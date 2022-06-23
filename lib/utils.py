import sublime
import socket, json

# tcp_request(('localhost', 9870), { "method": "quit" }) => "data"
def tcp_request(server, request):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.connect(server)
        client.sendall(bytes(json.dumps(request), "utf-8"))
        client.shutdown(socket.SHUT_WR)
        data = b""
        while True:
            chunk = client.recv(512)
            if chunk:
                data += chunk
            else:
                break
        return data.decode('utf-8')

# make_request("quit") => { "method": "quit" }
def make_request(method, params=None, seq=0):
    return { "method": method, "params": params, "seq": seq }

# get_file_extension_from_view(view) => '.js'
def get_file_extension_from_view(view: sublime.View):
    name = view.file_name()
    if name:
        i = name.rfind('.')
        if i != -1:
            return name[i:]
    syntax = view.syntax()
    if syntax:
        raw = sublime.load_resource(syntax.path)
        if syntax.path.endswith('.sublime-syntax'):
            i = raw.find('file_extensions:')
            raw = raw[i+len('file_extensions:'):].lstrip()
            if raw[0] == '-':
                return '.' + raw[1:raw.find('\n')].strip()
    return None
