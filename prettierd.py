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
            status_verbose("Prettier: ready.")
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
    status_verbose("Prettier: warming up...")
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
        status_verbose("Prettier: ready.")
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
    if view.get_status("prettier"): return
    filename = view.file_name()
    if not filename:
        if ext := get_file_extension_from_view(view):
            filename = 'main' + ext
    if not filename: return
    if is_ignored(filename):
        return view.set_status("prettier", f"Prettier (ignored)")
    if parser := is_overridden(filename):
        return view.set_status("prettier", f"Prettier ({parser})")
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
    filename = os.path.basename(filename)
    for p in settings.get('file_exclude_patterns') or []:
        if fnmatch.fnmatch(filename, p): return True


def is_overridden(filename):
    settings = load_settings()
    filename = os.path.basename(filename)
    overrides = settings.get("overrides", {})
    for p in overrides:
        if fnmatch.fnmatch(filename, p): return overrides[p]
    return None


def is_status_verbose():
    settings = load_settings()
    return settings.get('status_level') == 'verbose'


def status_verbose(message):
    if is_status_verbose():
        sublime.status_message(message)


def status_error(message):
    sublime.status_message(message)


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
        if cursor and cursor > 0:
            sel = self.view.sel()
            sel.clear()
            sel.add(sublime.Region(cursor, cursor))
        if save_on_format:
            sublime.set_timeout(lambda: self.view.run_command("save", { 'quiet': True, 'async': True }), 100)
            sublime.set_timeout_async(lambda: status_verbose('Prettier: formatted.'), 110)
        else:
            status_verbose('Prettier: formatted.')

    def format(self, save_on_format=False, force=False):
        sublime.set_timeout_async(lambda: self._format(save_on_format=save_on_format, force=force))

    def _format(self, save_on_format=False, force=False):
        settings = load_settings()
        status = self.view.get_status('prettier')
        if not status: return status_error('Prettier: not ready.')
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
        if parser == 'svelte' or not settings.get("cursor", False): cursor = None
        params = { "path": path, "contents": contents, "parser": parser, "cursor": cursor }
        try:
            data = call("format", params)
        except:
            return sublime.set_timeout_async(regenerate)
        response = sublime.decode_value(data)
        if "ok" in response and "formatted" in response["ok"]:
            if response["ok"]["formatted"] == contents:
                status_verbose('Prettier: unchanged.')
            else:
                self.view.run_command("prettier_format", {
                    "formatted": response["ok"]["formatted"],
                    "cursor": response["ok"]["cursorOffset"],
                    "save_on_format": save_on_format
                })
        elif "err" in response:
            print(response["err"])
            status_error('Prettier: open console to see error message.')

    def _format_manually(self, path: str, save_on_format=False):
        settings = load_settings()
        si = None
        is_windows = sublime.platform() == "windows"
        cmd = "prettier.cmd" if is_windows else "prettier"
        cursor = self.view.sel()[0].a
        if is_windows:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        try:
            args = [cmd, path]
            if settings.get("cursor", False):
                args.append('--cursor-offset')
                args.append(str(cursor))
            proc = subprocess.Popen(
                args,
                startupinfo=si,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
            )
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            status_error("Prettier: timeout.")
            return
        if proc.returncode != 0:
            print(stderr)
            status_error("Prettier: open console to see error message.")
            return
        if stderr:
            cursor = int(stderr)
        if stdout == self.view.substr(sublime.Region(0, self.view.size())):
            status_verbose('Prettier: unchanged.')
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
        clear_status()
        status_error('Prettier: cleared cache.')


class PrettierRestart(sublime_plugin.ApplicationCommand):
    def run(self):
        if not ready: return
        sublime.set_timeout_async(regenerate)
        status_error('Prettier: restarting...')


class PrettierListener(sublime_plugin.EventListener):
    def on_exit(self):
        quit_away()

    def on_pre_save(self, view):
        settings = load_settings()
        if not ready or save_without_format: return
        format_on_save = settings.get('format_on_save')
        if not format_on_save: return
        if format_on_save == "explicit":
            if not self._has_prettierrc(view.file_name()):
                return
        save_on_format = settings.get('save_on_format')
        max_size = settings.get('max_size') or 10240
        if max_size < 0 or view.size() < max_size:
            view.run_command('prettier_format', { 'save_on_format': save_on_format })

    def on_post_save(self, view):
        if not ready: return
        filename = view.file_name()
        if not filename: return
        filename = os.path.basename(filename)
        if filename == 'package.json' or 'prettierrc' in filename:
            call("clearConfigCache")

    def on_activated(self, view):
        if not ready: return
        sublime.set_timeout_async(lambda: check_formattable(view))

    def _has_prettierrc(self, p):
        if not p: return False
        while True:
            folder = os.path.dirname(p)
            if folder == p or not os.path.isdir(folder): return False
            names = os.listdir(folder)
            for name in names:
                if 'prettierrc' in name:
                    return True
            if 'package.json' in names:
                return False
            p = folder
        return False
