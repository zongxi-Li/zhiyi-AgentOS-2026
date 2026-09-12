/**
 * F11 全局全屏切换（桌面端）：
 * - 本模块只管按键接管，真正落地全屏由平台桥注入
 *   （桌面 = window.setFullscreen；Web 构建走空占位不初始化，浏览器自带 F11）。
 */

export interface FullscreenHotkeyOptions {
  /** 切换真实窗口全屏状态（桌面桥 = setFullscreen(!isFullscreen())）。 */
  toggle: () => void
}

type FullscreenRuntime = Required<FullscreenHotkeyOptions>

let runtime: FullscreenRuntime | null = null
let disposer: (() => void) | null = null

const handleKeydown = (event: KeyboardEvent): void => {
  if (!runtime) return
  if (event.key !== 'F11' && event.code !== 'F11') return
  // 按住 F11 会持续产生 auto-repeat keydown，不拦会把全屏来回打滑。
  event.preventDefault()
  if (event.repeat) return
  event.stopPropagation()
  runtime.toggle()
}

/** 初始化 F11 全屏接管；幂等，重复调用返回同一个清理函数。 */
export function initFullscreenHotkeyControl(options: FullscreenHotkeyOptions): () => void {
  if (disposer) return disposer
  runtime = { ...options }

  window.addEventListener('keydown', handleKeydown, { capture: true })

  disposer = () => {
    window.removeEventListener('keydown', handleKeydown, { capture: true })
    runtime = null
    disposer = null
  }
  return disposer
}
