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
// py: spawn js, read one line from stdout (in a thread)
// js: load prettier, start the server, log {"ok":9870}
//
// py: ok I know you are alive, tell me if "a.mjs" is formattable?
// js: {"ok":"babel"}   // returns the parser, can be null if not formattable.
//     {"err":"reason"} // something went wrong.
//     ...              // timeout!
// if ok, the py part marks the file as formattable or not.
// if err, the py part prints the error message and do nothing.
// if timeout, assume the node process is die. Try re-spawn.
//
// py: ok please format this file "a.mjs", and the parser is "babel".
// js: {"ok":"a = 1;\n"} // returns the formatted result.
//     {"err":"reason"}  // something went wrong.
//     ...               // timeout!
//
import { spawnSync } from 'child_process'
import { resolve, dirname } from 'path'
import { pathToFileURL } from 'url'
import { createServer } from 'net'

const exit = process.exit

process.stdin.on('data', e => {
  if (e.toString().startsWith('q')) exit(2)
})

function import_prettier() {
  let npm = process.platform === 'win32' ? 'npm.cmd' : 'npm'
  let global_path = spawnSync(npm, ['root', '-g']).stdout.toString().trimEnd()
  return import(pathToFileURL(resolve(global_path, 'prettier/index.js')))
}

function create_server(port, handler) {
  let server = createServer({ allowHalfOpen: true }, handler)
  server.on('error', err => console.error(err.message))
  server.listen(port, () => console.log(JSON.stringify({ ok: port })))
  return server
}

function get_port() {
  return Number(process.env.PORT) || Number.parseInt(process.argv[2]) || 9870
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
    const options = { ...config, parser, cursorOffset: cursor }
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
  process.on('SIGKILL', terminate)
}

main().catch(() => exit(1))
