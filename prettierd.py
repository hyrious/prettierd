import sublime
import sublime_plugin
import pathlib, socket, json, subprocess, threading, fnmatch
from .lib.diff_match_patch import diff_match_patch

__version__ = "0.1.0"

prettierd: "Prettierd | None" = None
save_without_format = False
def toggle_save_without_format(force=None, timeout=500):
    global save_without_format
    if force is None:
        save_without_format = not save_without_format
        sublime.set_timeout_async(lambda: toggle_save_without_format(force=False), timeout)
    else:
        save_without_format = force


def plugin_loaded():
    global prettierd
    prettierd = Prettierd()


def plugin_unloaded():
    global prettierd
    if prettierd:
        prettierd.terminate()


class Prettierd:
    def __init__(self):
        self.script = pathlib.Path(__file__).parent.joinpath('prettierd.mjs').resolve()
        self.settings = sublime.load_settings("prettier.sublime-settings")
        self.port = self.settings.get("port") or 9870
        self.seq = 0
        self.ready = False
        self.child: subprocess.Popen[bytes] | None = None
        self.on_done = lambda x: None
        self.terminated = False
        sublime.set_timeout_async(self.spawn_subprocess, 500)

    def spawn_subprocess(self):
        print('prettierd: spawning subprocess')
        sublime.status_message("Prettier: warming up...")
        si = None
        if sublime.platform() == "windows":
            si = subprocess.STARTUPINFO()                  # type: ignore
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore
        self.child = subprocess.Popen(
            ["node", self.script, str(self.port)],
            startupinfo=si,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.poll_ready_state()

    def poll_ready_state(self):
        if not self.child:
            return self.retry()
        try:
            io = self.child.stdout
            if not io:
                return self.retry()
            res = io.readline().decode('utf-8').rstrip()
            ret = json.loads(res) if res else None
            if ret and 'ok' in ret and ret['ok'] == self.port:
                self.ready = True
                self.refresh_statuses()
                sublime.status_message("Prettier: ready.")
                threading.Thread(target=self.poll_close_state).start()
            else:
                print('prettierd:', res)
                sublime.status_message("Prettier: something went wrong.")
                self.retry()
        except Exception as e:
            print('prettierd error in poll_ready_state:', e)
            self.retry()

    def retry(self):
        if self.terminated: return
        print('prettierd: retry')
        self.ready = False
        self.request("quit", timeout=100)
        sublime.set_timeout_async(self.spawn_subprocess, 3000)

    def poll_close_state(self):
        if not self.child:
            return;
        _, stderr = self.child.communicate()
        if stderr:
            msg = stderr.decode('utf-8')
            sublime.status_message(f"Prettier: {msg}")
        if b'EADDRINUSE' in stderr:
            self.retry()

    def terminate(self):
        if self.child: self.child.terminate()
        self.terminated = True
        self.clear_statuses()

    def each_view(self):
        for window in sublime.windows():
            yield from window.views()

    def clear_statuses(self):
        for view in self.each_view():
            view.erase_status("prettier")

    def refresh_statuses(self):
        for view in self.each_view():
            if view.get_status("prettier"): continue
            self.request_formattable(view, lambda x: self.on_formattable(x, view))

    def request_formattable(self, view, on_done):
        if not view.file_name(): return
        if self.is_ignored(view.file_name()): return
        timeout = self.settings.get("query_timeout")
        self.request("getFileInfo", { "path": view.file_name() }, timeout, on_done)

    def is_ignored(self, file_name):
        for p in self.settings.get("file_exclude_patterns"):
            if fnmatch.fnmatch(file_name, p): return True

    def on_formattable(self, ok, view):
        if "inferredParser" in ok:
            parser = ok["inferredParser"] or "off"
            view.set_status("prettier", f"Prettier ({parser})")
        elif "ignored" in ok and ok["ignored"] is True:
            view.set_status("prettier", f"Prettier (ignored)")

    def request_format(self, view, on_done):
        status = view.get_status("prettier")
        if not status: return sublime.status_message("Prettier: not ready")
        parser = status[10:-1]
        if parser in ('off', 'ignored'): return
        path = view.file_name()
        contents = view.substr(sublime.Region(0, view.size()))
        cursor = s[0].b if (s := view.sel()) else 0
        timeout = self.settings.get("format_timeout")
        payload = { 'path': path, 'contents': contents, 'parser': parser, 'cursor': cursor }
        sublime.status_message("Prettier: formatting...")
        self.request("format", payload, timeout, on_done)

    def on_format(self, ok, view, save_on_format=False):
        contents = view.substr(sublime.Region(0, view.size()))
        if "formatted" in ok and ok["formatted"] != contents:
            ok['save_on_format'] = save_on_format
            view.run_command("prettier_format", {
                'formatted': ok["formatted"],
                'cursor': ok['cursorOffset'],
                'save_on_format': save_on_format,
            })

    def do_replace(self, edit, view, formatted, cursor, save_on_format=False):
        original = view.substr(sublime.Region(0, view.size()))
        patches = diff_match_patch().patch_make(original, formatted)
        for obj in patches:
            point = obj.start1
            for i, text in obj.diffs:
                if i == 0:
                    point += len(text)
                elif i == 1:
                    view.insert(edit, point, text)
                    point += len(text)
                elif i == -1:
                    view.erase(edit, sublime.Region(point, point + len(text)))
        sel = view.sel()
        sel.clear()
        sel.add(sublime.Region(cursor, cursor))
        if save_on_format:
            sublime.set_timeout(lambda: view.run_command("save"), 100)
            sublime.set_timeout_async(lambda: sublime.status_message('Prettier: formatted.'), 110)
        else:
            sublime.status_message('Prettier: formatted.')

    def request(self, method, params=None, timeout=None, on_done=lambda x: None):
        if not self.ready: return
        self.seq += 1
        self.on_done = on_done
        sublime.set_timeout_async(lambda: self.request_sync(self.seq, method, params, timeout=timeout), 0)

    def make_request(self, seq, method, params):
        request = { 'id': seq, 'method': method, 'params': params }
        return bytes(json.dumps(request), 'utf-8')

    def request_sync(self, seq, method, params=None, timeout=None):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect(('localhost', self.port))
                s.sendall(self.make_request(seq, method, params))
                s.shutdown(socket.SHUT_WR)
                res = b''
                while True:
                    chunk = s.recv(512)
                    if not chunk: break
                    res += chunk
            if ret := json.loads(res):
                if 'err' in ret:
                    print('prettierd:', ret['err'])
                    sublime.status_message(f"Prettier: {ret['err']}")
                elif 'ok' in ret and self.seq == seq:
                    self.on_done(ret['ok'])
        except socket.timeout:
            sublime.status_message("Prettier: timeout")
        except Exception as e:
            print('prettierd error in request:', e)
            self.retry()

    def do_formattable(self, view):
        self.request_formattable(view, lambda x: self.on_formattable(x, view))

    def do_format(self, view, save_on_format=False):
        self.request_format(view, lambda x: self.on_format(x, view, save_on_format=save_on_format))

    def do_clear_cache(self):
        self.request("clearConfigCache")


class PrettierFormat(sublime_plugin.TextCommand):
    def run(self, edit, save_on_format=False, formatted=None, cursor=0):
        if not prettierd or not prettierd.ready:
            return
        if formatted:
            prettierd.do_replace(edit, self.view, formatted, cursor, save_on_format=save_on_format)
        else:
            prettierd.do_format(self.view, save_on_format=save_on_format)


class PrettierSaveWithoutFormat(sublime_plugin.TextCommand):
    def run(self, _):
        toggle_save_without_format()
        self.view.run_command("save")


class PrettierListener(sublime_plugin.EventListener):
    def on_pre_save(self, view):
        if prettierd and not save_without_format and prettierd.settings.get('format_on_save'):
            save_on_format = prettierd.settings.get('save_on_format')
            view.run_command('prettier_format', { 'save_on_format': save_on_format })

    def on_post_save(self, view):
        if prettierd and view.file_name() and '.prettierrc' in view.file_name():
            prettierd.do_clear_cache()

    def on_activated(self, view):
        if prettierd:
            prettierd.do_formattable(view)

    def on_exit(self):
        if prettierd:
            prettierd.terminate()


class PrettierClearCache(sublime_plugin.ApplicationCommand):
    def run(self):
        if prettierd:
            prettierd.do_clear_cache()
