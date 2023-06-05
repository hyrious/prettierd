#
# Protocol see ./prettier.mjs
#
import sublime, sublime_plugin
import os, pathlib, socket, json, subprocess, threading, fnmatch
from .lib.diff_match_patch import diff_match_patch
from .lib.utils import tcp_request, make_request, get_file_extension_from_view, get_parser_from_ext

__version__ = "0.2.0"

script = pathlib.Path(__file__).parent.joinpath('prettierd.mjs').resolve()

save_without_format = False

server = ('localhost', 9870)
seq = 0
ready = False
respawning = False


def load_settings():
    return sublime.load_settings('prettier.sublime-settings')


def call(*args, **kwargs):
    global seq
    seq += 1
    return tcp_request(server, make_request(*args, seq=seq, **kwargs))


def plugin_loaded():
    global server
    settings = load_settings()
    port = settings.get('port') or 9870
    if port != 9870: server = ('localhost', port)
    # try get existing server
    sublime.set_timeout_async(knock_knock)


def plugin_unloaded():
    sublime.set_timeout_async(clear_status)


def clear_status():
    for window in sublime.windows():
        for view in window.views():
            view.erase_status("prettier")


def quit_away():
    try:
        call("quit")
    except:
        pass


def knock_knock():
    global ready
    try:
        data = call("ping")
        response = sublime.decode_value(data)
        if "ok" in response:
            print("prettierd: use existing server")
            sublime.status_message("Prettier: ready.")
            ready = True
            sublime.set_timeout_async(refresh_views)
            return
    except:
        pass
    # no existing server, spawn one
    quit_away()
    spawn_subprocess()


