#
# Protocol see ./prettier.mjs
#
import sublime, sublime_plugin
import pathlib, socket, json, subprocess, threading, fnmatch
from .lib.diff_match_patch import diff_match_patch
from .lib.utils import tcp_request, make_request, get_file_extension_from_view

__version__ = "0.2.0"

script = pathlib.Path(__file__).parent.joinpath('prettierd.mjs').resolve()

save_without_format = False

settings = None
server = ('localhost', 9870)
seq = 0
ready = False


def plugin_loaded():
    global settings
    settings = sublime.load_settings('prettier.sublime-settings')
    port = settings.get('port') or 9870
    if port != 9870: server = ('localhost', port)
    # try get existing server
    sublime.set_timeout_async(knock_knock)


def quit_away():
    try:
        tcp_request(server, make_request("quit"))
    except:
        pass


def knock_knock():
    global ready
    try:
        data = tcp_request(server, make_request("ping"))
        response = sublime.decode_value(data)
        if "ok" in response:
            print("prettierd: use existing server")
            sublime.status_message("Prettier: ready.")
            ready = True
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
        ["node", script, str(server[1])],
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
    if "ok" in sublime.decode_value(res):
        print("prettierd: spawn success")
        sublime.status_message("Prettier: ready.")
        ready = True


class PrettierFormat(sublime_plugin.TextCommand):
    def run(self, edit, save_on_format=False, formatted=None, cursor=0):
        if not ready: return
        if formatted:
            self.replace(edit, formatted, cursor, save_on_format=save_on_format)
        else:
            self.format(save_on_format=save_on_format)

    def replace(self, edit, formatted, cursor, save_on_format=False):
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
        sel = self.view.sel()
        sel.clear()
        sel.add(sublime.Region(cursor, cursor))
        if save_on_format:
            sublime.set_timeout(lambda: self.view.run_command("save"), 100)
            sublime.set_timeout_async(lambda: sublime.status_message('Prettier: formatted.'), 110)
        else:
            sublime.status_message('Prettier: formatted.')

    def format(self, save_on_format=False):
        sublime.set_timeout_async(lambda: self._format(save_on_format=save_on_format))

    def _format(self, save_on_format=False):
        global seq
        status = self.view.get_status('prettier')
        if not status: return sublime.status_message('Prettier: not ready.')
        parser = status[10:-1]
        if parser in ('off', 'ignored'): return
        path = self.view.file_name()
        if not path:
            ext = get_file_extension_from_view(self.view)
            if not ext: return
            path = "main" + ext
        contents = self.view.substr(sublime.Region(0, self.view.size()))
        cursor = s[0].b if (s := self.view.sel()) else 0
        params = { "path": path, "contents": contents, "parser": parser, "cursor": cursor }
        seq += 1
        data = tcp_request(server, make_request("format", params, seq))
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


class PrettierSaveWithoutFormat(sublime_plugin.TextCommand):
    def run(self, edit):
        global save_on_format
        save_without_format = True
        sublime.set_timeout_async(self._restore, 500)
        self.view.run_command("save")

    def _restore(self):
        global save_on_format
        save_without_format = False


class PrettierClearCache(sublime_plugin.ApplicationCommand):
    def run(self):
        if not ready: return
        tcp_request(server, make_request("clearConfigCache", seq=seq))


class PrettierListener(sublime_plugin.EventListener):
    def on_exit(self):
        quit_away()

    def on_pre_save(self, view):
        if not ready or save_without_format or not settings.get('format_on_save'): return
        save_on_format = settings.get('save_on_format')
        view.run_command('prettier_format', { 'save_on_format': save_on_format })

    def on_post_save(self, view):
        if not ready: return
        tcp_request(server, make_request("clearConfigCache", seq=seq))

    def on_activated(self, view):
        if not ready: return
        sublime.set_timeout_async(lambda: self._formattable(view))

    def _formattable(self, view):
        filename = view.file_name()
        if not filename:
            if ext := get_file_extension_from_view(view):
                filename = 'main' + ext
        if not filename: return
        if self._ignored(filename): return
        data = tcp_request(server, make_request('getFileInfo', { "path": filename }))
        response = sublime.decode_value(data)
        if "ok" in response:
            ok = response["ok"]
            if "inferredParser" in ok:
                parser = ok["inferredParser"] or "off"
                view.set_status("prettier", f"Prettier ({parser})")
            elif "ignored" in ok and ok["ignored"] is True:
                view.set_status("prettier", f"Prettier (ignored)")

    def _ignored(self, filename):
        for p in settings.get('file_exclude_patterns') or []:
            if fnmatch.fnmatch(filename, p): return True
