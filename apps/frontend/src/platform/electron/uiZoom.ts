import { initUiZoomControl } from '@/composables/useUiZoom'
import { getElectronBridge } from './bridge'

/**
 * Electron 桌面缩放桥：档位落到 preload webFrame.setZoomFactor（等效浏览器整页缩放）。
 * 与 Tauri 版同理不用 CSS zoom：canvas 类可视化（ACG 图）在 CSS zoom 下
 * 会出现位图模糊与命中坐标偏移，原生缩放由合成器处理，无此问题。
 * Main Process 不参与缩放（无 IPC 往返），桥未注入时静默放弃。
 */
export function initUiZoom(): () => void {
  return initUiZoomControl({
    apply: (factor) => {
      try {
        getElectronBridge()?.zoom.setZoomFactor(factor)
      } catch {
        // 桥不可用（例如 Electron 构建误跑在普通浏览器里）时静默放弃。
      }
    }
  })
}
