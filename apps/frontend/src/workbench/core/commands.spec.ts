import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  CommandRegistry,
  installCommandKeybindings,
  matchesKeybinding,
  parseKeybinding,
  type CommandDescriptor
} from './commands'

const keydown = (init: KeyboardEventInit & { key?: string }): KeyboardEvent => (
  new KeyboardEvent('keydown', { cancelable: true, bubbles: true, ...init })
)

const register = (registry: CommandRegistry, command: Partial<CommandDescriptor> & { id: string }): CommandDescriptor => {
  const full: CommandDescriptor = { title: command.id, run: () => {}, ...command }
  registry.register(full)
  return full
}

let disposers: Array<() => void> = []
afterEach(() => {
  disposers.forEach(dispose => dispose())
  disposers = []
  document.body.innerHTML = ''
})

describe('parseKeybinding', () => {
  it('解析修饰键与主键，顺序无关', () => {
    const direct = parseKeybinding('mod+shift+k')
    const reordered = parseKeybinding('shift+mod+k')
    expect(direct).toMatchObject({ mod: true, shift: true, key: 'k' })
    expect(reordered).toMatchObject({ mod: true, shift: true, key: 'k' })
  })

  it('可打印符号隐含 Shift，字母与具名键需要显式比较', () => {
    expect(parseKeybinding('?')?.ignoreShift).toBe(true)
    expect(parseKeybinding('`')?.ignoreShift).toBe(true)
    expect(parseKeybinding('k')?.ignoreShift).toBe(false)
    expect(parseKeybinding('f5')?.ignoreShift).toBe(false)
  })

  it('拒绝未知修饰键或空键位', () => {
    expect(parseKeybinding('hyper+k')).toBeNull()
    expect(parseKeybinding('')).toBeNull()
  })
})

describe('matchesKeybinding', () => {
  it('mod 在非 macOS 上等价 Ctrl', () => {
    const binding = parseKeybinding('mod+b')!
    expect(matchesKeybinding(binding, keydown({ key: 'b', ctrlKey: true }))).toBe(true)
    expect(matchesKeybinding(binding, keydown({ key: 'b', metaKey: true }))).toBe(false)
    expect(matchesKeybinding(binding, keydown({ key: 'b' }))).toBe(false)
  })

  it('修饰键必须完全一致（避免吞掉 Ctrl+Shift+B 之类的组合）', () => {
    const binding = parseKeybinding('mod+b')!
    expect(matchesKeybinding(binding, keydown({ key: 'b', ctrlKey: true, shiftKey: true }))).toBe(false)
    expect(matchesKeybinding(binding, keydown({ key: 'b', ctrlKey: true, altKey: true }))).toBe(false)
  })

  it('符号键忽略 Shift，且可用 event.code 兜底键盘布局差异', () => {
    expect(matchesKeybinding(parseKeybinding('?')!, keydown({ key: '?', shiftKey: true }))).toBe(true)
    const backquote = parseKeybinding('mod+backquote')!
    expect(matchesKeybinding(backquote, keydown({ key: '', code: 'Backquote', ctrlKey: true }))).toBe(true)
  })

  it('功能键与方向键按小写键名匹配', () => {
    expect(matchesKeybinding(parseKeybinding('f5')!, keydown({ key: 'F5' }))).toBe(true)
    expect(matchesKeybinding(parseKeybinding('alt+arrowleft')!, keydown({ key: 'ArrowLeft', altKey: true }))).toBe(true)
  })
})

describe('CommandRegistry', () => {
  it('同一 id 重复注册时以最新为准，旧注销函数不会误删', async () => {
    const registry = new CommandRegistry()
    const first = vi.fn()
    const second = vi.fn()
    const disposeFirst = registry.register({ id: 'app.a', title: 'A', run: first })
    registry.register({ id: 'app.a', title: 'A2', run: second })
    expect(registry.get('app.a')?.title).toBe('A2')

    disposeFirst()
    await expect(registry.execute('app.a')).resolves.toBe(true)
    expect(first).not.toHaveBeenCalled()
    expect(second).toHaveBeenCalledTimes(1)
  })

  it('拒绝非法键位', () => {
    const registry = new CommandRegistry()
    expect(() => register(registry, { id: 'app.b', keys: ['hyper+b'] })).toThrow(/Invalid keybinding/)
    expect(() => register(registry, { id: '   ' })).toThrow(/Command id is required/)
  })

  it('执行命令并支持注销', async () => {
    const registry = new CommandRegistry()
    const run = vi.fn()
    register(registry, { id: 'app.a', run })
    await expect(registry.execute('app.a', 1)).resolves.toBe(true)
    expect(run).toHaveBeenCalledWith(1)
    registry.unregister('app.a')
    await expect(registry.execute('app.a')).resolves.toBe(false)
  })

  it('when 为假时不执行、也不算可展示命令', async () => {
    const registry = new CommandRegistry()
    const run = vi.fn()
    register(registry, { id: 'app.a', keys: ['mod+a'], when: () => false, run })
    expect(registry.visible()).toHaveLength(0)
    expect(registry.resolve(keydown({ key: 'a', ctrlKey: true }))).toBeNull()
    await expect(registry.execute('app.a')).resolves.toBe(false)
    expect(run).not.toHaveBeenCalled()
  })

  it('hidden 命令不出现在可展示列表里', () => {
    const registry = new CommandRegistry()
    register(registry, { id: 'app.a', keys: ['f1'] })
    register(registry, { id: 'app.a.alias', keys: ['?'], hidden: true })
    expect(registry.visible().map(command => command.id)).toEqual(['app.a'])
  })

  it('通知订阅者在注册/注销时更新，注销订阅后停止', () => {
    const registry = new CommandRegistry()
    const listener = vi.fn()
    const off = registry.onDidChange(listener)
    expect(registry.register({ id: 'app.a', title: 'A', run: () => {} })).toBeTypeOf('function')
    expect(listener).toHaveBeenCalledTimes(1)
    registry.unregister('app.a')
    expect(listener).toHaveBeenCalledTimes(2)
    off()
    registry.register({ id: 'app.b', title: 'B', run: () => {} })
    expect(listener).toHaveBeenCalledTimes(2)
  })
})

