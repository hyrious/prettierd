import sublime
import sublime_plugin
import asyncio, pathlib, socket, json, subprocess, threading
from .lib.diff_match_patch import diff_match_patch

__version__ = "0.1.0"

prettierd = None


def plugin_loaded():
    global prettierd
    prettierd = Prettierd()


def plugin_unloaded():
    global prettierd
    prettierd.terminate()


# Run a callback in the ONLY-ONE worker thread provided by Sublime.
# Callbacks in that thread will be executed one by one, blocking each other.
# If you really want to do some async work in other threads,
# use `threading.Thread()`.
def run_in_worker_thread(function, timeout=0):
    sublime.set_timeout_async(function, timeout)


# Run a callback (-> coroutine) in a new `threading.Thread()`. Refer to
# https://gist.github.com/dmfigol/3e7d5b84a16d076df02baa9f53271058
def run_in_new_thread(function, *args, **kwargs):

    # The "loop" holder.
    loop = asyncio.new_event_loop()

    # Kick start the event loop.
    def wrapper(loop):
        asyncio.set_event_loop(loop)
        loop.run_forever()

    # Send wrapper to a new thread with the loop.
    t = threading.Thread(target=wrapper, args=(loop,))
    t.start()

    # Run the callback with the loop.
    coro = function(*args, **kwargs)
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    # `await future` to wait for it.

    return future


# Spawn a new child process asynchronously.
# Returns (process, firstline from stdout).
async def spawn(*args):
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        startupinfo=si,
    )
    data = await proc.stdout.readline()
    line = data.decode("utf-8").rstrip()
    return proc, line


async def retry_if_needed(proc, retry, *args):
    stdout, stderr = await proc.communicate()
    if stderr:
        msg = stderr.decode("utf-8")
        sublime.status_message(f"Prettier: {msg}")
    if b"EADDRINUSE" in stderr:
        sublime.status_message("Prettier: warming up (again)...")
        await retry(*args)


async def spawn_daemon(*args, on_proc=lambda x: None, on_ok=lambda x: None, on_err=lambda x: None):
    try:
        proc, line = await spawn(*args)
        on_proc(proc)
        ret = json.loads(line) if line else None
        if ret and "ok" in ret:
            on_ok(ret)
        else:
            on_err(line)
            raise Exception(line)
    except:
        await retry_if_needed(proc, spawn_daemon, *args, on_proc, on_ok, on_err)


