import { spawnSync } from 'child_process'
import { resolve } from 'path'
import { pathToFileURL } from 'url'
import { createServer } from 'net'

const WIN = process.platform === 'win32'
const NPM = WIN ? 'npm.cmd' : 'npm'
const GLOBAL_PATH = spawnSync(NPM, ['root', '-g']).stdout.toString().trimEnd()
const PRETTIER = resolve(GLOBAL_PATH, 'prettier/index.js')
const PORT = +process.env.PORT || +process.argv[2] || 9870

let prettier

let symWork = Symbol('work')
let worker = new (class {
  [symWork](method, params) {
    if (method in this) {
      console.error('worker.' + method, params)
      return this[method](params)
    } else {
      throw new Error("NoSuchMethodError: don't know how to " + method)
    }
  }
  getSupportInfo(_) {
    return prettier.getSupportInfo()
  }
  getFileInfo({ path }) {
    return prettier.getFileInfo(path) // { ignored: false, inferredParser: 'babel' | null }
  }
  clearConfigCache() {
    prettier.clearConfigCache()
    return null
  }
  async format({ path, contents, parser = 'babel', cursorOffset }) {
    const config = await prettier.resolveConfig(path)
    const options = { ...config, parser, cursorOffset }
    return prettier.formatWithCursor(contents, options) // { formatted: '1;\n', cursorOffset: 1 }
  }
})()

let server
const onterm = () => {
  console.log('byebye')
  server && server.close()
  process.exit(0)
}

process.on('SIGINT', onterm)
process.on('SIGTERM', onterm)
process.on('SIGKILL', onterm)

async function main() {
  ;({ default: prettier } = await import(pathToFileURL(PRETTIER)))
  server = createServer({ allowHalfOpen: true }, handleConnection)
  server.on('error', (err) => console.error(err.message))
  server.listen(PORT, () => console.log(`serving http://localhost:${PORT}`))
}

async function handleConnection(con) {
  const chunks = []
  con.on('data', (chunk) => chunks.push(chunk))
  con.on('end', async () => {
    const raw = Buffer.concat(chunks).toString()
    const { id, method, params } = JSON.parse(raw)
    if (method === 'close') {
      con.write(JSON.stringify({ id, result: 'closing' }))
      con.destroy()
      onterm()
      return
    }
    try {
      const result = await worker[symWork](method, params)
      con.write(JSON.stringify({ id, result }))
    } catch (err) {
      con.write(JSON.stringify({ id, error: err.message }))
    }
    con.destroy()
  })
}

main().catch(() => process.exit(1))
