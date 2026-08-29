import type { NotificationOptions, PlatformAdapter, SelectedFile } from '../types'
import { open } from '@tauri-apps/plugin-dialog'
import { isPermissionGranted, requestPermission, sendNotification } from '@tauri-apps/plugin-notification'
import { openUrl } from '@tauri-apps/plugin-opener'

const fileNameFromPath = (path: string): string => path.split(/[\\/]/).pop() || path

const desktopAdapter: PlatformAdapter = {
  platform: 'desktop',

  async openFile(options = {}): Promise<SelectedFile | null> {
    const selected = await open({
      multiple: false,
      directory: false,
      filters: options.accept
        ? [{ name: 'Supported files', extensions: options.accept.split(',').map((item) => item.trim().replace(/^\./, '')).filter(Boolean) }]
        : undefined
    })
    if (typeof selected !== 'string') return null
    return { name: fileNameFromPath(selected), path: selected }
  },

  async openDirectory(): Promise<string | null> {
    const selected = await open({ multiple: false, directory: true })
    return typeof selected === 'string' ? selected : null
  },

  async notify(options: NotificationOptions): Promise<void> {
    let permissionGranted = await isPermissionGranted()
    if (!permissionGranted) permissionGranted = (await requestPermission()) === 'granted'
    if (permissionGranted) sendNotification({ title: options.title, body: options.body })
  },

  async openExternal(url: string): Promise<void> {
    const parsed = new URL(url)
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      throw new Error('Only HTTP(S) external URLs are supported')
    }
    await openUrl(parsed.toString())
  },

  isDesktop: () => true
}

export { desktopAdapter }
export default desktopAdapter
