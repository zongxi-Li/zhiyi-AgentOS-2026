import type { NotificationOptions, PlatformAdapter, SelectedFile } from '../types'

const selectedFileFromBrowser = (file: File): SelectedFile => ({
  name: file.name,
  path: null,
  file,
  size: file.size,
  type: file.type
})

const webAdapter: PlatformAdapter = {
  platform: 'web',

  openFile(options = {}): Promise<SelectedFile | null> {
    return new Promise((resolve) => {
      const input = document.createElement('input')
      input.type = 'file'
      if (options.accept) input.accept = options.accept
      input.onchange = () => resolve(input.files?.[0] ? selectedFileFromBrowser(input.files[0]) : null)
      input.click()
    })
  },

  async openDirectory(): Promise<string | null> {
    // Browsers intentionally do not expose a local directory path.
    return null
  },

  async notify(options: NotificationOptions): Promise<void> {
    if (!('Notification' in window)) return

    let permission = Notification.permission
    if (permission === 'default') permission = await Notification.requestPermission()
    if (permission === 'granted') new Notification(options.title, { body: options.body })
  },

  async openExternal(url: string): Promise<void> {
    const parsed = new URL(url, window.location.href)
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      throw new Error('Only HTTP(S) external URLs are supported')
    }
    window.open(parsed.toString(), '_blank', 'noopener,noreferrer')
  },

  isDesktop: () => false
}

export { webAdapter }
export default webAdapter
