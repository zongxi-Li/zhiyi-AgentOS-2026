import { getCurrentWindow } from '@tauri-apps/api/window'
import { initFullscreenHotkeyControl } from '@/composables/useFullscreenHotkey'

/**
 * 桌面全屏桥：F11 切换 Tauri 原生窗口全屏。
 * 需要 capability：core:window:allow-set-fullscreen、core:window:allow-is-fullscreen。
 */
export function initFullscreenHotkey(): () => void {
  return initFullscreenHotkeyControl({
    toggle: () => {
      try {
        const appWindow = getCurrentWindow()
        void appWindow.isFullscreen().then((fullscreen) => {
          return appWindow.setFullscreen(!fullscreen)
        }).catch(() => {
          // 窗口句柄暂不可用（正在关闭等）时静默放弃，不打断用户。
        })
      } catch {
        // 无 __TAURI_INTERNALS__ 时 getCurrentWindow 会同步抛错
        // （例如桌面构建直接跑在普通浏览器里），同样静默放弃。
      }
    }
  })
}
