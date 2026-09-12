/**
 * Web 构建的全屏快捷键占位：浏览器自带 F11 整页全屏，应用层不接管。
 * 通过 vite/tsconfig 的 @fullscreen-hotkey 别名按平台切换，
 * 保证 Web 构建永不解析任何 @tauri-apps/* 模块。
 */
export function initFullscreenHotkey(): () => void {
  return () => {}
}
