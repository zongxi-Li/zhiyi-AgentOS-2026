import { rm } from 'node:fs/promises'
import { build } from 'esbuild'

// 主进程与 Preload 统一 esbuild 打包：CJS 产物、external electron、不压缩，
// 保证审计可直接读产物。入口只有这两个，渲染层由 apps/frontend 独立构建。
const entries = [
  { entryPoints: ['src/main.ts'], outfile: 'dist/main.js' },
  { entryPoints: ['src/preload.ts'], outfile: 'dist/preload.js' }
]

await rm('dist', { recursive: true, force: true })

for (const entry of entries) {
  await build({
    ...entry,
    bundle: true,
    format: 'cjs',
    platform: 'node',
    target: 'node20',
    external: ['electron'],
    sourcemap: true,
    minify: false,
    logLevel: 'info'
  })
}
