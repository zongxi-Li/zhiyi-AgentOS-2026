/**
 * 最小可用的 LSP 客户端（stdio + JSON-RPC 分帧）。
 * 只实现工作台需要的子集：请求/通知、服务端反向请求的兜底应答、通知订阅。
 */
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'

export interface LspErrorPayload {
  code: number
  message: string
  data?: unknown
}

interface LspIncoming {
  jsonrpc?: string
  id?: number | string
  method?: string
  params?: unknown
  result?: unknown
  error?: LspErrorPayload
}

export const encodeLspMessage = (message: unknown): Buffer => {
  const body = Buffer.from(JSON.stringify(message), 'utf8')
  return Buffer.concat([Buffer.from(`Content-Length: ${body.length}\r\n\r\n`, 'ascii'), body])
}

/** 解析 `Content-Length` 分帧；允许一次收到多个消息或半个消息。 */
export class LspFramer {
  private buffer = Buffer.alloc(0)

  push(chunk: Buffer): LspIncoming[] {
    this.buffer = Buffer.concat([this.buffer, chunk])
    const messages: LspIncoming[] = []
    while (true) {
      const headerEnd = this.buffer.indexOf('\r\n\r\n')
      if (headerEnd < 0) break
      const header = this.buffer.subarray(0, headerEnd).toString('ascii')
      const match = /Content-Length:\s*(\d+)/i.exec(header)
      if (!match) {
        // 头部损坏时丢弃，避免永久卡住。
        this.buffer = this.buffer.subarray(headerEnd + 4)
        continue
      }
      const length = Number(match[1])
      const bodyStart = headerEnd + 4
      if (this.buffer.length < bodyStart + length) break
      const body = this.buffer.subarray(bodyStart, bodyStart + length).toString('utf8')
      this.buffer = this.buffer.subarray(bodyStart + length)
      try {
        messages.push(JSON.parse(body) as LspIncoming)
      } catch {
        // 单个坏消息不应中断整条连接。
      }
    }
    return messages
  }
}

export interface LspClientOptions {
  command: string
  args: string[]
  cwd: string
  env?: NodeJS.ProcessEnv
  requestTimeoutMs?: number
}

type NotificationHandler = (params: unknown) => void

export class LspClient {
  private child: ChildProcessWithoutNullStreams | null = null
  private readonly framer = new LspFramer()
  private readonly pending = new Map<number, { resolve: (value: unknown) => void; reject: (error: Error) => void; timer: NodeJS.Timeout }>()
  private readonly handlers = new Map<string, Set<NotificationHandler>>()
  private readonly options: LspClientOptions
  private nextId = 1
  private disposed = false
  stderr = ''

  constructor(options: LspClientOptions) {
    this.options = options
  }

  get running(): boolean {
    return Boolean(this.child && !this.disposed)
  }

  start(): void {
    if (this.child) return
    const child = spawn(this.options.command, this.options.args, {
      cwd: this.options.cwd,
      windowsHide: true,
      env: { ...process.env, ...this.options.env }
    })
    child.stdout.on('data', (chunk: Buffer) => {
      for (const message of this.framer.push(chunk)) this.dispatch(message)
    })
    child.stderr.on('data', (chunk: Buffer) => {
      this.stderr = (this.stderr + chunk.toString('utf8')).slice(-4000)
    })
    child.on('exit', () => {
      this.child = null
      for (const [, entry] of this.pending) {
        clearTimeout(entry.timer)
        entry.reject(new Error('语言服务进程已退出'))
      }
      this.pending.clear()
    })
    this.child = child
  }

  request<T = unknown>(method: string, params: unknown, timeoutMs = this.options.requestTimeoutMs ?? 15000): Promise<T> {
    if (!this.child) this.start()
    const child = this.child
    if (!child) return Promise.reject(new Error('语言服务未启动'))
    const id = this.nextId++
    child.stdin.write(encodeLspMessage({ jsonrpc: '2.0', id, method, params }))
    return new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`语言服务响应超时：${method}`))
      }, timeoutMs)
      this.pending.set(id, { resolve: value => resolve(value as T), reject, timer })
    })
  }

  notify(method: string, params: unknown): void {
    if (!this.child) this.start()
    this.child?.stdin.write(encodeLspMessage({ jsonrpc: '2.0', method, params }))
  }

  onNotification(method: string, handler: NotificationHandler): () => void {
    const set = this.handlers.get(method) || new Set<NotificationHandler>()
    set.add(handler)
    this.handlers.set(method, set)
    return () => { set.delete(handler) }
  }

  dispose(): void {
    if (this.disposed) return
    this.disposed = true
    this.child?.kill()
    this.child = null
  }

  private dispatch(message: LspIncoming): void {
    if (message.method && message.id !== undefined) {
      // 服务端反向请求：按 LSP 惯例给出可用的最小应答。
      this.respond(message.id, message.method, message.params)
      return
    }
    if (message.method) {
      for (const handler of this.handlers.get(message.method) || []) handler(message.params)
      return
    }
    if (typeof message.id === 'number' && this.pending.has(message.id)) {
      const entry = this.pending.get(message.id)!
      this.pending.delete(message.id)
      clearTimeout(entry.timer)
      if (message.error) entry.reject(new Error(message.error.message || '语言服务返回错误'))
      else entry.resolve(message.result)
    }
  }

  private respond(id: number | string, method: string, params: unknown): void {
    let result: unknown = null
    if (method === 'workspace/configuration') {
      const items = Array.isArray((params as { items?: unknown[] })?.items) ? (params as { items: unknown[] }).items : []
      result = items.map(() => ({}))
    }
    this.child?.stdin.write(encodeLspMessage({ jsonrpc: '2.0', id, result }))
  }
}
