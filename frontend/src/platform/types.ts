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

  openFile(options?: { accept?: string }): Promise<SelectedFile | null>

  openDirectory(): Promise<string | null>

  notify(options: NotificationOptions): Promise<void>

  openExternal(url: string): Promise<void>

  isDesktop(): boolean
}
