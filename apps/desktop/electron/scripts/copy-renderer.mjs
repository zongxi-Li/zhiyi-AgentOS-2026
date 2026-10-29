import { copyFileSync, cpSync, existsSync, mkdirSync, rmSync } from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'

/**
 * 打包前置：把 apps/frontend 的 Electron 产物复制进本包（asar 内 renderer/），
 * 并沿用 Tauri 包的多尺寸品牌 ico 作为安装/应用图标。
 * electron-builder 的 files 只认包内路径，这里显式复制而不是引用外部目录。
 */
const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = path.resolve(project, '..', '..', '..')
const source = path.join(repoRoot, 'apps/frontend', 'dist-electron')
const rendererDir = path.join(project, 'renderer')
const buildDir = path.join(project, 'build')

if (!existsSync(path.join(source, 'index.html'))) {
  console.error('[copy-renderer] 缺少前端产物：先在 apps/frontend 执行 npm run build:electron')
  process.exit(1)
}

rmSync(rendererDir, { recursive: true, force: true })
cpSync(source, rendererDir, { recursive: true })

mkdirSync(buildDir, { recursive: true })
copyFileSync(
  path.join(repoRoot, 'apps/desktop/src-tauri/icons/icon.ico'),
  path.join(buildDir, 'icon.ico')
)

console.log(`[copy-renderer] renderer 已就绪（${rendererDir}），品牌图标已复制`)