describe('CommandRegistry.resolve 守卫', () => {
  it('终端焦点默认让位，terminalSafe 命令仍可命中', () => {
    const registry = new CommandRegistry()
    register(registry, { id: 'app.toggle', keys: ['mod+b'] })
    register(registry, { id: 'terminal.toggle', keys: ['mod+backquote'], terminalSafe: true })
    const guards = { isTerminalFocused: () => true }
    expect(registry.resolve(keydown({ key: 'b', ctrlKey: true }), guards)).toBeNull()
    expect(registry.resolve(keydown({ key: '', code: 'Backquote', ctrlKey: true }), guards)?.id).toBe('terminal.toggle')
  })

  it('输入焦点默认让位，editableSafe 命令仍可命中', () => {
    const registry = new CommandRegistry()
    register(registry, { id: 'app.question', keys: ['?'] })
    register(registry, { id: 'app.palette', keys: ['mod+k'], editableSafe: true })
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    expect(registry.resolve(keydown({ key: '?', shiftKey: true }), { isEditableTarget: () => true })).toBeNull()
    expect(registry.resolve(keydown({ key: 'k', ctrlKey: true }), { isEditableTarget: () => true })?.id).toBe('app.palette')
  })

  it('多个命令共享组合键时按注册顺序取第一个', () => {
    const registry = new CommandRegistry()
    register(registry, { id: 'first', keys: ['f1'] })
    register(registry, { id: 'second', keys: ['f1'] })
    expect(registry.resolve(keydown({ key: 'F1' }))?.id).toBe('first')
  })
})

describe('installCommandKeybindings', () => {
  it('命中后派发一次并阻止默认行为', async () => {
    const registry = new CommandRegistry()
    const run = vi.fn()
    register(registry, { id: 'app.run', keys: ['mod+b'], run })
    disposers.push(installCommandKeybindings({ registry }))

    const event = keydown({ key: 'b', ctrlKey: true })
    window.dispatchEvent(event)
    await Promise.resolve()
    expect(run).toHaveBeenCalledTimes(1)
    expect(event.defaultPrevented).toBe(true)
  })

  it('忽略按键重复、输入法组合与已被消费的事件', () => {
    const registry = new CommandRegistry()
    const run = vi.fn()
    register(registry, { id: 'app.run', keys: ['mod+b'], run })
    disposers.push(installCommandKeybindings({ registry }))

    const repeated = keydown({ key: 'b', ctrlKey: true })
    Object.defineProperty(repeated, 'repeat', { value: true })
    window.dispatchEvent(repeated)

    const composing = keydown({ key: 'b', ctrlKey: true, isComposing: true })
    window.dispatchEvent(composing)

    const consumed = keydown({ key: 'b', ctrlKey: true })
    consumed.preventDefault()
    window.dispatchEvent(consumed)

    expect(run).not.toHaveBeenCalled()
  })

  it('命令抛错不会打断后续按键', async () => {
    const registry = new CommandRegistry()
    const error = vi.spyOn(console, 'error').mockImplementation(() => {})
    register(registry, { id: 'app.boom', keys: ['mod+b'], run: () => { throw new Error('boom') } })
    disposers.push(installCommandKeybindings({ registry }))
    window.dispatchEvent(keydown({ key: 'b', ctrlKey: true }))
    await Promise.resolve()
    await Promise.resolve()
    expect(error).toHaveBeenCalled()
    error.mockRestore()
  })

  it('卸载后不再响应', () => {
    const registry = new CommandRegistry()
    const run = vi.fn()
    register(registry, { id: 'app.run', keys: ['mod+b'], run })
    const dispose = installCommandKeybindings({ registry })
    dispose()
    window.dispatchEvent(keydown({ key: 'b', ctrlKey: true }))
    expect(run).not.toHaveBeenCalled()
  })
})