class Prettierd:
    def __init__(self):
        self.script = pathlib.Path(__file__).parent.joinpath("prettierd.mjs").resolve()
        self.settings = sublime.load_settings("prettier.sublime-settings")
        self.port = self.settings.get("port") or 9870
        self.seq = 0
        self.ready = False
        self.child = None
        self.on_done = lambda x: None
        sublime.status_message("Prettier: warming up...")
        run_in_new_thread(
            spawn_daemon, "node", self.script, str(self.port),
            on_proc=self.on_spawn_daemon_proc,
            on_ok=self.on_spawn_daemon_ok,
            on_err=self.on_spawn_daemon_err
        )

    def on_spawn_daemon_proc(self, proc):
        self.child = proc

    def on_spawn_daemon_ok(self, ret):
        print("prettierd:", ret)
        self.ready = True
        self.refresh_statuses()
        sublime.status_message("Prettier: ready.")

    def on_spawn_daemon_err(self, line):
        print("prettierd error on spawn:", line)
        sublime.status_message("Prettier: something went wrong.")

    def terminate(self):
        print("prettierd: terminate")
        if self.child:
            self.child.terminate()
        self.clear_statuses()

    def each_view(self):
        for window in sublime.windows():
            yield from window.views()

    def clear_statuses(self):
        for view in self.each_view():
            view.erase_status("prettier")

    def refresh_statuses(self):
        for view in self.each_view():
            if not view.get_status("prettier"):
                self.request_formattable(view, lambda x: self.on_formattable(x, view))

    def request_formattable(self, view, on_done):
        if view.file_name():
            timeout = self.settings.get("query_timeout")
            self.request("getFileInfo", {"path": view.file_name()}, timeout, on_done)

    def on_formattable(self, ok, view):
        if "inferredParser" in ok:
            parser = ok["inferredParser"] or "off"
            view.set_status("prettier", f"Prettier ({parser})")
        elif "ignored" in ok and ok["ignored"] is True:
            view.set_status("prettier", f"Prettier (ignored)")

    def request_format(self, view, on_done):
        status = view.get_status("prettier")
        if not status:
            return sublime.status_message("Prettier: not ready.")
        parser = status[10:-1]
        if parser in ("off", "ignored"):
            return
        path = view.file_name()
        contents = view.substr(sublime.Region(0, view.size()))
        cursor = s[0].b if (s := view.sel()) else 0
        timeout = self.settings.get("format_timeout")
        payload = dict(path=path, contents=contents, parser=parser, cursor=cursor)
        sublime.status_message("Prettier: formatting...")
        self.request("format", payload, timeout, on_done)

    def on_format(self, ok, view, save_on_format=False):
        contents = view.substr(sublime.Region(0, view.size()))
        if "formatted" in ok and ok["formatted"] != contents:
            ok["save_on_format"] = save_on_format
            view.run_command(
                "prettier_format",
                {
                    # pass the formatted argument to trigger "do_replace"
                    "formatted": ok["formatted"],
                    "cursor": ok["cursorOffset"],
                    "save_on_format": save_on_format,
                },
            )

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
            sublime.set_timeout(lambda: sublime.status_message("Prettier: formatted."), 110)
        else:
            sublime.status_message("Prettier: formatted.")

    def request(self, method, params=None, timeout=None, on_done=lambda x: None):
        if self.ready:
            self.seq += 1
            self.on_done = on_done
            run_in_worker_thread(lambda: self.request_sync(self.seq, method, params, timeout=timeout))

    def make_request(self, seq, method, params):
        request = {"id": seq, "method": method, "params": params}
        return bytes(json.dumps(request), "utf-8")

    def request_sync(self, seq, method, params=None, timeout=None):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect(("localhost", self.port))
                s.sendall(self.make_request(seq, method, params))
                s.shutdown(socket.SHUT_WR)
                res = b""
                while True:
                    chunk = s.recv(512)
                    if not chunk:
                        break
                    res += chunk
            if ret := json.loads(res):
                if "err" in ret:
                    print("prettierd:", ret["err"])
                    sublime.status_message(f"Prettier: {ret['err']}")
                elif "ok" in ret and self.seq == seq:
                    self.on_done(ret["ok"])
        except socket.timeout:
            sublime.status_message("Prettier: timeout")
        except Exception as e:
            print("prettierd error in request:", e)

    def do_formattable(self, view):
        self.request_formattable(view, lambda x: self.on_formattable(x, view))

    def do_format(self, view, save_on_format=False):
        self.request_format(view, lambda x: self.on_format(x, view, save_on_format=save_on_format))

    def do_clear_cache(self):
        self.request("clearConfigCache")


class PrettierFormat(sublime_plugin.TextCommand):
    def run(self, edit, save_on_format=False, formatted=None, cursor=0):
        if prettierd.ready:
            if formatted:
                prettierd.do_replace(edit, self.view, formatted, cursor, save_on_format=save_on_format)
            else:
                prettierd.do_format(self.view, save_on_format=save_on_format)


class PrettierListener(sublime_plugin.EventListener):
    def on_pre_save(self, view):
        if prettierd.settings.get("format_on_save"):
            save_on_format = prettierd.settings.get("save_on_format")
            view.run_command("prettier_format", {"save_on_format": save_on_format})

    def on_post_save(self, view):
        if view.file_name() and ".prettierrc" in view.file_name():
            prettierd.do_clear_cache()

    def on_activated(self, view):
        prettierd.do_formattable(view)

    def on_exit(self):
        prettierd.terminate()


class PrettierClearCache(sublime_plugin.ApplicationCommand):
    def run(self):
        prettierd.do_clear_cache()
