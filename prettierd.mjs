//
// Protocol
//
// All messages are represented in JSON. I know JSON is not fast,
// but it should just be ok.
//
// So, the prettierd.py controls a subprocess which spawns "node {this_file}".
//
// We identify the start is success with an one-line log: {"ok":9870},
// which means we are listening on port 9870.
// Any other text it read means it failed.
//
// Then, we start a simple TCP server to perform request-response based
// communication. A request is ended with its write stream being shutdown.
//
// Not using stdin-stdout is for multiple request can be handled asynchronously.
//
// [Seq-Graph]
// py: knock knock, is you alive? (tcp.send(9870, { method: "ping" }))
// js: pong             // wow, use it
//     ...              // error or timeout!
//
// py: spawn js, read one line from stdout (in a thread)
// js: load prettier, start the server, log {"ok":9870}
//
// py: ok I know you are alive, tell me if "a.mjs" is formattable?
// js: {"ok":"babel"}   // returns the parser, can be null if not formattable.
//     {"err":"reason"} // something went wrong.
//     ...              // timeout!
// if ok, the py part marks the file as formattable or not.
// if err, the py part prints the error message and do nothing.
// if timeout, assume the node process die. Try re-spawn.
//
// py: ok please format this file "a.mjs", and the parser is "babel".
// js: {"ok":"a = 1;\n"} // returns the formatted result.
//     {"err":"reason"}  // something went wrong.
//     ...               // timeout!
//
// Unfortunately, python subprocessing is a bit buggy, given:
// 1. Sublime Text is always using the same plugin process to run python code.
// 2. Python is always creating a *detached* subprocess.
// 3. Python cannot send SIGINT correctly, it can only terminate directly.
//    To prevent zombie process, we have to send { method: "quit" }.
import { existsSync, writeFileSync } from 'fs'
import { spawnSync } from 'child_process'
import { join } from 'path'
import { pathToFileURL } from 'url'
import { createServer } from 'net'

const exit = process.exit

process.stdin.on('data', e => {
  if (e.toString().startsWith('q')) exit(2)
})

function import_prettier() {
  const win = process.platform === 'win32'
  // npm root -g is slow, test known locations first
  let global_path = win
    ? join(process.env.APPDATA, 'npm', 'node_modules')
    : process.platform === 'darwin'
      ? '/opt/homebrew/lib/node_modules'
      : '/usr/local/lib/node_modules'

  if (!existsSync(global_path)) {
    let npm = win ? 'npm.cmd' : 'npm'
    global_path = spawnSync(npm, ['root', '-g'], { shell: !!win }).stdout.toString().trimEnd()
  }

  let prettier_path = join(global_path, 'prettier/index.js')
  if (!existsSync(prettier_path)) {
    prettier_path = join(global_path, 'prettier/index.mjs')
    if (!existsSync(prettier_path)) {
      console.log('{"err":"not found prettier, is it installed?"}')
      exit(1)
    }
  }

  return import(pathToFileURL(prettier_path))
}

function create_server(port, handler) {
  let server = createServer({ allowHalfOpen: true }, handler)
  server.on('error', err => console.error(err.message))
  server.listen(port, () => console.log('{"ok":%d}', port))
  return server
}

function get_port() {
  return Number(process.env.PORT) || Number.parseInt(process.argv[2]) || 9870
}

function get_ppid() {
  return Number(process.env.PPID) || Number.parseInt(process.argv[3]) || 0
}

function is_running(pid) {
  try {
    return process.kill(pid, 0)
  } catch (error) {
    return error.code === 'EPERM'
  }
}

// let [ok, err] = await go(do_some_async_work_which_may_throw_error)
// if (err) console.log(...)
async function go(promise) {
  try {
    return [await promise]
  } catch (error) {
    return [, error]
  }
}

const PORT = Symbol('port')
const MODULE = Symbol('module')
const HANDLE = Symbol('handle')
const ON_QUIT = Symbol('onQuit')

class Prettied {
  constructor(on_quit) {
    this[PORT] = get_port()
    this[MODULE] = import_prettier()
    this[ON_QUIT] = on_quit
  }
  [HANDLE](con) {
    let chunks = []
    con.on('data', chunk => chunks.push(chunk))
    con.on('end', async () => {
      let raw = Buffer.concat(chunks).toString()
      const { id, method, params } = JSON.parse(raw)
      if (method === 'quit') {
        this[ON_QUIT](con)
      } else if (method in this) {
        const [ok, err] = await go(this[method](params))
        if (err) {
          con.end(JSON.stringify({ id, err: String(err) }))
        } else {
          con.end(JSON.stringify({ id, ok }))
        }
      } else {
        con.end(JSON.stringify({ id, err: 'NoSuchMethod: ' + method }))
      }
    })
  }
  async getSupportInfo(_) {
    let { default: prettier } = await this[MODULE]
    return prettier.getSupportInfo()
  }
  async getFileInfo({ path }) {
    let { default: prettier } = await this[MODULE]
    return prettier.getFileInfo(path, { resolveConfig: true })
  }
  async clearConfigCache(_) {
    let { default: prettier } = await this[MODULE]
    prettier.clearConfigCache()
    return null
  }
  async format({ path, contents, parser, cursor }) {
    let { default: prettier } = await this[MODULE]
    const config = await prettier.resolveConfig(path)
    // `filepath` is required for preserving <T> in .ts files instead of generating <T,>.
    // https://github.com/prettier/prettier/blob/724bb0c/src/language-js/print/type-parameters.js#L36-L48
    const options = { ...config, filepath: path, parser, cursorOffset: cursor }
    return prettier.formatWithCursor(contents, options)
  }
  ping(_) {
    return 'pong'
  }
}

async function main() {
  let server

  let prettierd = new Prettied(con => {
    con.end(JSON.stringify({ id, err: 'quit' }))
    server.close(() => console.log(JSON.stringify({ ok: 'closed' })))
  })

  let { [PORT]: port, [HANDLE]: handler } = prettierd
  server = create_server(port, handler.bind(prettierd))

  let terminate = () => {
    server.close()
    exit(0)
  }
  process.on('SIGINT', terminate)
  process.on('SIGTERM', terminate)

  // check python process and exit if there's none
  if (!is_running(get_ppid())) {
    terminate()
  }
}

main().catch(() => exit(1))
