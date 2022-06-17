from sublime import View, load_resource

def get_file_extension_from_view(view: View):
    name = view.file_name()
    if name:
        i = name.rfind('.')
        if i != -1:
            return name[i:]
    syntax = view.syntax()
    if syntax:
        raw = load_resource(syntax.path)
        if syntax.path.endswith('.sublime-syntax'):
            i = raw.find('file_extensions:')
            raw = raw[i+len('file_extensions:'):].lstrip()
            if raw[0] == '-':
                return '.' + raw[1:raw.find('\n')].strip()
    return None
