import assert from 'node:assert/strict'
import { test } from 'node:test'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import * as path from 'node:path'
import { LspFramer, LspClient, encodeLspMessage } from '../src/lib/lsp-client.ts'
import { LspHost, languageIdForPath } from '../src/lib/lsp-host.ts'

const waitFor = async (predicate: () => boolean, timeoutMs = 5000): Promise<void> => {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    if (predicate()) return
    await new Promise(resolve => setTimeout(resolve, 50))
  }
  throw new Error('等待超时')
}

test('LspFramer splits concatenated and partial messages', () => {
  const framer = new LspFramer()
  const first = encodeLspMessage({ jsonrpc: '2.0', id: 1, result: { ok: true } })
  const second = encodeLspMessage({ jsonrpc: '2.0', method: 'textDocument/publishDiagnostics', params: { uri: 'file:///a.ts', diagnostics: [] } })

  assert.deepEqual(framer.push(first.subarray(0, 10)), [])
  const messages = framer.push(Buffer.concat([first.subarray(10), second]))
  assert.equal(messages.length, 2)
  assert.deepEqual(messages[0], { jsonrpc: '2.0', id: 1, result: { ok: true } })
  assert.equal((messages[1] as any).method, 'textDocument/publishDiagnostics')
})

test('LspFramer survives a corrupted header and keeps parsing', () => {
  const framer = new LspFramer()
  const corrupted = Buffer.from('Broken: 1\r\n\r\n', 'ascii')
  const valid = encodeLspMessage({ jsonrpc: '2.0', method: 'x', params: {} })
  const messages = framer.push(Buffer.concat([corrupted, valid]))
  assert.equal(messages.length, 1)
  assert.equal((messages[0] as any).method, 'x')
})

test('LspClient dispatches notifications and resolves requests', async () => {
  const server = path.resolve(process.cwd(), 'test', 'fixtures', 'fake-lsp-server.mjs')
  const client = new LspClient({ command: process.execPath, args: [server, '--stdio'], cwd: process.cwd() })
  try {
    const initialized = await client.request<{ capabilities: any }>('initialize', {})
    assert.ok(initialized.capabilities)

    const seen: any[] = []
    client.onNotification('textDocument/publishDiagnostics', params => seen.push(params))
    client.notify('textDocument/didOpen', {
      textDocument: { uri: 'file:///C:/ws/a.ts', languageId: 'typescript', version: 1, text: 'const a = 1' }
    })
    await waitFor(() => seen.length === 1)
    assert.equal(seen[0].diagnostics[0].message, 'fake error')
  } finally {
    client.dispose()
  }
})

test('LspHost reports diagnostics and definition locations', async t => {
  const root = await mkdtemp(path.join(tmpdir(), 'zhiyi-lsp-'))
  const server = path.resolve(process.cwd(), 'test', 'fixtures', 'fake-lsp-server.mjs')
  const host = new LspHost(server)
  try {
    await writeFile(path.join(root, 'a.ts'), 'const a = 1\n')
    const opened = await host.openDocument(root, 'a.ts', 'const a = 1\n')
    assert.equal(opened.languageId, 'typescript')

    await waitFor(() => host.diagnostics(root).length === 1)
    const [diagnostic] = host.diagnostics(root)
    assert.deepEqual(diagnostic, {
      path: 'a.ts',
      line: 1,
      column: 3,
      severity: 'error',
      message: 'fake error',
      source: 'fake-lsp'
    })

    const locations = await host.definition(root, 'a.ts', 1, 4)
    assert.deepEqual(locations, [{ path: 'a.ts', line: 4, column: 1 }])
  } finally {
    host.dispose()
    // 语言服务进程还以临时目录为 cwd，Windows 上要等它真正退出才能删目录。
    for (let attempt = 0; attempt < 10; attempt += 1) {
      try {
        await rm(root, { recursive: true, force: true })
        break
      } catch {
        await new Promise(resolve => setTimeout(resolve, 200))
      }
    }
  }
  t.diagnostic('LSP host round-trip covered')
})

test('languageIdForPath covers JS/TS extensions only', () => {
  assert.equal(languageIdForPath('src/a.ts'), 'typescript')
  assert.equal(languageIdForPath('src/a.tsx'), 'typescriptreact')
  assert.equal(languageIdForPath('src/a.js'), 'javascript')
  assert.equal(languageIdForPath('src/a.py'), null)
  assert.equal(languageIdForPath('README.md'), null)
})
