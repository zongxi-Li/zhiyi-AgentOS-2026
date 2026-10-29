import type { NotificationOptions, PlatformAdapter, SelectedFile } from '../types'
import { getElectronBridge } from './bridge'
import './drag-region.css'

// Electron 宿主适配：沿用 PlatformAdapter 合同，窗口/对话框/通知/外链全部经
// Preload 暴露的白名单 IPC 落到 Main Process；桥未注入时逐项静默降级。

const electronAdapter: PlatformAdapter = {
  platform: 'desktop',

  // CSS 侧由 drag-region.css 把该属性映射为 -webkit-app-region: drag。
  dragRegionProps: { 'data-electron-drag-region': '' },

  async openFile(options = {}): Promise<SelectedFile | null> {
    const bridge = getElectronBridge()
    if (!bridge) return null
    const extensions = options.accept
      ? options.accept.split(',').map((item) => item.trim().replace(/^\./, '')).filter(Boolean)
      : undefined
    const selected = await bridge.dialog.openFile(extensions)
    if (!selected) return null
    return { name: selected.name, path: selected.path }
  },

  async openDirectory(): Promise<string | null> {
    const bridge = getElectronBridge()
    if (!bridge) return null
    return bridge.dialog.openDirectory()
  },

  async notify(options: NotificationOptions): Promise<void> {
    const bridge = getElectronBridge()
    if (!bridge) return
    bridge.notify(options.title, options.body)
  },

  async openExternal(url: string): Promise<void> {
    const bridge = getElectronBridge()
    if (!bridge) throw new Error('Electron bridge unavailable')
    const parsed = new URL(url)
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      throw new Error('Only HTTP(S) external URLs are supported')
    }
    await bridge.openExternal(parsed.toString())
  },

  isDesktop: () => true
}

export { electronAdapter }
export default electronAdapter
