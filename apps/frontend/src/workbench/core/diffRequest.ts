/**
 * 「在编辑器里打开该文件的行内 diff」通道。
 * 与 reveal 相同：文件可能已打开（直接切到 diff 模式），也可能还没打开（暂存请求）。
 */
type DiffHandler = () => void

const handlers = new Map<string, DiffHandler>()
const pending = new Set<string>()

export const requestDiff = (path: string): void => {
  if (!path) return
  const handler = handlers.get(path)
  if (handler) {
    handler()
    return
  }
  pending.add(path)
}

export const registerDiff = (path: string, handler: DiffHandler): (() => void) => {
  if (!path) return () => {}
  handlers.set(path, handler)
  if (pending.delete(path)) handler()
  return () => {
    if (handlers.get(path) === handler) handlers.delete(path)
  }
}

export const resetDiff = (): void => {
  handlers.clear()
  pending.clear()
}
