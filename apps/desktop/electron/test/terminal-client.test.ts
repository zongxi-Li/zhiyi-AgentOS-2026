import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createServer } from 'node:http'
import { TerminalClient } from '../src/lib/terminal-client.ts'

test('terminal transport keeps credentials in Main and scopes every operation to one owner', async () => {
  const observed: { url: string; token?: string; owner?: string }[] = []
  const server = createServer((request, response) => {
    observed.push({ url: request.url!, token: request.headers.authorization,
      owner: request.headers['x-terminal-owner'] as string })
    response.setHeader('Content-Type', 'application/json')
    response.end(JSON.stringify({ sessions: [], closed: true }))
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  try {
    const address = server.address()
    assert.ok(address && typeof address !== 'string')
    const environment = { KINLIN_TERMINAL_ENDPOINT: `http://127.0.0.1:${address.port}`,
      KINLIN_TERMINAL_TOKEN: 'test-only-private-credential' }
    const client = new TerminalClient(environment)
    assert.deepEqual(await client.list(), { sessions: [], closed: true })
    await client.closeAll()
    await new TerminalClient(environment).profiles()
    assert.equal(observed[0].token, 'Bearer test-only-private-credential')
    assert.equal(observed[0].owner, observed[1].owner)
    assert.notEqual(observed[0].owner, observed[2].owner)
    assert.equal(observed[1].url, '/sessions')
    assert.throws(() => client.read('../other', 0), /Invalid terminal session/)
    assert.throws(() => client.read('00000000-0000-0000-0000-000000000000', -1), /Invalid terminal cursor/)
    assert.equal(observed.length, 3)
  } finally { await new Promise<void>(resolve => server.close(() => resolve())) }
})

test('terminal transport rejects remote endpoints and reports missing local configuration', async () => {
  for (const endpoint of ['https://127.0.0.1:18766', 'http://example.com:18766', 'http://127.0.0.1:18766/path']) {
    assert.throws(() => new TerminalClient({ KINLIN_TERMINAL_ENDPOINT: endpoint }), /Invalid local terminal endpoint/)
  }
  await assert.rejects(new TerminalClient({}).list(), /终端服务未连接/)
})