def spawn_subprocess():
    global ready
    print("prettierd: spawning subprocess")
    sublime.status_message("Prettier: warming up...")
    si = None
    if sublime.platform() == "windows":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    proc = subprocess.Popen(
        ["node", script, str(server[1]), str(os.getpid())],
        startupinfo=si,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    io = proc.stdout
    res = io.readline()
    if "EADDRINUSE" in res:
        print("prettierd: conflict with existing server?")
        quit_away()
        return sublime.set_timeout_async(spawn_subprocess, 3000)
    print("prettierd:", res, end='')
    if "ok" in sublime.decode_value(res):
        print("prettierd: spawn success")
        sublime.status_message("Prettier: ready.")
        ready = True
        sublime.set_timeout_async(refresh_views)
        return


def regenerate():
    global respawning
    if respawning: return
    print("prettierd: server down, respawning...")
    respawning = True
    ready = False
    quit_away()
    spawn_subprocess()
    respawning = False


def refresh_views():
    for window in sublime.windows():
        for view in window.views():
            check_formattable(view)


def check_formattable(view):
    filename = view.file_name()
    if not filename:
        if ext := get_file_extension_from_view(view):
            filename = 'main' + ext
    if not filename: return
    if is_ignored(filename): return view.set_status("prettier", f"Prettier (ignored)")
    try:
        data = call('getFileInfo', { "path": filename })
    except:
        return sublime.set_timeout_async(regenerate)
    response = sublime.decode_value(data)
    if "ok" in response:
        ok = response["ok"]
        if "inferredParser" in ok:
            parser = ok["inferredParser"] or "off"
            view.set_status("prettier", f"Prettier ({parser})")
        elif "ignored" in ok and ok["ignored"] is True:
            view.set_status("prettier", f"Prettier (ignored)")


def is_ignored(filename):
    settings = load_settings()
    for p in settings.get('file_exclude_patterns') or []:
        if fnmatch.fnmatch(filename, p): return True


class PrettierFormat(sublime_plugin.TextCommand):
    def run(self, edit, save_on_format=False, force=False, formatted=None, cursor=None):
        if not ready: return
        if formatted:
            self.replace(edit, formatted, cursor=cursor, save_on_format=save_on_format)
        else:
            self.format(save_on_format=save_on_format, force=force)

    def replace(self, edit, formatted, cursor=None, save_on_format=False):
        original = self.view.substr(sublime.Region(0, self.view.size()))
        patches = diff_match_patch().patch_make(original, formatted)
        for obj in patches:
            point = obj.start1
            for i, text in obj.diffs:
                if i == 0:
                    point += len(text)
                elif i == 1:
                    self.view.insert(edit, point, text)
                    point += len(text)
                elif i == -1:
                    self.view.erase(edit, sublime.Region(point, point + len(text)))
        if cursor is not None:
            sel = self.view.sel()
            sel.clear()
            sel.add(sublime.Region(cursor, cursor))
        if save_on_format:
            sublime.set_timeout(lambda: self.view.run_command("save", { 'quiet': True, 'async': True }), 100)
            sublime.set_timeout_async(lambda: sublime.status_message('Prettier: formatted.'), 110)
        else:
            sublime.status_message('Prettier: formatted.')

    def format(self, save_on_format=False, force=False):
        sublime.set_timeout_async(lambda: self._format(save_on_format=save_on_format, force=force))

    def _format(self, save_on_format=False, force=False):
        status = self.view.get_status('prettier')
        if not status: return sublime.status_message('Prettier: not ready.')
        parser = status[10:-1]
        if not force and parser in ('off', 'ignored'): return
        path = self.view.file_name()
        if self._too_large(): return self._format_manually(path, save_on_format=save_on_format)
        ext = None
        if path:
            i = path.rfind('.')
            if i != -1:
                ext = path[i:]
        if not path:
            ext = get_file_extension_from_view(self.view)
            if not ext: return
            path = "main" + ext
        if parser in ('off', 'ignored'):
            parser = get_parser_from_ext(ext)
            if not parser: return
        contents = self.view.substr(sublime.Region(0, self.view.size()))
        cursor = s[0].b if (s := self.view.sel()) else 0
        params = { "path": path, "contents": contents, "parser": parser, "cursor": cursor }
        try:
            data = call("format", params)
        except:
            return sublime.set_timeout_async(regenerate)
        response = sublime.decode_value(data)
        if "ok" in response and "formatted" in response["ok"]:
            if response["ok"]["formatted"] == contents:
                sublime.status_message('Prettier: unchanged.')
            else:
                self.view.run_command("prettier_format", {
                    "formatted": response["ok"]["formatted"],
                    "cursor": response["ok"]["cursorOffset"],
                    "save_on_format": save_on_format
                })
        elif "err" in response:
            print(response["err"])
            sublime.status_message('Prettier: open console to see error message.')

    def _format_manually(self, path: str, save_on_format=False):
        si = None
        is_windows = sublime.platform() == "windows"
        cmd = "prettier.cmd" if is_windows else "prettier"
        cursor = self.view.sel()[0].a
        if is_windows:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            proc = subprocess.Popen(
                [cmd, path, '--cursor-offset', str(cursor)],
                startupinfo=si,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
            )
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            sublime.status_message("Prettier: timeout.")
            return
        if proc.returncode != 0:
            print(stderr)
            sublime.status_message("Prettier: open console to see error message.")
            return
        if stderr:
            cursor = int(stderr)
        if stdout == self.view.substr(sublime.Region(0, self.view.size())):
            sublime.status_message('Prettier: unchanged.')
        else:
            self.view.run_command("prettier_format", {
                "formatted": stdout,
                "save_on_format": save_on_format
            })

    def _too_large(self):
        settings = load_settings()
        max_size = settings.get('max_size') or 10240
        if max_size < 0: max_size = 10240
        return self.view.size() >= max_size


class PrettierSaveWithoutFormat(sublime_plugin.TextCommand):
    def run(self, edit):
        global save_without_format
        save_without_format = True
        sublime.set_timeout_async(self._restore, 500)
        sublime.set_timeout(lambda: self.view.run_command("save", { 'quiet': True, 'async': True }), 100)

    def _restore(self):
        global save_without_format
        save_without_format = False


class PrettierClearCache(sublime_plugin.ApplicationCommand):
    def run(self):
        if not ready: return
        call("clearConfigCache")
        sublime.status_message('Prettier: cleared cache.')


class PrettierRestart(sublime_plugin.ApplicationCommand):
    def run(self):
        if not ready: return
        sublime.set_timeout_async(regenerate)
        sublime.status_message('Prettier: restarting...')


class PrettierListener(sublime_plugin.EventListener):
    def on_exit(self):
        quit_away()

    def on_pre_save(self, view):
        settings = load_settings()
        if not ready or save_without_format or not settings.get('format_on_save'): return
        save_on_format = settings.get('save_on_format')
        max_size = settings.get('max_size') or 10240
        if max_size < 0 or view.size() < max_size:
            view.run_command('prettier_format', { 'save_on_format': save_on_format })

    def on_post_save(self, view):
        if not ready: return
        call("clearConfigCache")

    def on_activated(self, view):
        if not ready: return
        sublime.set_timeout_async(lambda: check_formattable(view))
