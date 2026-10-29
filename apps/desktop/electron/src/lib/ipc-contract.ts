/**
 * IPC 通道名单一权威：Main Process 注册与 Preload 调用共用，
 * 防止通道名漂移导致白名单失配。Renderer 侧类型合同见
 * apps/frontend/src/platform/electron/bridge.ts（手工保持同构）。
 */
export const IPC = {
  windowMinimize: 'kinlin:window/minimize',
  windowToggleMaximize: 'kinlin:window/toggle-maximize',
  windowClose: 'kinlin:window/close',
  windowIsMaximized: 'kinlin:window/is-maximized',
  windowIsFullscreen: 'kinlin:window/is-fullscreen',
  windowSetFullscreen: 'kinlin:window/set-fullscreen',
  /** Main → Renderer 事件：真实窗口最大化状态变化（含 Win+↑、Snap 等系统路径）。 */
  windowMaximizeChanged: 'kinlin:window/maximize-changed',
  dialogOpenFile: 'kinlin:dialog/open-file',
  dialogOpenDirectory: 'kinlin:dialog/open-directory',
  notify: 'kinlin:notify',
  openExternal: 'kinlin:open-external',
  appInfo: 'kinlin:app/info'
} as const

export type IpcChannel = (typeof IPC)[keyof typeof IPC]
