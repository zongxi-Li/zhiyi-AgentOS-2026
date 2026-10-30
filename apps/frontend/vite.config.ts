import { defineConfig } from 'vitest/config'
import { loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'
import Components from 'unplugin-vue-components/vite'
import AutoImport from 'unplugin-auto-import/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

const DEV_PROXY_TIMEOUT_MS = 240000

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const isElectron = mode === 'electron'
  // 桌面（Electron）与 Web 共用本配置：15100 端口与平台适配层只在桌面模式
  // 启用，前端一律直连本机 Java 后端（N03 口径，默认 18080）。
  const platformAdapter = resolve(
    __dirname,
    isElectron ? 'src/platform/electron/adapter.ts' : 'src/platform/web/adapter.ts'
  )
  // 桌面构建把窗口控件打进顶栏；Web 构建换成空占位，保证永不解析 Electron 桥模块。
  const windowControls = resolve(
    __dirname,
    isElectron ? 'src/components/desktop/ElectronWindowControls.vue' : 'src/platform/web/windowControlsStub.ts'
  )
  const uiZoomEntry = resolve(
    __dirname,
    isElectron ? 'src/platform/electron/uiZoom.ts' : 'src/platform/web/uiZoomStub.ts'
  )
  const BACKEND_PROXY_TARGET =
    env.DEV_BACKEND_PROXY_TARGET ||
    'http://127.0.0.1:18080'

  return {
    plugins: [
      vue(),
      Components({ resolvers: [ElementPlusResolver()] }),
      AutoImport({ resolvers: [ElementPlusResolver()] })
    ],
    css: {
      preprocessorOptions: {
        scss: {
          api: 'modern-compiler'
        }
      }
    },
    build: {
      // Electron 走独立产物目录，与 Web 的 dist 互不覆盖。
      outDir: isElectron ? 'dist-electron' : 'dist',
      // The remaining large files are the app shell and lazy visualization
      // libraries; keep a guard for meaningful growth after code-splitting.
      chunkSizeWarningLimit: 800
    },
    test: {
      environment: 'jsdom',
      globals: true,
      css: false,
      // 全量 625 条 jsdom 用例在并行 worker 下存在负载型计时抖动（断言调用次数/
      // 列表渲染条数的用例偶发漂移，单跑必现通过）；失败重跑一次吸收调度抖动，
      // 确定性失败仍然两次都挂，不会被掩盖。
      retry: 1,
      server: {
        deps: {
          inline: ['element-plus']
        }
      },
      include: ['src/**/*.spec.ts']
    },
    resolve: {
      alias: [
        { find: '@platform', replacement: platformAdapter },
        { find: '@window-controls', replacement: windowControls },
        // 桌面端 Ctrl+滚轮界面缩放的初始化入口；Web 构建换空占位，保证永不解析
        // Electron 桥模块。
        { find: '@ui-zoom', replacement: uiZoomEntry },
        { find: '@', replacement: resolve(__dirname, 'src') },
        {
          find: /^dayjs\/plugin\/(.+)\.js$/,
          replacement: `${resolve(__dirname, 'node_modules/dayjs/esm/plugin')}/$1/index.js`
        }
      ]
    },
    optimizeDeps: {
      include: [
        'vis-data',
        'vis-network',
      ],
    },
    server: {
      port: isElectron ? 15100 : 3000,
      // 桌面模式端口是 Electron dev 的硬约定（--dev-server=127.0.0.1:15100，
      // 并与后端 CORS 白名单对应）：端口被占就快速失败，
      // 禁止 Vite 静默漂移到 3001 导致 API 全部落入 CORS 陷阱。
      strictPort: isElectron,
      // 跨文件系统挂载可能不产生 inotify 事件，chokidar 常规监听会静默失效：
      // 源码已更新而 Vite 转换缓存永不失效，浏览器硬刷新仍拿到旧模块。
      // 需要轮询的环境显式设 CHOKIDAR_USEPOLLING=true；桌面开发使用原生监听，
      // 避免持续扫描文件。
      watch: { usePolling: env.CHOKIDAR_USEPOLLING === 'true' || !isElectron, interval: 1000 },
      proxy: {
        '/api': {
          target: BACKEND_PROXY_TARGET,
          changeOrigin: true,
          timeout: DEV_PROXY_TIMEOUT_MS,
          proxyTimeout: DEV_PROXY_TIMEOUT_MS,
          // Java 入口统一兼容 /api 别名；开发与打包版使用相同路由。
          configure: (proxy, _options) => {
            proxy.on('error', (err, _req, _res) => {
              console.log('proxy error', err)
            })
            proxy.on('proxyReq', (_proxyReq, req, _res) => {
              console.log('Sending Request to the Target:', req.method, req.url)
            })
            proxy.on('proxyRes', (proxyRes, req, _res) => {
              console.log('Received Response from the Target:', proxyRes.statusCode, req.url)
            })
          }
        },
        // 所有 /ai 路径（包括 SSE）只允许进入 Java 安全边界。
        '/ai/chat/text/stream': {
          target: BACKEND_PROXY_TARGET,
          changeOrigin: true,
          timeout: DEV_PROXY_TIMEOUT_MS,
          proxyTimeout: DEV_PROXY_TIMEOUT_MS,
          configure: (proxy, _options) => {
            proxy.on('error', (err, _req, _res) => {
              console.log('AI stream proxy error', err)
            })
            proxy.on('proxyReq', (_proxyReq, req, _res) => {
              console.log('Sending AI Stream Request to the Target:', req.method, req.url)
            })
            proxy.on('proxyRes', (proxyRes, req, _res) => {
              console.log('Received AI Stream Response from the Target:', proxyRes.statusCode, req.url)
            })
          }
        },
        '/ai': {
          target: BACKEND_PROXY_TARGET,
          changeOrigin: true,
          // Upgrade requests retain the Java authentication boundary too.
          // Availability still requires a corresponding Java WS endpoint.
          ws: true,
          timeout: DEV_PROXY_TIMEOUT_MS,
          proxyTimeout: DEV_PROXY_TIMEOUT_MS,
          rewrite: (path) => {
            // /ai 路径需要转发到Java后端，Java后端会代理到Python服务
            // 所以保持路径不变，Java后端会处理
            return path
          },
          configure: (proxy, _options) => {
            proxy.on('error', (err, _req, _res) => {
              console.log('AI proxy error', err)
            })
            proxy.on('proxyReq', (_proxyReq, req, _res) => {
              console.log('Sending AI Request to the Target:', req.method, req.url)
            })
            proxy.on('proxyRes', (proxyRes, req, _res) => {
              console.log('Received AI Response from the Target:', proxyRes.statusCode, req.url)
            })
          }
        }
      }
    }
  }
})
