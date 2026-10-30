/** Desktop transport only. PTY processes and their lifecycle belong to the local terminal service. */
import { randomUUID } from 'node:crypto'

export class TerminalClient {
  private readonly owner = randomUUID()
  private readonly endpoint: string
  private readonly token: string

  constructor(environment: NodeJS.ProcessEnv = process.env) {
    this.endpoint = environment.KINLIN_TERMINAL_ENDPOINT || ''
    this.token = environment.KINLIN_TERMINAL_TOKEN || ''
    if (this.endpoint) {
      const url = new URL(this.endpoint)
      if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.username || url.password
          || url.pathname !== '/' || url.search || url.hash) throw new Error('Invalid local terminal endpoint')
    }
  }

  private async request(method: string, route: string, body?: unknown): Promise<unknown> {
    if (!this.endpoint || !this.token) throw new Error('终端服务未连接，请通过本地启动入口重新打开知弈')
    let response: Response
    try {
      response = await fetch(new URL(route, this.endpoint), {
        method, headers: { Authorization: `Bearer ${this.token}`, 'X-Terminal-Owner': this.owner, 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(8000)
      })
    } catch { throw new Error('无法连接本地终端服务，请检查本地环境是否已启动') }
    const data = await response.json() as { error?: string }
    if (!response.ok) throw new Error(data.error || '终端操作失败')
    return data
  }

  private session(id: unknown): string {
    if (typeof id !== 'string' || !/^[a-f0-9-]{36}$/.test(id)) throw new Error('Invalid terminal session')
    return `/sessions/${id}`
  }
  profiles(): Promise<unknown> { return this.request('GET', '/profiles') }
  list(): Promise<unknown> { return this.request('GET', '/sessions') }
  create(options: unknown): Promise<unknown> { return this.request('POST', '/sessions', options) }
  read(id: unknown, after: unknown): Promise<unknown> {
    if (!Number.isSafeInteger(after) || Number(after) < 0) throw new Error('Invalid terminal cursor')
    return this.request('GET', `${this.session(id)}/output?after=${after}`)
  }
  write(id: unknown, data: unknown): Promise<unknown> { return this.request('POST', `${this.session(id)}/input`, { data }) }
  resize(id: unknown, cols: unknown, rows: unknown): Promise<unknown> { return this.request('POST', `${this.session(id)}/resize`, { cols, rows }) }
  close(id: unknown): Promise<unknown> { return this.request('DELETE', this.session(id)) }
  async closeAll(): Promise<void> { if (this.endpoint && this.token) await this.request('DELETE', '/sessions') }
}
