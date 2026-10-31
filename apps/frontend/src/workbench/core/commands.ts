/**
 * 工作台命令注册表：把「命令定义 / 快捷键 / 触发条件」收敛成一份可查询的数据，
 * 快捷键派发、快捷键速查、后续的命令面板与 Agent 工具调用都读同一份定义。
 *
 * 键位串约定（贴近 VS Code 习惯）：
 * - 修饰键：`mod`（Windows/Linux=Ctrl，macOS=Cmd）、`ctrl`、`meta`、`alt`、`shift`
 * - 主键：小写字母、数字、可打印符号（`?` `` ` `` `=` `-` `/`），或 f1..f12 /
 *   arrowleft / arrowright / arrowup / arrowdown / home / end / space 等具名键
 * - 修饰键顺序无关：`mod+shift+k` 与 `shift+mod+k` 等价
 * - 主键是可打印符号（非 a-z）时隐含 Shift：`?` 用的是 Shift+/，因此不比较 shiftKey
 *
 * 派发优先级：按注册顺序取第一个命中项；同一组合键请只注册一次，
 * 需要覆盖时先注销旧命令（`register` 返回注销函数）。
 */

export interface Keybinding {
  /** 原始键位串，用于日志与错误提示。 */
  readonly text: string
  readonly mod: boolean
  readonly ctrl: boolean
  readonly meta: boolean
  readonly alt: boolean
  readonly shift: boolean
  readonly key: string
  /** 主键是可打印符号时忽略 Shift 位（`?` 必须显式按 Shift 才能输入）。 */
  readonly ignoreShift: boolean
}

export interface CommandDescriptor {
  id: string
  title: string
  /** 速查浮层/命令面板里的分组名，缺省「通用」。 */
  category?: string
  /** 展示排序，越小越靠前；缺省 100。 */
  order?: number
  /** 默认快捷键；为空表示只能从面板或代码调用。 */
  keys?: readonly string[]
  /** 返回 false 时不派发快捷键、不出现在面板里。 */
  when?: () => boolean
  /** 焦点在内置终端时是否仍响应；默认 false（把按键交还 shell）。 */
  terminalSafe?: boolean
  /** 焦点在输入框/可编辑元素时是否仍响应；默认 false。 */
  editableSafe?: boolean
  /** 内部别名（例如同一动作的第二个入口），速查里不单列。 */
  hidden?: boolean
  run: (arg?: unknown) => unknown | Promise<unknown>
}

interface RegisteredCommand {
  readonly command: CommandDescriptor
  readonly bindings: readonly Keybinding[]
}

export const isMacPlatform = (): boolean => (
  typeof navigator !== 'undefined'
  && /Mac|iPhone|iPad|iPod/.test(navigator.platform || navigator.userAgent || '')
)

const MODIFIER_TOKENS = new Set(['mod', 'ctrl', 'meta', 'alt', 'shift'])

export const normalizeEventKey = (event: KeyboardEvent): string => {
  if (event.key === ' ') return 'space'
  return (event.key || '').toLowerCase()
}

export const parseKeybinding = (text: string): Keybinding | null => {
  const tokens = text.toLowerCase().split('+').map(token => token.trim()).filter(Boolean)
  if (!tokens.length) return null
  const key = tokens.pop() as string
  if (!key) return null
  const result = { text, mod: false, ctrl: false, meta: false, alt: false, shift: false, key, ignoreShift: false }
  for (const token of tokens) {
    if (!MODIFIER_TOKENS.has(token)) return null
    result[token as 'mod' | 'ctrl' | 'meta' | 'alt' | 'shift'] = true
  }
  // 单个可打印字符（非 a-z）：Shift 已经体现在字符本身（? = Shift+/），不再单独比较。
  result.ignoreShift = key.length === 1 && !/[a-z]/.test(key)
  return result
}

export const matchesKeybinding = (binding: Keybinding, event: KeyboardEvent): boolean => {
  const mac = isMacPlatform()
  const ctrl = binding.ctrl || (binding.mod && !mac)
  const meta = binding.meta || (binding.mod && mac)
  if (event.ctrlKey !== ctrl) return false
  if (event.metaKey !== meta) return false
  if (event.altKey !== binding.alt) return false
  if (!binding.ignoreShift && event.shiftKey !== binding.shift) return false
  if (normalizeEventKey(event) === binding.key) return true
  // `event.key` 随键盘布局变化（`` ` `` 在部分布局上不是这个字符），code 作为兜底。
  return Boolean(event.code) && event.code.toLowerCase() === binding.key
}

