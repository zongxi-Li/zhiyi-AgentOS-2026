import { localFetch } from '@/platform/api'
import { apiUrl } from '@/platform'
import { parseChatStreamFrame, readSseFrames, type ChatStreamEvent } from '@/utils/sse'

const pause = (ms: number, signal: AbortSignal) => new Promise<void>((resolve, reject) => {
  const aborted = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')) }
  const timer = setTimeout(() => { signal.removeEventListener('abort', aborted); resolve() }, ms)
  if (signal.aborted) aborted()
  else signal.addEventListener('abort', aborted, { once: true })
})

export async function startChatExecution(payload: object, signal: AbortSignal) {
  // A lost acknowledgement retries the same command identity, never a new submission.
  const body = JSON.stringify(payload)
  for (let attempt = 0; ; attempt++) {
    let response: Response
    try {
      response = await localFetch(apiUrl('/api/chat/executions'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body, signal,
      })
    } catch (error) {
      if (signal.aborted || attempt >= 1) throw error
      await pause(250, signal); continue
    }
    if (!response.ok) throw new Error(response.status === 409
      ? '这个对话仍在回复，请先停止生成再继续'
      : `回复请求失败（HTTP ${response.status}），请重试`)
    const execution = await response.json()
    if (typeof execution.chatExecutionId !== 'string' || !execution.chatExecutionId) throw new Error('执行标识缺失，请刷新会话后继续')
    return execution as { chatExecutionId: string; contextId: string }
  }
}

export async function* followChatExecution(id: string, signal: AbortSignal, reconnect: () => void): AsyncGenerator<ChatStreamEvent> {
  let cursor = 0
  for (let attempt = 0; ; attempt++) {
    try {
      const response = await localFetch(apiUrl(`/api/chat/executions/${encodeURIComponent(id)}/events?after=${cursor}`), { signal })
      if (!response.ok) {
        // Reconnecting cannot fix ownership, credentials or a deleted execution.
        if (response.status < 500) throw Object.assign(new Error(`回复订阅失败（HTTP ${response.status}）`), { permanent: true })
        throw new Error(`回复订阅失败（HTTP ${response.status}）`)
      }
      if (!response.body) throw new Error('流式读取失败')
      for await (const frame of readSseFrames(response.body, { signal, flushAtEof: true })) {
        const event = parseChatStreamFrame(frame)
        if (!event) continue
        // Zero is the legacy no-cursor value. Snapshots replace the whole projection.
        if (!['snapshot', 'done', 'error'].includes(event.event) && event.sequence > 0 && event.sequence <= cursor) continue
        if (event.sequence > 0) cursor = Math.max(cursor, event.sequence)
        yield event
        if (event.event === 'done' || event.event === 'error') return
      }
      throw new Error('流式响应意外结束，请重新打开会话恢复进度')
    } catch (error) {
      if (signal.aborted || (error as any).permanent || attempt >= 2) throw error
    }
    reconnect()
    await pause(250 * (attempt + 1), signal)
  }
}
