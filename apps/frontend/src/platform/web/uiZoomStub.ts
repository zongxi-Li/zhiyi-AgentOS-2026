/**
 * Web 构建的界面缩放占位：浏览器自带 Ctrl+滚轮整页缩放，应用层不接管。
 * 通过 vite/tsconfig 的 @ui-zoom 别名按平台切换，
 * 保证 Web 构建永不解析任何 @tauri-apps/* 模块。
 */
export function initUiZoom(): () => void {
  return () => {}
}
