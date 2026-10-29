import { contextBridge, ipcRenderer, webFrame } from 'electron'
import { IPC } from './lib/ipc-contract'
import { clampNumber } from './lib/validation'

/**
 * 安全 Preload：沙箱模式下唯一可用面是 contextBridge/ipcRenderer/webFrame。
 * 这里只做三件事：
 * 1. 以白名单通道（lib/ipc-contract.ts）invoke Main，不在 Renderer 暴露 ipcRenderer 本体；
 * 2. 把缩放落到 webFrame（无 IPC 往返，Main 不参与缩放）；
 * 3. 对事件回执做类型收窄后才交给页面。
 * 通道名单与参数校验的权威在 Main；Renderer 侧类型合同见
 * apps/frontend/src/platform/electron/bridge.ts（手工保持同构）。
 */

const invoke = (channel: string, ...args: unknown[]): Promise<unknown> => ipcRenderer.invoke(channel, ...args)

const bridge = {
  window: {
    minimize: (): void => {
      void invoke(IPC.windowMinimize).catch(() => undefined)
    },
    toggleMaximize: (): void => {
      void invoke(IPC.windowToggleMaximize).catch(() => undefined)
    },
    close: (): void => {
      void invoke(IPC.windowClose).catch(() => undefined)
    },
    isMaximized: (): Promise<boolean> => invoke(IPC.windowIsMaximized).then(Boolean),
    isFullscreen: (): Promise<boolean> => invoke(IPC.windowIsFullscreen).then(Boolean),
    setFullscreen: (fullscreen: boolean): Promise<void> =>
      invoke(IPC.windowSetFullscreen, Boolean(fullscreen)).then(() => undefined),
    onMaximizeChanged: (listener: (maximized: boolean) => void): (() => void) => {
      const wrapped = (_event: unknown, value: unknown): void => {
        if (typeof value === 'boolean') listener(value)
      }
      ipcRenderer.on(IPC.windowMaximizeChanged, wrapped)
      return () => {
        ipcRenderer.removeListener(IPC.windowMaximizeChanged, wrapped)
      }
    }
  },
  zoom: {
    setZoomFactor: (factor: number): void => {
      const clamped = clampNumber(factor, 0.25, 5)
      if (clamped === null) return
      try {
        webFrame.setZoomFactor(clamped)
      } catch {
        // webFrame 暂不可用时静默放弃，档位状态仍保留。
      }
    }
  },
  dialog: {
    openFile: (extensions?: string[]): Promise<{ name: string; path: string } | null> =>
      invoke(IPC.dialogOpenFile, extensions === undefined ? {} : { extensions }) as Promise<{ name: string; path: string } | null>,
    openDirectory: (): Promise<string | null> => invoke(IPC.dialogOpenDirectory) as Promise<string | null>
  },
  notify: (title: string, body?: string): void => {
    void invoke(IPC.notify, { title, body }).catch(() => undefined)
  },
  openExternal: (url: string): Promise<void> =>
    invoke(IPC.openExternal, url).then(() => undefined) as Promise<void>,
  appInfo: (): Promise<{ version: string; platform: string; packaged: boolean }> =>
    invoke(IPC.appInfo) as Promise<{ version: string; platform: string; packaged: boolean }>
}

contextBridge.exposeInMainWorld('kinlinDesktop', bridge)
