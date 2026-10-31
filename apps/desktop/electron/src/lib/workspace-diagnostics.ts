/**
 * 工作区诊断：用项目自己的工具链跑一次静态检查，把输出解析成「可跳转」的问题列表。
 *
 * 目前支持两类检查器，都只在检测到相应工具时运行：
 * - TypeScript：项目根或一级子目录里的 tsconfig.json + 本地 typescript
 * - Python：PATH 上的 ruff（或 python -m ruff）
 *
 * 所有外部进程都有超时和结果上限；解析函数是纯函数，方便单测。
 */
import { spawn } from 'node:child_process'
import { promises as fs } from 'node:fs'
import * as path from 'node:path'

export type DiagnosticSeverity = 'error' | 'warning' | 'info'

export interface WorkspaceDiagnosticItem {
  path: string
  line: number
  column: number
  severity: DiagnosticSeverity
  message: string
  source: string
  code: string
}

export interface WorkspaceDiagnosticsResult {
  diagnostics: WorkspaceDiagnosticItem[]
  engine: 'tsc' | 'ruff' | 'none'
  durationMs: number
  truncated: boolean
  message?: string
}

const MAX_DIAGNOSTICS = 300
const TSC_TIMEOUT_MS = 120_000
const RUFF_TIMEOUT_MS = 60_000
const PROBE_TIMEOUT_MS = 8_000

const IGNORED_DIRECTORIES = new Set(['node_modules', '.git', 'dist', 'dist-electron', 'target', '__pycache__', '.venv', 'venv', 'build', '.next'])

interface ProcessResult {
  stdout: string
  stderr: string
  code: number | null
  error: Error | null
}

const runProcess = (command: string, args: string[], options: { cwd: string; timeout: number }): Promise<ProcessResult> => new Promise(resolve => {
  let stdout = ''
  let stderr = ''
  let settled = false
  const finish = (error: Error | null, code: number | null): void => {
    if (settled) return
    settled = true
    clearTimeout(timer)
    resolve({ stdout, stderr, code, error })
  }
  let child
  try {
    child = spawn(command, args, { cwd: options.cwd, windowsHide: true })
  } catch (error) {
    resolve({ stdout: '', stderr: '', code: null, error: error as Error })
    return
  }
  const timer = setTimeout(() => {
    child.kill()
    finish(new Error('检查超时'), null)
  }, options.timeout)
  child.stdout?.setEncoding('utf8')
  child.stderr?.setEncoding('utf8')
  child.stdout?.on('data', chunk => { stdout += chunk; if (stdout.length > 4_000_000) { child.kill(); finish(new Error('输出过大'), null) } })
  child.stderr?.on('data', chunk => { stderr += chunk; if (stderr.length > 1_000_000) { child.kill(); finish(new Error('输出过大'), null) } })
  child.on('error', error => finish(error, null))
  child.on('close', code => finish(null, code))
})

