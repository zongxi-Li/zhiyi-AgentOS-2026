/**
 * LSP 宿主：按工作区根目录维护一个语言服务进程，负责文档同步、诊断收集和跳转定义。
 * v1 只接入 TypeScript 语言服务（typescript-language-server），未安装时静默降级。
 */
import { existsSync } from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { LspClient } from './lsp-client.ts'

export interface LspDiagnosticItem {
  path: string
  line: number
  column: number
  severity: 'error' | 'warning' | 'info'
  message: string
  source: string
}

export interface LspLocationItem {
  path: string
  line: number
  column: number
}

export interface LspOpenResult {
  languageId: string | null
}

interface Session {
  root: string
  client: LspClient
  ready: Promise<void>
  diagnostics: Map<string, LspDiagnosticItem[]>
  documents: Map<string, { version: number; text: string }>
}

const LANGUAGE_BY_EXTENSION: Record<string, string> = {
  '.ts': 'typescript',
  '.tsx': 'typescriptreact',
  '.mts': 'typescript',
  '.cts': 'typescript',
  '.js': 'javascript',
  '.jsx': 'javascriptreact',
  '.mjs': 'javascript',
  '.cjs': 'javascript'
}

const MAX_DIAGNOSTICS = 500

export const languageIdForPath = (filePath: string): string | null => {
  const extension = path.extname(filePath).toLowerCase()
  return LANGUAGE_BY_EXTENSION[extension] || null
}

const resolveServerPath = (): string | null => {
  const candidates = [
    path.join(__dirname, '..', 'node_modules', 'typescript-language-server', 'lib', 'cli.mjs'),
    path.join(process.cwd(), 'node_modules', 'typescript-language-server', 'lib', 'cli.mjs'),
    path.join(process.cwd(), '..', 'desktop', 'electron', 'node_modules', 'typescript-language-server', 'lib', 'cli.mjs')
  ]
  return candidates.find(candidate => existsSync(candidate)) ?? null
}

const severityOf = (value: unknown): LspDiagnosticItem['severity'] => (
  value === 1 ? 'error' : value === 2 ? 'warning' : 'info'
)

const toRelative = (root: string, uri: string): string => {
  try {
    return path.relative(root, fileURLToPath(uri)).split(path.sep).join('/')
  } catch {
    return uri
  }
}

const asArray = <T>(value: T | T[] | null | undefined): T[] => (
  Array.isArray(value) ? value : value ? [value] : []
)

export class LspHost {
  private readonly sessions = new Map<string, Session>()
  private readonly serverPath: string | null
  private readonly onDiagnostics?: (root: string, diagnostics: LspDiagnosticItem[]) => void

  constructor(serverPath: string | null = resolveServerPath(), onDiagnostics?: (root: string, diagnostics: LspDiagnosticItem[]) => void) {
    this.serverPath = serverPath
    this.onDiagnostics = onDiagnostics
  }

  get available(): boolean {
    return Boolean(this.serverPath)
  }

  private async ensure(root: string): Promise<Session | null> {
    if (!this.serverPath) return null
    const existing = this.sessions.get(root)
    if (existing) {
      await existing.ready
      return existing
    }
    const client = new LspClient({
      command: process.execPath,
      args: [this.serverPath, '--stdio'],
      cwd: root,
      // 打包后的 Electron 以 node 模式跑服务脚本；普通 node 下该变量无副作用。
      env: { ELECTRON_RUN_AS_NODE: '1' }
    })
    const session: Session = { root, client, ready: Promise.resolve(), diagnostics: new Map(), documents: new Map() }
    session.ready = this.initialize(session)
    this.sessions.set(root, session)
    try {
      await session.ready
    } catch (error) {
      client.dispose()
      this.sessions.delete(root)
      throw error
    }
    return session
  }

  private async initialize(session: Session): Promise<void> {
    session.client.onNotification('textDocument/publishDiagnostics', (params: any) => {
      const uri = String(params?.uri || '')
      if (!uri) return
      const items = asArray<any>(params?.diagnostics).slice(0, MAX_DIAGNOSTICS).map(diagnostic => ({
        path: toRelative(session.root, uri),
        line: Number(diagnostic?.range?.start?.line ?? 0) + 1,
        column: Number(diagnostic?.range?.start?.character ?? 0) + 1,
        severity: severityOf(diagnostic?.severity),
        message: String(diagnostic?.message || ''),
        source: String(diagnostic?.source || 'lsp')
      }))
      session.diagnostics.set(uri, items)
      this.onDiagnostics?.(session.root, this.diagnostics(session.root))
    })

    const rootUri = pathToFileURL(session.root).href
    await session.client.request('initialize', {
      processId: process.pid,
      rootUri,
      workspaceFolders: [{ uri: rootUri, name: path.basename(session.root) }],
      capabilities: {
        textDocument: { synchronization: { didSave: true }, definition: {}, publishDiagnostics: {} },
        workspace: { configuration: true, workspaceFolders: true }
      }
    }, 20000)
    session.client.notify('initialized', {})
  }

  /** 打开文档时同步给语言服务；不支持的扩展名返回 languageId=null。 */
  async openDocument(root: string, relativePath: string, text: string): Promise<LspOpenResult> {
    const languageId = languageIdForPath(relativePath)
    if (!languageId) return { languageId: null }
    const session = await this.ensure(root)
    if (!session) return { languageId: null }
    const uri = pathToFileURL(path.join(root, relativePath)).href
    const version = (session.documents.get(uri)?.version || 0) + 1
    session.documents.set(uri, { version, text })
    session.client.notify('textDocument/didOpen', { textDocument: { uri, languageId, version, text } })
    return { languageId }
  }

  /** 文档变化：全量同步（编辑场景足够，v1 不做增量区间）。 */
  async changeDocument(root: string, relativePath: string, text: string): Promise<void> {
    const session = this.sessions.get(root)
    if (!session) return
    const uri = pathToFileURL(path.join(root, relativePath)).href
    const current = session.documents.get(uri)
    if (!current) return
    const version = current.version + 1
    session.documents.set(uri, { version, text })
    session.client.notify('textDocument/didChange', { textDocument: { uri, version }, contentChanges: [{ text }] })
  }

  async closeDocument(root: string, relativePath: string): Promise<void> {
    const session = this.sessions.get(root)
    if (!session) return
    const uri = pathToFileURL(path.join(root, relativePath)).href
    if (!session.documents.has(uri)) return
    session.documents.delete(uri)
    session.diagnostics.delete(uri)
    session.client.notify('textDocument/didClose', { textDocument: { uri } })
  }

  diagnostics(root: string): LspDiagnosticItem[] {
    const session = this.sessions.get(root)
    if (!session) return []
    return [...session.diagnostics.values()].flat()
  }

  async definition(root: string, relativePath: string, line: number, column: number): Promise<LspLocationItem[]> {
    const session = this.sessions.get(root)
    if (!session) return []
    const uri = pathToFileURL(path.join(root, relativePath)).href
    const result = await session.client.request<any>('textDocument/definition', {
      textDocument: { uri },
      position: { line: Math.max(line - 1, 0), character: Math.max(column - 1, 0) }
    })
    return asArray<any>(result).map(location => {
      const target = location.targetUri || location.uri
      const range = location.targetSelectionRange || location.range
      return {
        path: toRelative(session.root, String(target || '')),
        line: Number(range?.start?.line ?? 0) + 1,
        column: Number(range?.start?.character ?? 0) + 1
      }
    }).filter(item => Boolean(item.path))
  }

  dispose(): void {
    for (const session of this.sessions.values()) session.client.dispose()
    this.sessions.clear()
  }
}
