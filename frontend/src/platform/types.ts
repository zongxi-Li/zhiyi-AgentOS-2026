export type PlatformName = 'web' | 'desktop'

export type RuntimeStatus = 'checking' | 'online' | 'offline' | 'unknown'

export interface SelectedFile {
  name: string
  path: string | null
  file?: File
  size?: number
  type?: string
}

export interface NotificationOptions {
  title: string
  body?: string
}

export interface PlatformAdapter {
  readonly platform: PlatformName

  /**
   * 窗口拖拽区属性：desktop 返回 data-tauri-drag-region，
   * web 返回空对象——属性名字符串因此不进入 Web 产物。
   */
  readonly dragRegionProps: Record<string, string>

  openFile(options?: { accept?: string }): Promise<SelectedFile | null>

  openDirectory(): Promise<string | null>

  notify(options: NotificationOptions): Promise<void>

  openExternal(url: string): Promise<void>

  isDesktop(): boolean
}