const normalizePath = (root: string, file: string): string => {
  const relative = path.isAbsolute(file) ? path.relative(root, file) : file
  return relative.split(path.sep).join('/').replace(/^\.\//, '')
}

const clip = (message: string): string => message.length > 300 ? `${message.slice(0, 300)}…` : message

/** `src/a.ts(3,5): error TS2322: xxx` —— tsc --pretty false 的稳定输出格式。 */
export const parseTscOutput = (output: string, root: string): WorkspaceDiagnosticItem[] => {
  const diagnostics: WorkspaceDiagnosticItem[] = []
  const pattern = /^(.+?)\((\d+),(\d+)\):\s+(error|warning)\s+(TS\d+):\s+(.*)$/gm
  let match: RegExpExecArray | null
  while ((match = pattern.exec(output))) {
    diagnostics.push({
      path: normalizePath(root, match[1].trim()),
      line: Number(match[2]),
      column: Number(match[3]),
      severity: match[4] === 'error' ? 'error' : 'warning',
      code: match[5],
      message: clip(match[6].trim()),
      source: 'tsc'
    })
    if (diagnostics.length >= MAX_DIAGNOSTICS) break
  }
  return diagnostics
}

/** `src/a.py:3:5: F401 [*] xxx` —— ruff --output-format concise。 */
export const parseRuffOutput = (output: string, root: string): WorkspaceDiagnosticItem[] => {
  const diagnostics: WorkspaceDiagnosticItem[] = []
  const pattern = /^(.+?):(\d+):(\d+):\s+([A-Z]+\d+)\s+(.*)$/gm
  let match: RegExpExecArray | null
  while ((match = pattern.exec(output))) {
    const code = match[4]
    const severity: DiagnosticSeverity = code.startsWith('F') || code.startsWith('E') ? 'error' : code.startsWith('W') ? 'warning' : 'info'
    diagnostics.push({
      path: normalizePath(root, match[1].trim()),
      line: Number(match[2]),
      column: Number(match[3]),
      severity,
      code,
      message: clip(match[5].replace(/^\[\*\]\s*/, '').trim()),
      source: 'ruff'
    })
    if (diagnostics.length >= MAX_DIAGNOSTICS) break
  }
  return diagnostics
}

const exists = async (target: string): Promise<boolean> => {
  try { await fs.access(target); return true } catch { return false }
}

interface TsProject { directory: string; tsc: string }

const findTsProject = async (root: string): Promise<TsProject | null> => {
  // 常见布局是 monorepo：tsconfig 在 apps/* 或 packages/* 下，因此向下找两层。
  const candidates = [root]
  const queue: Array<{ directory: string; depth: number }> = [{ directory: root, depth: 0 }]
  while (queue.length && candidates.length < 40) {
    const current = queue.shift()!
    if (current.depth >= 2) continue
    let entries
    try {
      entries = await fs.readdir(current.directory, { withFileTypes: true })
    } catch {
      continue
    }
    for (const entry of entries) {
      if (!entry.isDirectory() || IGNORED_DIRECTORIES.has(entry.name) || entry.name.startsWith('.')) continue
      const directory = path.join(current.directory, entry.name)
      candidates.push(directory)
      queue.push({ directory, depth: current.depth + 1 })
    }
  }
  for (const directory of candidates) {
    if (!await exists(path.join(directory, 'tsconfig.json'))) continue
    const tsc = path.join(directory, 'node_modules', 'typescript', 'bin', 'tsc')
    if (await exists(tsc)) return { directory, tsc }
  }
  return null
}

const findPython = async (root: string): Promise<{ command: string; args: string[] } | null> => {
  for (const command of ['python', 'python3']) {
    const probe = await runProcess(command, ['-m', 'ruff', '--version'], { cwd: root, timeout: PROBE_TIMEOUT_MS })
    if (!probe.error && probe.code === 0) return { command, args: ['-m', 'ruff'] }
  }
  const direct = await runProcess('ruff', ['--version'], { cwd: root, timeout: PROBE_TIMEOUT_MS })
  if (!direct.error && direct.code === 0) return { command: 'ruff', args: [] }
  return null
}

export async function runDiagnostics(root: string): Promise<WorkspaceDiagnosticsResult> {
  const started = Date.now()
  const tsProject = await findTsProject(root)
  if (tsProject) {
    const result = await runProcess(process.execPath, [
      tsProject.tsc, '-p', path.join(tsProject.directory, 'tsconfig.json'), '--noEmit', '--pretty', 'false'
    ], { cwd: root, timeout: TSC_TIMEOUT_MS })
    if (result.error) {
      return { diagnostics: [], engine: 'none', durationMs: Date.now() - started, truncated: false, message: `TypeScript 检查未完成：${result.error.message}` }
    }
    const diagnostics = parseTscOutput(`${result.stdout}\n${result.stderr}`, root)
    return {
      diagnostics,
      engine: 'tsc',
      durationMs: Date.now() - started,
      truncated: diagnostics.length >= MAX_DIAGNOSTICS,
      message: `tsc 退出码 ${result.code ?? '未知'}`
    }
  }

  const ruff = await findPython(root)
  if (ruff) {
    const result = await runProcess(ruff.command, [...ruff.args, 'check', '--output-format', 'concise', '--quiet', '.'], {
      cwd: root,
      timeout: RUFF_TIMEOUT_MS
    })
    if (result.error) {
      return { diagnostics: [], engine: 'none', durationMs: Date.now() - started, truncated: false, message: `ruff 检查未完成：${result.error.message}` }
    }
    const diagnostics = parseRuffOutput(`${result.stdout}\n${result.stderr}`, root)
    return {
      diagnostics,
      engine: 'ruff',
      durationMs: Date.now() - started,
      truncated: diagnostics.length >= MAX_DIAGNOSTICS,
      message: `ruff 退出码 ${result.code ?? '未知'}`
    }
  }

  return {
    diagnostics: [],
    engine: 'none',
    durationMs: Date.now() - started,
    truncated: false,
    message: '未找到可运行的检查器（需要 TypeScript 或 ruff）'
  }
}

/** 诊断根目录校验：与搜索共用同一套约束。 */
export async function validateDiagnosticsRoot(input: unknown): Promise<string> {
  if (typeof input !== 'string' || !path.isAbsolute(input)) throw new Error('诊断需要绝对路径')
  const root = await fs.realpath(input)
  if (!(await fs.stat(root)).isDirectory()) throw new Error('诊断路径不是目录')
  if (path.parse(root).root === root) throw new Error('不能检查整个磁盘')
  return root
}
