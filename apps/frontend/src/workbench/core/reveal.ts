/**
 * 跨面板的「打开并定位到某一行」通道。
 *
 * 搜索/诊断点击时先投递行号再打开文件：编辑器可能还没挂载（异步 chunk），
 * 也可能已经打开。已挂载就立即定位，未挂载则暂存，等编辑器注册时消费。
 */
type RevealHandler = (line: number) => void

const handlers = new Map<string, RevealHandler>()
const pending = new Map<string, number>()

export const requestReveal = (path: string, line: number): void => {
  if (!path) return
  const handler = handlers.get(path)
  if (handler) {
    handler(line)
    return
  }
  pending.set(path, line)
}

export const registerReveal = (path: string, handler: RevealHandler): (() => void) => {
  if (!path) return () => {}
  handlers.set(path, handler)
  const line = pending.get(path)
  if (line !== undefined) {
    pending.delete(path)
    handler(line)
  }
  return () => {
    if (handlers.get(path) === handler) handlers.delete(path)
  }
}

/** 测试与工作区切换时清空，避免把旧的待定位行带到新文件。 */
export const resetReveal = (): void => {
  handlers.clear()
  pending.clear()
}
