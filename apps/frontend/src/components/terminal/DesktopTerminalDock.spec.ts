import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'
import DesktopTerminalDock from './DesktopTerminalDock.vue'
import { terminalActiveId, terminalVisible } from '@/composables/useDesktopTerminal'
import { installCommandKeybindings } from '@/workbench/core/commands'
import type { TerminalSession } from '@/platform/electron/bridge'

const emulator = vi.hoisted(() => ({ input: null as ((data: string) => void) | null,
  write: vi.fn(), dispose: vi.fn(), focus: vi.fn() }))
vi.mock('@xterm/xterm', () => ({ Terminal: class {
  cols = 100; rows = 20
  loadAddon() {} open() {} clear() {} attachCustomKeyEventHandler() {}
  focus = emulator.focus; write = emulator.write; dispose = emulator.dispose
  onData(callback: (data: string) => void) { emulator.input = callback }
} }))
vi.mock('@xterm/addon-fit', () => ({ FitAddon: class { fit() {} } }))
const sample = (id: string): TerminalSession => ({ id, profileId: 'pwsh', profileName: 'PowerShell 7',
  cwd: 'C:/chosen-project', pid: 42, state: 'running', exitCode: null, cols: 100, rows: 20, createdAt: 'now' })

describe('DesktopTerminalDock', () => {
  let wrapper: ReturnType<typeof mount> | undefined
  let disposeKeybindings: (() => void) | null = null
  let stored: TerminalSession[]
  let api: { profiles: ReturnType<typeof vi.fn>; list: ReturnType<typeof vi.fn>; create: ReturnType<typeof vi.fn>;
    read: ReturnType<typeof vi.fn>; write: ReturnType<typeof vi.fn>; resize: ReturnType<typeof vi.fn>; close: ReturnType<typeof vi.fn> }
  beforeEach(() => {
    vi.clearAllMocks(); localStorage.clear(); terminalVisible.value = false; terminalActiveId.value = null; stored = []
    api = {
      profiles: vi.fn(async () => ({ profiles: [{ id: 'pwsh', name: 'PowerShell 7' }, { id: 'cmd', name: 'Command Prompt' }] })),
      list: vi.fn(async () => ({ sessions: [...stored] })),
      create: vi.fn(async () => { const session = sample(`session-${stored.length + 1}`); stored.push(session); return session }),
      read: vi.fn(async (id: string) => ({ session: stored.find(session => session.id === id)!, cursor: 1,
        truncated: false, chunks: [{ sequence: 1, data: 'PS C:\\chosen-project> ' }] })),
      write: vi.fn(async () => ({})), resize: vi.fn(async () => ({})),
      close: vi.fn(async (id: string) => { stored = stored.filter(session => session.id !== id); return {} })
    }
    Object.assign(window, { kinlinDesktop: { terminal: api } })
    localStorage.setItem('token', 'test-token')
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ workspaceRoot: 'C:/chosen-project' }) })))
    // Ctrl+` 由命令表派发（见 onMounted 注册）。
    disposeKeybindings = installCommandKeybindings()
  })
  afterEach(() => {
    wrapper?.unmount(); wrapper = undefined
    disposeKeybindings?.(); disposeKeybindings = null
    vi.unstubAllGlobals(); delete window.kinlinDesktop
  })

  async function open() {
    wrapper = mount(DesktopTerminalDock)
    terminalVisible.value = true
    await flushPromises(); await nextTick(); await flushPromises()
  }
  it('starts a real transport session in the selected workspace and forwards keyboard input', async () => {
    await open()
    expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ profileId: 'pwsh', cwd: 'C:/chosen-project' }))
    expect(emulator.write).toHaveBeenCalledWith('PS C:\\chosen-project> ')
    emulator.input?.('node\r'); emulator.input?.('\x03')
    await flushPromises()
    expect(api.write.mock.calls).toEqual([['session-1', 'node\r'], ['session-1', '\x03']])
  })
  it('collapse and reopen keep the Shell session instead of creating a new one', async () => {
    await open()
    await wrapper!.get('[aria-label="关闭终端面板"]').trigger('click')
    expect(terminalVisible.value).toBe(false)
    expect(api.close).not.toHaveBeenCalled()
    terminalVisible.value = true
    await flushPromises()
    expect(api.create).toHaveBeenCalledTimes(1)
    expect(terminalActiveId.value).toBe('session-1')
  })
  it('supports multiple tabs and closes only the requested session', async () => {
    await open()
    await wrapper!.get('[aria-label="新建终端"]').trigger('click')
    await flushPromises()
    expect(wrapper!.findAll('[role="tab"]')).toHaveLength(2)
    await wrapper!.get('[aria-label="关闭终端 2"]').trigger('click')
    await flushPromises()
    expect(api.close).toHaveBeenCalledWith('session-2')
    expect(terminalActiveId.value).toBe('session-1')
  })
  it('Ctrl+backquote toggles the global panel and transport errors are visible', async () => {
    api.profiles.mockRejectedValueOnce(new Error('Host unavailable'))
    wrapper = mount(DesktopTerminalDock)
    window.dispatchEvent(new KeyboardEvent('keydown', { ctrlKey: true, code: 'Backquote', bubbles: true }))
    await flushPromises()
    expect(terminalVisible.value).toBe(true)
    expect(wrapper.get('[role="alert"]').text()).toContain('Host unavailable')
    expect(api.create).not.toHaveBeenCalled()
  })
})
