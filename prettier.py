import sublime
import sublime_plugin
import pathlib, socket, json, subprocess, threading

__version__ = '0.1.0'

prettierd = None


def plugin_loaded():
    global prettierd
    prettierd = Prettierd()


def plugin_unloaded():
    global prettierd
    if prettierd: prettierd.terminate()


class Prettierd:
    SCRIPT = pathlib.Path(__file__).parent.joinpath('prettierd.mjs').resolve()
    PORT = 9870

    def __init__(self):
        settings = sublime.load_settings('prettier.sublime-settings')
        self.port = settings.get('port') or self.PORT
        self.seq = 0
        self.ready = False
        self.save_on_format = False
        sublime.set_timeout_async(self.spawn_child_process, 1000)

    def spawn_child_process(self):
        print('prettierd: spawning child process')
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        self.child = subprocess.Popen(
            ["node", self.SCRIPT, str(self.port)],
            startupinfo=si,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)
        threading.Thread(target=self.poll_ready_state).start()

    def poll_ready_state(self):
        hello = self.child.stdout.readline().decode('utf-8').rstrip()
        print('prettierd:', hello)
        self.ready = True
        sublime.status_message("Prettier: ready.")
        # while line := self.child.stdout.readline():
        #     print('prettierd:', line.decode('utf-8').rstrip())
        #     pass
        threading.Thread(target=self.poll_close_state).start()

    def poll_close_state(self):
        stdout, stderr = self.child.communicate()
        # in case we met last zombie process, kill it by sending a request
        if b'EADDRINUSE' in stderr:
            self.ready = False
            self.request('close', None)
            self.spawn_child_process()

    def formatable(self, view):
        if not view.file_name(): return None
        info = self.request('getFileInfo', { 'path': view.file_name() })
        return info and info['inferredParser']

    def format(self, edit, view, save_on_format=False):
        if parser := self.formatable(view):
            self.save_on_format = save_on_format
            self.do_format(edit, view, parser)

    def clear_cache(self):
        self.request('clearConfigCache', None)

    def do_format(self, edit, view, parser):
        path = view.file_name()
        contents = view.substr(sublime.Region(0, view.size()))
        cursor = view.sel()[0].b
        payload = { 'path': path, 'contents': contents, 'parser': parser, 'cursorOffset': cursor }
        result = self.request('format', payload)
        formatted = result and result['formatted']
        if formatted and contents != formatted:
            self.do_replace(edit, view, result)

    def do_replace(self, edit, view, result):
        formatted = result['formatted']
        cursor = result['cursorOffset']
        view.replace(edit, sublime.Region(0, view.size()), formatted)
        sel = view.sel()
        sel.clear()
        sel.add(sublime.Region(cursor, cursor))
        if self.save_on_format:
            sublime.set_timeout(lambda: view.run_command("save"), 100)
        sublime.status_message("Formatted.")

    def request(self, method, params):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect(('localhost', self.port))
            data = self.make_request(method, params)
            s.sendall(data)
            s.shutdown(socket.SHUT_WR)
            res = b''
            while True:
                chunk = s.recv(512)
                if not chunk: break
                res += chunk
        if result := json.loads(res):
            if 'error' in result:
                print(result['error'])
            elif 'result' in result:
                return result['result']

    def make_request(self, method, params):
        self.seq += 1
        request = { 'id': self.seq, 'method': method, 'params': params }
        return bytes(json.dumps(request), 'utf-8')

    def terminate(self):
        print('prettierd: terminate')
        self.child.kill()
        self.child.terminate()


class PrettierCommand(sublime_plugin.TextCommand):

    def run(self, edit, save_on_format=False):
        if not prettierd.ready: return
        prettierd.format(edit, self.view, save_on_format=save_on_format)


class PrettierFormatOnSave(sublime_plugin.EventListener):

    def on_pre_save_async(self, view):
        settings = sublime.load_settings('prettier.sublime-settings')
        if settings.get('format_on_save'):
            save_on_format = settings.get('save_on_format')
            view.run_command('prettier', { 'save_on_format': save_on_format })

    def on_post_save_async(self, view):
        if not prettierd.ready: return
        if '.prettierrc' in view.file_name():
            prettierd.clear_cache()

    def on_activated_async(self, view):
        if not prettierd.ready: return
        if parser := prettierd.formatable(view):
            view.set_status('prettier', f'Prettier ({parser})')
        else:
            view.erase_status('prettier')


class PrettierClearCache(sublime_plugin.ApplicationCommand):

    def run(self):
        if not prettierd.ready: return
        prettierd.clear_cache()
