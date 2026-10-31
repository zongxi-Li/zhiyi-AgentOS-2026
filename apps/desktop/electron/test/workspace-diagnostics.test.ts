import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mkdtemp, rm, writeFile, mkdir, symlink } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import * as path from 'node:path'
import {
  parseRuffOutput,
  parseTscOutput,
  runDiagnostics,
  validateDiagnosticsRoot
} from '../src/lib/workspace-diagnostics.ts'

test('parseTscOutput maps errors and warnings to clickable diagnostics', () => {
  const output = [
    'src/a.ts(3,5): error TS2322: Type \'string\' is not assignable to type \'number\'.',
    'C:\\ws\\src\\b.ts(10,1): warning TS6133: \'x\' is declared but its value is never read.',
    'Fake line that should be ignored',
    'src/c.ts(1,1): error TS1005: \';\' expected.'
  ].join('\r\n')

  const diagnostics = parseTscOutput(output, 'C:\\ws')
  assert.equal(diagnostics.length, 3)
  assert.deepEqual(diagnostics[0], {
    path: 'src/a.ts',
    line: 3,
    column: 5,
    severity: 'error',
    code: 'TS2322',
    message: "Type 'string' is not assignable to type 'number'.",
    source: 'tsc'
  })
  assert.equal(diagnostics[1].path, 'src/b.ts')
  assert.equal(diagnostics[1].severity, 'warning')
  assert.equal(diagnostics[2].code, 'TS1005')
})

test('parseRuffOutput maps codes to severities and strips fix markers', () => {
  const output = [
    'src/a.py:3:5: F401 [*] `os` imported but unused',
    'src/b.py:9:1: W291 Trailing whitespace',
    'src/c.py:1:1: I001 Import block is un-sorted',
    'not a diagnostic line'
  ].join('\n')

  const diagnostics = parseRuffOutput(output, '/ws')
  assert.equal(diagnostics.length, 3)
  assert.equal(diagnostics[0].severity, 'error')
  assert.equal(diagnostics[0].message, '`os` imported but unused')
  assert.equal(diagnostics[1].severity, 'warning')
  assert.equal(diagnostics[2].severity, 'info')
  assert.equal(diagnostics[2].path, 'src/c.py')
})

test('runDiagnostics uses the local TypeScript and reports clickable errors', async (t) => {
  // 复用前端已安装的 typescript，避免测试依赖网络或全局安装。
  const typescript = path.resolve(process.cwd(), '../../frontend/node_modules/typescript')
  try {
    await (await import('node:fs/promises')).access(typescript)
  } catch {
    t.skip('当前机器没有本地 typescript，跳过集成用例')
    return
  }
  const root = await mkdtemp(path.join(tmpdir(), 'zhiyi-diagnostics-ts-'))
  try {
    await mkdir(path.join(root, 'src'))
    await mkdir(path.join(root, 'node_modules'))
    await writeFile(path.join(root, 'tsconfig.json'), JSON.stringify({
      compilerOptions: { strict: true, noEmit: true, target: 'ES2020', module: 'ESNext' },
      include: ['src']
    }))
    await writeFile(path.join(root, 'src', 'bad.ts'), 'const answer: number = "nope"\n')
    await symlink(typescript, path.join(root, 'node_modules', 'typescript'), 'junction')

    const result = await runDiagnostics(root)
    assert.equal(result.engine, 'tsc')
    assert.ok(result.diagnostics.length >= 1)
    const first = result.diagnostics[0]
    assert.equal(first.path, 'src/bad.ts')
    assert.equal(first.line, 1)
    assert.equal(first.severity, 'error')
    assert.match(first.code, /^TS\d+$/)
    assert.ok(Number.isFinite(result.durationMs))
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('runDiagnostics never throws on a project without checkers', async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'zhiyi-diagnostics-empty-'))
  try {
    await writeFile(path.join(root, 'README.md'), '# empty project\n')
    const result = await runDiagnostics(root)
    assert.ok(['none', 'ruff', 'tsc'].includes(result.engine))
    assert.ok(Array.isArray(result.diagnostics))
    if (result.engine === 'none') assert.match(result.message || '', /未找到可运行的检查器/)
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('validateDiagnosticsRoot rejects relative paths, files and drive roots', async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'zhiyi-diagnostics-root-'))
  try {
    await writeFile(path.join(root, 'file.txt'), 'x')
    assert.equal(await validateDiagnosticsRoot(root), await (await import('node:fs/promises')).realpath(root))
    await assert.rejects(() => validateDiagnosticsRoot('relative'), /绝对路径/)
    await assert.rejects(() => validateDiagnosticsRoot(path.join(root, 'file.txt')), /不是目录/)
    await assert.rejects(() => validateDiagnosticsRoot(path.parse(root).root), /整个磁盘/)
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})
