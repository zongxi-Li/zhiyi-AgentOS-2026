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
  const isDesktop = mode === 'desktop'
  const platformAdapter = resolve(
    __dirname,
    isDesktop ? 'src/platform/desktop/adapter.ts' : 'src/platform/web/adapter.ts'
  )
  // 桌面构建把窗口控件打进顶栏；Web 构建换成空占位，保证永不解析 @tauri-apps/api/window。
  const windowControls = resolve(
    __dirname,
    isDesktop ? 'src/components/desktop/DesktopWindowControls.vue' : 'src/platform/web/windowControlsStub.ts'
  )
  const desktopNodeModules = resolve(__dirname, '../desktop/node_modules')
  const BACKEND_PROXY_TARGET =
    env.DEV_BACKEND_PROXY_TARGET ||
    'http://127.0.0.1:9050'
  const proxyThroughHostGateway = isDesktop && BACKEND_PROXY_TARGET === 'http://127.0.0.1:9050'

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
      // The remaining large files are the app shell and lazy visualization
      // libraries; keep a guard for meaningful growth after code-splitting.
      chunkSizeWarningLimit: 800
    },
    test: {
      environment: 'jsdom',
      globals: true,
      css: false,
      server: {
        deps: {
          inline: ['element-plus']
        }
      },
      include: ['src/**/*.spec.ts'],
      alias: {
        '@': resolve(__dirname, 'src'),
        // 仅供 jsdom 测试解析 DesktopWindowControls 的 import（运行时被 vi.mock 替换）；
        // 生产构建不经过这里，Web/desktop 隔离仍由 resolve.alias 决定。
        '@tauri-apps/api': resolve(desktopNodeModules, '@tauri-apps/api')
      }
    },
    resolve: {
      alias: [
        { find: '@platform', replacement: platformAdapter },
        { find: '@window-controls', replacement: windowControls },
        // 桌面端 Ctrl+滚轮界面缩放的初始化入口；Web 构建换空占位，保证永不解析 @tauri-apps/api/webview。
        {
          find: '@ui-zoom',
          replacement: resolve(
            __dirname,
            isDesktop ? 'src/platform/desktop/uiZoom.ts' : 'src/platform/web/uiZoomStub.ts'
          )
        },
        ...(isDesktop ? [
          { find: '@tauri-apps/api', replacement: resolve(desktopNodeModules, '@tauri-apps/api') },
          { find: '@tauri-apps/plugin-dialog', replacement: resolve(desktopNodeModules, '@tauri-apps/plugin-dialog') },
          { find: '@tauri-apps/plugin-notification', replacement: resolve(desktopNodeModules, '@tauri-apps/plugin-notification') },
          { find: '@tauri-apps/plugin-opener', replacement: resolve(desktopNodeModules, '@tauri-apps/plugin-opener') }
        ] : []),
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
      port: isDesktop ? 15100 : 3000,
      // 桌面模式端口是 tauri dev 的硬约定（tauri.conf.json devUrl=127.0.0.1:15100，
      // 后端 CORS 白名单也只围绕该源设计）：端口被占就快速失败，
      // 禁止 Vite 静默漂移到 3001 导致 API 全部落入 CORS 陷阱。
      strictPort: isDesktop,
      // Windows 宿主目录 bind mount 进容器后不产生 inotify 事件，chokidar 常规监听
      // 会静默失效：源码已更新而 Vite 转换缓存永不失效，浏览器硬刷新仍拿到旧模块。
      // 容器开发保留轮询；宿主桌面开发使用原生监听，避免持续扫描文件。
      watch: { usePolling: env.CHOKIDAR_USEPOLLING === 'true' || !isDesktop, interval: 1000 },
      proxy: {
        '/api': {
          target: BACKEND_PROXY_TARGET,
          changeOrigin: true,
          timeout: DEV_PROXY_TIMEOUT_MS,
          proxyTimeout: DEV_PROXY_TIMEOUT_MS,
          // 智能处理：部分控制器有/api前缀，部分没有
          // 对于有/api前缀的控制器（如digital-human），保留前缀
          // 对于没有/api前缀的控制器（如auth、chat），去掉前缀
          rewrite: (path) => {
            // The desktop hot-reload server forwards to the host Gateway,
            // whose own frontend proxy expects the /api prefix. Docker's
            // frontend server forwards directly to Backend and still needs
            // the legacy prefix removal below.
            if (proxyThroughHostGateway) return path

            // 这些路径已经有/api前缀，保留
            const keepApiPrefix = [
              '/api/digital-human',
              '/api/kylin-os',
              '/api/emotion',
              '/api/knowledge-graph',
              '/api/role-fusion',
              '/api/alerts',
              '/api/feedback',
              '/api/federated-models',
              '/api/agentos/v2'
            ]

            // 检查是否需要保留/api前缀
            if (keepApiPrefix.some(prefix => path.startsWith(prefix))) {
              return path // 保留/api前缀
            }

            // 其他路径去掉/api前缀
            return path.replace(/^\/api/, '')
          },
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