export type CommandChangeListener = () => void

export class CommandRegistry {
  private readonly entries = new Map<string, RegisteredCommand>()
  private readonly listeners = new Set<CommandChangeListener>()

  register(command: CommandDescriptor): () => void {
    const id = command.id?.trim()
    if (!id) throw new Error('Command id is required')
    const bindings = (command.keys || []).map((text) => {
      const parsed = parseKeybinding(text)
      if (!parsed) throw new Error(`Invalid keybinding "${text}" for command ${id}`)
      return parsed
    })
    // 同一 id 重复注册时以最新为准：UI 组件在 HMR/测试里可能重复挂载，
    // 旧实例必须失效，否则会派发到已经卸载的闭包。
    const record: RegisteredCommand = { command, bindings }
    this.entries.set(id, record)
    this.emitChange()
    return () => {
      if (this.entries.get(id) === record) this.unregister(id)
    }
  }

  unregister(id: string): void {
    if (!this.entries.delete(id)) return
    this.emitChange()
  }

  get(id: string): CommandDescriptor | undefined {
    return this.entries.get(id)?.command
  }

  has(id: string): boolean {
    return this.entries.has(id)
  }

  list(): CommandDescriptor[] {
    return [...this.entries.values()].map(entry => entry.command)
  }

  /** 可用于展示的命令：注册了快捷键、未标 hidden、when 通过，并按 order 排序。 */
  visible(): CommandDescriptor[] {
    return this.list()
      .filter(command => Boolean(command.keys?.length) && !command.hidden && (command.when?.() ?? true))
      .sort((left, right) => (left.order ?? 100) - (right.order ?? 100) || left.title.localeCompare(right.title))
  }

  /** 返回与事件匹配且守卫通过的命令；命中顺序与注册顺序一致。 */
  resolve(event: KeyboardEvent, guards: KeybindingGuards = {}): CommandDescriptor | null {
    const terminalFocused = guards.isTerminalFocused?.() ?? false
    const editable = guards.isEditableTarget?.(event.target) ?? false
    for (const entry of this.entries.values()) {
      const { command, bindings } = entry
      if (!bindings.length) continue
      if (terminalFocused && !command.terminalSafe) continue
      if (editable && !command.editableSafe) continue
      if (command.when && !command.when()) continue
      if (!bindings.some(binding => matchesKeybinding(binding, event))) continue
      return command
    }
    return null
  }

  async execute(id: string, arg?: unknown): Promise<boolean> {
    const entry = this.entries.get(id)
    if (!entry) return false
    if (entry.command.when && !entry.command.when()) return false
    await entry.command.run(arg)
    return true
  }

  onDidChange(listener: CommandChangeListener): () => void {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  /** 测试或热更新用：清空全部命令并通知订阅者。 */
  reset(): void {
    if (!this.entries.size) return
    this.entries.clear()
    this.emitChange()
  }

  private emitChange(): void {
    for (const listener of [...this.listeners]) listener()
  }
}

export interface KeybindingGuards {
  isTerminalFocused?: () => boolean
  isEditableTarget?: (target: EventTarget | null) => boolean
}

export interface KeybindingDispatchOptions extends KeybindingGuards {
  registry?: CommandRegistry
  /** 注入给测试用的窗口对象；缺省取全局 window。 */
  target?: Window
}

export const commands = new CommandRegistry()

/**
 * 安装全局快捷键派发：捕获阶段监听，命中后 preventDefault 并异步执行命令。
 * 返回卸载函数；同一时刻只应安装一个派发器。
 */
export const installCommandKeybindings = (options: KeybindingDispatchOptions = {}): (() => void) => {
  const registry = options.registry || commands
  const view = options.target || (typeof window !== 'undefined' ? window : null)
  if (!view) return () => {}
  const onKeydown = (event: KeyboardEvent): void => {
    if (event.defaultPrevented || event.isComposing || event.repeat) return
    const command = registry.resolve(event, {
      isTerminalFocused: options.isTerminalFocused,
      isEditableTarget: options.isEditableTarget
    })
    if (!command) return
    event.preventDefault()
    void Promise.resolve(registry.execute(command.id)).catch((error) => {
      console.error(`[command] ${command.id} failed`, error)
    })
  }
  view.addEventListener('keydown', onKeydown, { capture: true })
  return () => view.removeEventListener('keydown', onKeydown, { capture: true })
}
