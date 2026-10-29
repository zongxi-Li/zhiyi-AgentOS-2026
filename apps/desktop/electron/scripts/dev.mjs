import { spawn, spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * Electron 桌面开发编排：
 * 1. 编译 main/preload；2. 确保 Vite dev server（mode=electron，15100）在位；
 * 3. 拉起 Electron 指向该 dev server；4. 退出时清理自己拉起的 Vite。
 * 外部已起 dev server（如 N02/N03 在 15200 起了自己的 Vite）时直接复用，
 * 用 ELECTRON_DEV_SERVER_URL 或 --dev-server= 指定即可，不再二次拉起。
 */
const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = path.resolve(project, '..', '..', '..')
const frontendDir = path.join(repoRoot, 'apps/frontend')
const electronCli = path.join(project, 'node_modules', 'electron', 'cli.js')

const fail = (message) => {
  console.error(`[dev] ${message}`)
  process.exit(1)
}

if (!existsSync(electronCli)) {
  fail('缺少 Electron 运行时：先在 apps/desktop/electron 执行 npm install（网络受限时先设 ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/）')
}

const compile = spawnSync(process.execPath, ['build.mjs'], { cwd: project, stdio: 'inherit' })
if (compile.status !== 0) fail('main/preload 编译失败')

const args = process.argv.slice(2)
const devServerArg = args.find((value) => value.startsWith('--dev-server='))
const devServerUrl = process.env.ELECTRON_DEV_SERVER_URL
  || devServerArg?.slice('--dev-server='.length)
  || 'http://127.0.0.1:15100'

let devPort = 15100
try {
  devPort = new URL(devServerUrl).port || 15100
} catch {
  fail(`--dev-server 不是合法 URL：${devServerUrl}`)
}

const isUp = async (url) => {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(900) })
    return response.status < 500
  } catch {
    return false
  }
}

const forwardArgs = args.filter((value) => !value.startsWith('--dev-server='))

let viteChild = null
let electronChild = null
let shuttingDown = false

const killTree = (child) => {
  if (!child || child.killed || !child.pid) return
  // vite 会派生 esbuild 子进程；Electron 经 cli.js 派生真实二进制，
  // 统一按进程树清理，避免孤儿进程占住端口。
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
  } else {
    child.kill('SIGTERM')
  }
}

const shutdown = (code) => {
  if (shuttingDown) return
  shuttingDown = true
  killTree(electronChild)
  killTree(viteChild)
  process.exit(code ?? 0)
}

process.on('SIGINT', () => shutdown(130))
process.on('SIGTERM', () => shutdown(143))
process.on('SIGHUP', () => shutdown(129))

const ready = await isUp(devServerUrl)
if (!ready) {
  if (process.env.ELECTRON_EXTERNAL_DEV_SERVER === '1') {
    fail(`外部开发服务器未就绪：${devServerUrl}`)
  }
  const viteBin = path.join(frontendDir, 'node_modules', 'vite', 'bin', 'vite.js')
  if (!existsSync(viteBin)) fail('apps/frontend 尚未安装依赖（node_modules/vite 不存在）')
  console.log(`[dev] 启动 Vite dev server：${devServerUrl}`)
  const viteEnv = { ...process.env, VITE_API_BASE_URL: '' }
  viteChild = spawn(
    process.execPath,
    [viteBin, frontendDir, '--mode', 'electron', '--host', '127.0.0.1', '--port', String(devPort), '--strictPort'],
    { cwd: frontendDir, env: viteEnv, stdio: 'inherit' }
  )
  viteChild.on('exit', (code) => {
    if (!shuttingDown) fail(`Vite dev server 提前退出（code=${code}）`)
  })
}

const deadline = Date.now() + 120_000
while (!(await isUp(devServerUrl))) {
  if (Date.now() > deadline) fail(`等待 dev server 超时：${devServerUrl}`)
  await new Promise((resolve) => setTimeout(resolve, 400))
}

console.log(`[dev] 启动 Electron：${devServerUrl}`)
// 外部 shell/调试器可能注入 ELECTRON_RUN_AS_NODE=1；它会让 electron.exe 以普通
// Node 运行 main.js（electron.protocol 为 undefined）。开发入口必须剥离它。
const electronEnv = { ...process.env }
delete electronEnv.ELECTRON_RUN_AS_NODE
electronChild = spawn(process.execPath, [electronCli, project, `--dev-server=${devServerUrl}`, ...forwardArgs], {
  cwd: project,
  env: electronEnv,
  stdio: 'inherit'
})
electronChild.on('exit', (code) => shutdown(code ?? 0))
