// 测试用的最小 LSP 服务：验证分帧、文档打开、诊断推送与跳转定义。
import process from 'node:process'

let buffer = ''

const send = message => {
  const body = JSON.stringify(message)
  process.stdout.write(`Content-Length: ${Buffer.byteLength(body, 'utf8')}\r\n\r\n${body}`)
}

const handle = message => {
  if (message.method === 'initialize') {
    send({ jsonrpc: '2.0', id: message.id, result: { capabilities: { textDocumentSync: 1 } } })
    return
  }
  if (message.method === 'initialized') return
  if (message.method === 'textDocument/didOpen') {
    const uri = message.params.textDocument.uri
    send({
      jsonrpc: '2.0',
      method: 'textDocument/publishDiagnostics',
      params: {
        uri,
        diagnostics: [{
          range: { start: { line: 0, character: 2 }, end: { line: 0, character: 5 } },
          severity: 1,
          message: 'fake error',
          source: 'fake-lsp'
        }]
      }
    })
    return
  }
  if (message.method === 'textDocument/definition') {
    send({
      jsonrpc: '2.0',
      id: message.id,
      result: [{
        uri: message.params.textDocument.uri,
        range: { start: { line: 3, character: 0 }, end: { line: 3, character: 4 } }
      }]
    })
    return
  }
  if (message.id !== undefined) send({ jsonrpc: '2.0', id: message.id, result: null })
}

process.stdin.on('data', chunk => {
  buffer += chunk.toString('utf8')
  while (true) {
    const headerEnd = buffer.indexOf('\r\n\r\n')
    if (headerEnd < 0) break
    const header = buffer.slice(0, headerEnd)
    const match = /Content-Length:\s*(\d+)/i.exec(header)
    if (!match) { buffer = buffer.slice(headerEnd + 4); continue }
    const length = Number(match[1])
    const bodyStart = headerEnd + 4
    if (buffer.length < bodyStart + length) break
    const body = buffer.slice(bodyStart, bodyStart + length)
    buffer = buffer.slice(bodyStart + length)
    try { handle(JSON.parse(body)) } catch { /* 忽略坏消息 */ }
  }
})
