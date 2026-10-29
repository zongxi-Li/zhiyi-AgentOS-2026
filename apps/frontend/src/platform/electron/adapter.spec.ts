import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import electronAdapter from './adapter'
import type { KinlinDesktopBridge } from './bridge'

// 与组件测试同款完整桥 mock：经 window.kinlinDesktop 注入，缺面即断言失败。
const createBridge = () =>
  ({
    window: {
      minimize: vi.fn(),
      toggleMaximize: vi.fn(),
      close: vi.fn(),
      isMaximized: vi.fn(async () => false),
      isFullscreen: vi.fn(async () => false),
      setFullscreen: vi.fn(async () => {}),
      onMaximizeChanged: vi.fn(() => () => {})
    },
    zoom: {
      setZoomFactor: vi.fn()
    },
    dialog: {
      openFile: vi.fn(async () => null),
      openDirectory: vi.fn(async () => null)
    },
    notify: vi.fn(),
    openExternal: vi.fn(async () => {}),
    appInfo: vi.fn(async () => ({ version: '0.0.0-test', platform: 'win32', packaged: false }))
  }) as unknown as KinlinDesktopBridge

let bridge: KinlinDesktopBridge

beforeEach(() => {
  bridge = createBridge()
  window.kinlinDesktop = bridge
})

afterEach(() => {
  delete (window as any).kinlinDesktop
})

describe('electronAdapter', () => {
  it('exposes the desktop identity and the drag region props', () => {
    expect(electronAdapter.platform).toBe('desktop')
    expect(electronAdapter.isDesktop()).toBe(true)
    expect(electronAdapter.dragRegionProps).toEqual({ 'data-electron-drag-region': '' })
  })

  it('degrades silently per feature when the bridge is missing', async () => {
    delete (window as any).kinlinDesktop

    await expect(electronAdapter.openFile()).resolves.toBeNull()
    await expect(electronAdapter.openDirectory()).resolves.toBeNull()
    await expect(electronAdapter.notify({ title: 'x' })).resolves.toBeUndefined()
    await expect(electronAdapter.openExternal('https://a.com')).rejects.toThrow('Electron bridge unavailable')
  })

  it('normalizes accept filters into extensions and maps the bridge result', async () => {
    vi.mocked(bridge.dialog.openFile).mockResolvedValueOnce({ name: 'a.csv', path: 'C:/tmp/a.csv' })
    await expect(electronAdapter.openFile({ accept: '.csv, json' })).resolves.toEqual({
      name: 'a.csv',
      path: 'C:/tmp/a.csv'
    })
    expect(bridge.dialog.openFile).toHaveBeenCalledWith(['csv', 'json'])

    vi.mocked(bridge.dialog.openFile).mockResolvedValueOnce(null)
    await expect(electronAdapter.openFile({ accept: '.csv, json' })).resolves.toBeNull()
  })

  it('calls the bridge without extensions when accept is omitted', async () => {
    await expect(electronAdapter.openFile()).resolves.toBeNull()

    expect(bridge.dialog.openFile).toHaveBeenCalledWith(undefined)
  })

  it('passes the directory selection straight through', async () => {
    vi.mocked(bridge.dialog.openDirectory).mockResolvedValueOnce('C:/tmp')
    await expect(electronAdapter.openDirectory()).resolves.toBe('C:/tmp')

    vi.mocked(bridge.dialog.openDirectory).mockResolvedValueOnce(null)
    await expect(electronAdapter.openDirectory()).resolves.toBeNull()
  })

  it('forwards notify with title and body', async () => {
    await expect(electronAdapter.notify({ title: 't', body: 'b' })).resolves.toBeUndefined()

    expect(bridge.notify).toHaveBeenCalledWith('t', 'b')
  })

  it('only opens HTTP(S) external URLs', async () => {
    await expect(electronAdapter.openExternal('file:///C:/x')).rejects.toThrow()
    await expect(electronAdapter.openExternal('javascript:alert(1)')).rejects.toThrow()
    await expect(electronAdapter.openExternal('https://example.com/a')).resolves.toBeUndefined()

    expect(bridge.openExternal).toHaveBeenCalledTimes(1)
    expect(bridge.openExternal).toHaveBeenCalledWith('https://example.com/a')
  })
})
