import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import * as path from 'node:path'
import { normalizeSearchOptions, searchWithNode, searchWorkspace, validateSearchRoot } from '../src/lib/workspace-search.ts'

const createFixture = async (): Promise<string> => {
  const root = await mkdtemp(path.join(tmpdir(), 'zhiyi-search-'))
  await mkdir(path.join(root, 'src'))
  await mkdir(path.join(root, 'node_modules'))
  await mkdir(path.join(root, '.git'))
  await writeFile(path.join(root, 'src', 'a.ts'), 'const answer = 42\n// TODO: answer again\n')
  await writeFile(path.join(root, 'src', 'b.py'), 'answer = 21\n')
  await writeFile(path.join(root, 'node_modules', 'dep.js'), 'answer = 0\n')
  await writeFile(path.join(root, '.git', 'config'), 'answer\n')
  await writeFile(path.join(root, 'image.bin'), Buffer.from([0, 1, 2, 3]))
  return root
}

test('node fallback: relative paths, line numbers and ignored directories', async () => {
  const root = await createFixture()
  try {
    const result = await searchWithNode(root, { query: 'answer', maxResults: 10 })
    assert.equal(result.engine, 'node')
    assert.equal(result.truncated, false)
    assert.deepEqual(
      result.matches.map(match => `${match.path}:${match.line}`),
      ['src/a.ts:1', 'src/a.ts:2', 'src/b.py:1']
    )
    assert.ok(result.matches.every(match => !match.path.includes('node_modules')))
    assert.ok(result.matches.every(match => !match.path.includes('.git/')))
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('node fallback: honors maxResults and reports truncation', async () => {
  const root = await createFixture()
  try {
    const result = await searchWithNode(root, { query: 'answer', maxResults: 1 })
    assert.equal(result.matches.length, 1)
    assert.equal(result.truncated, true)
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('searchWorkspace returns matches regardless of engine', async () => {
  const root = await createFixture()
  try {
    const result = await searchWorkspace(root, { query: 'answer' })
    assert.ok(['ripgrep', 'node'].includes(result.engine))
    assert.ok(result.matches.some(match => match.path === 'src/a.ts' && match.line === 1))
    assert.ok(result.matches.every(match => !match.path.startsWith('/') && !match.path.includes('\\')))
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('searchWorkspace is case-insensitive unless caseSensitive is set', async () => {
  const root = await createFixture()
  try {
    const insensitive = await searchWorkspace(root, { query: 'ANSWER' })
    assert.ok(insensitive.matches.length > 0)
    const sensitive = await searchWorkspace(root, { query: 'ANSWER', caseSensitive: true })
    assert.equal(sensitive.matches.length, 0)
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('validateSearchRoot rejects relative paths and filesystem roots', async () => {
  const root = await createFixture()
  try {
    const resolved = await validateSearchRoot(root)
    assert.equal(path.basename(resolved), path.basename(root))
    await assert.rejects(() => validateSearchRoot('relative/path'), /绝对路径/)
    await assert.rejects(() => validateSearchRoot(path.parse(root).root), /整个磁盘/)
    await assert.rejects(() => validateSearchRoot(path.join(root, 'src', 'a.ts')), /不是目录/)
  } finally {
    await rm(root, { recursive: true, force: true })
  }
})

test('normalizeSearchOptions trims and bounds user input', () => {
  assert.deepEqual(normalizeSearchOptions({ query: '  hello  ' }), { query: 'hello', caseSensitive: false, maxResults: 200 })
  assert.equal(normalizeSearchOptions({ query: 'x'.repeat(500) }).query.length, 200)
  assert.equal(normalizeSearchOptions({ query: 'x', maxResults: 99999 }).maxResults, 1000)
  assert.equal(normalizeSearchOptions(null).query, '')
})
