import { getCurrentWebview } from '@tauri-apps/api/webview'
import { initUiZoomControl } from '@/composables/useUiZoom'

/**
 * 桌面缩放桥：档位落到 Tauri webview 原生缩放（等效浏览器整页缩放）。
 * 不用 CSS zoom 的原因：canvas 类可视化在 CSS zoom 下
 * 会出现位图模糊与命中坐标偏移，原生缩放由合成器处理，无此问题。
 * 需要 capability：core:webview:allow-set-webview-zoom。
 */
export function initUiZoom(): () => void {
  return initUiZoomControl({
    apply: (factor) => {
      try {
        getCurrentWebview().setZoom(factor).catch(() => {
          // Tauri 桥不可用（例如桌面构建直接跑在普通浏览器里）时静默放弃。
        })
      } catch {
        // 无 __TAURI_INTERNALS__ 时 getCurrentWebview 会同步抛错，同样静默放弃。
      }
    }
  })
}
