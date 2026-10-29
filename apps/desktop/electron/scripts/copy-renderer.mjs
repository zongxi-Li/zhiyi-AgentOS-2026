import { cpSync, existsSync, rmSync } from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * 打包前置：把 apps/frontend 的 Electron 产物复制进本包（asar 内 renderer/）。
 * electron-builder 的 files 只认包内路径，这里显式复制而不是引用外部目录；
 * 品牌 ico（icons/icon.ico）为入库文件，由 electron-builder 直接引用。
 */
const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = path.resolve(project, '..', '..', '..')
const source = path.join(repoRoot, 'apps/frontend', 'dist-electron')
const rendererDir = path.join(project, 'renderer')

if (!existsSync(path.join(source, 'index.html'))) {
  console.error('[copy-renderer] 缺少前端产物：先在 apps/frontend 执行 npm run build:electron')
  process.exit(1)
}

rmSync(rendererDir, { recursive: true, force: true })
cpSync(source, rendererDir, { recursive: true })

console.log(`[copy-renderer] renderer 已就绪（${rendererDir}）`)
