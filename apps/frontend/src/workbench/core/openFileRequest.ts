import type { WorkspaceFileOpenRequest } from '@/services/api/agentos'

/**
 * 「在编辑器里打开另一个文件」通道：LSP 跳转定义等跨文件动作使用。
 * 视图尚未注册处理器时先暂存请求，等挂载后消费。
 */
type OpenFileHandler = (request: WorkspaceFileOpenRequest) => void

let handler: OpenFileHandler | null = null
const pending: WorkspaceFileOpenRequest[] = []

export const registerOpenFile = (next: OpenFileHandler): (() => void) => {
  handler = next
  while (pending.length) handler(pending.shift() as WorkspaceFileOpenRequest)
  return () => {
    if (handler === next) handler = null
  }
}

export const requestOpenFile = (request: WorkspaceFileOpenRequest): void => {
  if (!request?.relativePath) return
  if (handler) handler(request)
  else pending.push(request)
}

export const resetOpenFile = (): void => {
  handler = null
  pending.length = 0
}
