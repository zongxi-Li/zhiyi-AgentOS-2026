/**
 * 工作区全文搜索：优先调用 ripgrep（快、尊重 .gitignore），
 * 机器上没有 rg 时退化为受控的 Node 递归扫描（有文件数/体积/结果上限）。
 * 只读操作，永远不跟随符号链接。
 */
import { spawn } from 'node:child_process'
import { promises as fs } from 'node:fs'
import * as path from 'node:path'

export interface WorkspaceSearchOptions {
  query: string
  caseSensitive?: boolean
  maxResults?: number
}

export interface WorkspaceSearchMatch {
  /** 相对工作区根目录的路径，统一用 / 分隔 */
  path: string
  line: number
  text: string
}

export interface WorkspaceSearchResult {
  matches: WorkspaceSearchMatch[]
  truncated: boolean
  engine: 'ripgrep' | 'node'
}

const DEFAULT_MAX_RESULTS = 200
const MAX_FILE_BYTES = 512 * 1024
const MAX_FILES = 4000
const MAX_LINE_LENGTH = 400
const RIPGREP_TIMEOUT_MS = 15000

const IGNORED_DIRECTORIES = new Set([
  '.git', 'node_modules', 'dist', 'dist-electron', 'target', '__pycache__',
  '.venv', 'venv', 'coverage', '.pytest_cache', '.mypy_cache', '.ruff_cache',
  'build', '.next', '.nuxt', '.idea', '.cache'
])

export function normalizeSearchOptions(raw: unknown): WorkspaceSearchOptions {
  const source = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>
  const query = typeof source.query === 'string' ? source.query.trim() : ''
  const maxResults = Number(source.maxResults)
  return {
    query: query.slice(0, 200),
    caseSensitive: source.caseSensitive === true,
    maxResults: Number.isFinite(maxResults) && maxResults > 0
      ? Math.min(Math.floor(maxResults), DEFAULT_MAX_RESULTS * 5)
      : DEFAULT_MAX_RESULTS
  }
}

const normalizeRelative = (root: string, file: string): string => (
  path.relative(root, file).split(path.sep).join('/')
)

const clipLine = (text: string): string => (
  text.length > MAX_LINE_LENGTH ? `${text.slice(0, MAX_LINE_LENGTH)}…` : text
)

const runRipgrep = (
  root: string,
  options: WorkspaceSearchOptions,
  maxResults: number
): Promise<WorkspaceSearchResult | null> => new Promise(resolve => {
  let settled = false
  const finish = (result: WorkspaceSearchResult | null): void => {
    if (settled) return
    settled = true
    clearTimeout(timer)
    resolve(result)
  }
  const args = [
    '--json', '--no-config', '--color', 'never',
    '--max-count', '50', '--max-filesize', '2M',
    ...(options.caseSensitive ? ['--case-sensitive'] : ['--ignore-case'])
  ]
  for (const directory of IGNORED_DIRECTORIES) args.push('--glob', `!**/${directory}/**`)
  args.push('--', options.query, '.')
  let child
  try {
    child = spawn('rg', args, { cwd: root, windowsHide: true })
  } catch {
    finish(null)
    return
  }
  const timer = setTimeout(() => { child.kill(); finish(null) }, RIPGREP_TIMEOUT_MS)
  child.on('error', () => finish(null))
  let buffer = ''
  const matches: WorkspaceSearchMatch[] = []
  let truncated = false
  child.stdout.setEncoding('utf8')
  child.stdout.on('data', (chunk: string) => {
    buffer += chunk
    let index = buffer.indexOf('\n')
    while (index >= 0) {
      const line = buffer.slice(0, index)
      buffer = buffer.slice(index + 1)
      index = buffer.indexOf('\n')
      if (!line.startsWith('{')) continue
      let event: any
      try { event = JSON.parse(line) } catch { continue }
      if (event?.type !== 'match') continue
      if (matches.length >= maxResults) { truncated = true; continue }
      matches.push({
        path: String(event.data?.path?.text || '').split(path.sep).join('/').replace(/^\.\//, ''),
        line: Number(event.data?.line_number) || 0,
        text: clipLine(String(event.data?.lines?.text || '').replace(/\r?\n$/, ''))
      })
    }
  })
  child.on('close', () => finish({ matches, truncated, engine: 'ripgrep' }))
})

const readTextFile = async (file: string): Promise<string | null> => {
  try {
    const stat = await fs.stat(file)
    if (!stat.isFile() || stat.size > MAX_FILE_BYTES) return null
    const buffer = await fs.readFile(file)
    // 含 NUL 字节的按二进制处理，避免把图片/压缩包当成文本搜索。
    if (buffer.subarray(0, 2048).includes(0)) return null
    return buffer.toString('utf8')
  } catch {
    return null
  }
}

/** 没有 ripgrep 时的兜底：受控递归扫描，结果与文件数都有上限。 */
export async function searchWithNode(
  root: string,
  options: WorkspaceSearchOptions,
  maxResults = options.maxResults || DEFAULT_MAX_RESULTS
): Promise<WorkspaceSearchResult> {
  const matches: WorkspaceSearchMatch[] = []
  const needle = options.caseSensitive ? options.query : options.query.toLowerCase()
  let visited = 0
  let truncated = false

  const scan = async (directory: string): Promise<void> => {
    if (truncated) return
    let entries
    try {
      entries = await fs.readdir(directory, { withFileTypes: true })
    } catch {
      return
    }
    for (const entry of entries) {
      if (truncated) return
      if (entry.isSymbolicLink()) continue
      const full = path.join(directory, entry.name)
      if (entry.isDirectory()) {
        if (IGNORED_DIRECTORIES.has(entry.name) || entry.name.startsWith('.')) continue
        await scan(full)
        continue
      }
      if (!entry.isFile()) continue
      if (visited >= MAX_FILES) { truncated = true; return }
      visited += 1
      const text = await readTextFile(full)
      if (!text) continue
      const lines = text.split(/\r?\n/)
      for (let index = 0; index < lines.length; index += 1) {
        const line = lines[index]
        const haystack = options.caseSensitive ? line : line.toLowerCase()
        if (!haystack.includes(needle)) continue
        if (matches.length >= maxResults) { truncated = true; return }
        matches.push({ path: normalizeRelative(root, full), line: index + 1, text: clipLine(line.trim()) })
      }
    }
  }

  await scan(root)
  return { matches, truncated, engine: 'node' }
}

export async function searchWorkspace(
  root: string,
  options: WorkspaceSearchOptions
): Promise<WorkspaceSearchResult> {
  const normalized = normalizeSearchOptions(options)
  if (!normalized.query) return { matches: [], truncated: false, engine: 'ripgrep' }
  const maxResults = normalized.maxResults || DEFAULT_MAX_RESULTS
  const viaRipgrep = await runRipgrep(root, normalized, maxResults)
  if (viaRipgrep) return viaRipgrep
  return searchWithNode(root, normalized, maxResults)
}

/** 校验搜索根目录：绝对路径、真实目录、不是盘符根。 */
export async function validateSearchRoot(input: unknown): Promise<string> {
  if (typeof input !== 'string' || !path.isAbsolute(input)) throw new Error('搜索需要绝对路径')
  const root = await fs.realpath(input)
  const stat = await fs.stat(root)
  if (!stat.isDirectory()) throw new Error('搜索路径不是目录')
  if (path.parse(root).root === root) throw new Error('不能搜索整个磁盘')
  return root
}
