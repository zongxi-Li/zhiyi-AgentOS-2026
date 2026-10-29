import type { WorkspaceFileListing } from '@/services/api/agentos/types/workspace'
/**
 * Electron 桥合同：Main Process 经安全 Preload（contextBridge）暴露的最小白名单面。
 * Renderer 只依赖本类型与 getElectronBridge()，永不 import 'electron'，
 * 保证 Web 构建与测试环境永不解析 Node/Electron 模块。
 */
export interface KinlinOpenFileResult {
  name: string
  path: string
}

export interface KinlinAppInfo {
  version: string
  platform: string
  packaged: boolean
}

export interface KinlinDesktopBridge {
  window: {
    minimize(): void
    toggleMaximize(): void
    close(): void
    isMaximized(): Promise<boolean>
    isFullscreen(): Promise<boolean>
    setFullscreen(fullscreen: boolean): Promise<void>
    /** 订阅真实窗口最大化状态（含 Win+↑、Snap、拖边等系统路径）；返回取消订阅函数。 */
    onMaximizeChanged(listener: (maximized: boolean) => void): () => void
  }
  /** 原生页面缩放由 preload 的 webFrame 直接落地，不走 Main IPC。 */
  zoom: {
    setZoomFactor(factor: number): void
  }
  dialog: {
    openFile(extensions?: string[]): Promise<KinlinOpenFileResult | null>
    openDirectory(): Promise<string | null>
  }
  workspace?: {
    choose(): Promise<{id: string; root: string} | null>
    current(): Promise<{id: string; root: string} | null>
    list(id: string, relative: string): Promise<WorkspaceFileListing>
    read(id: string, relative: string): Promise<{workspaceRoot: string; path: string; content: string; version: string}>
    save(id: string, relative: string, content: string, version: string): Promise<{path: string; version: string}>
  }
  notify(title: string, body?: string): void
  openExternal(url: string): Promise<void>
  appInfo(): Promise<KinlinAppInfo>
}

declare global {
  interface Window {
    kinlinDesktop?: KinlinDesktopBridge
  }
}

/** 桥缺失（非 Electron 宿主、Preload 未注入）时返回 null，调用方各自静默降级。 */
export function getElectronBridge(): KinlinDesktopBridge | null {
  const bridge = (window as Window & { kinlinDesktop?: KinlinDesktopBridge }).kinlinDesktop
  return bridge && typeof bridge === 'object' ? bridge : null
}
