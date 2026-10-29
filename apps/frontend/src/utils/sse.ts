/** Extract an SSE data field while accepting the optional space allowed after `data:`. */
export function parseSseDataLine(line: string): string | null {
  const normalized = line.endsWith('\r') ? line.slice(0, -1) : line
  if (!normalized.startsWith('data:')) return null

  const value = normalized.slice('data:'.length)
  return value.startsWith(' ') ? value.slice(1) : value
}

export type ChatStreamEventType =
  | 'heartbeat'
  | 'reasoning_start'
  | 'reasoning_delta'
  | 'reasoning_end'
  | 'content_delta'
  | 'tool_start'
  | 'tool_result'
  | 'tool_error'
  | 'approval_required'
  | 'approval_resolved'
  | 'execution_started'
  | 'stdout_delta'
  | 'stderr_delta'
  | 'execution_completed'
  | 'execution_failed'
  | 'execution_cancelled'
  | 'usage'
  | 'done'
  | 'error'
  | 'auth.invalidated'

export interface ChatStreamEvent {
  event: ChatStreamEventType
  requestId: string
  sequence: number
  data: Record<string, any>
}

export function parseChatStreamData(data: string): ChatStreamEvent | null {
  if (data === '[DONE]') {
    return { event: 'done', requestId: 'legacy', sequence: 0, data: { status: 'completed' } }
  }
  try {
    const parsed = JSON.parse(data) as Record<string, any>
    if (typeof parsed.event === 'string' && parsed.data && typeof parsed.data === 'object') {
      return {
        event: parsed.event as ChatStreamEventType,
        requestId: typeof parsed.requestId === 'string' ? parsed.requestId : 'unknown',
        sequence: typeof parsed.sequence === 'number' ? parsed.sequence : 0,
        data: parsed.data
      }
    }
    if (typeof parsed.delta === 'string') {
      return {
        event: 'content_delta',
        requestId: 'legacy',
        sequence: 0,
        data: { delta: parsed.delta }
      }
    }
    if (parsed.error) {
      return {
        event: 'error',
        requestId: 'legacy',
        sequence: 0,
        data: { code: parsed.error }
      }
    }
  } catch {
    return null
  }
  return null
}

/** Keep the SSE event field: gateway terminal events have no JSON envelope. */
export function parseChatStreamFrame(frame: string): ChatStreamEvent | null {
  let eventName = ''
  const data: string[] = []
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith('event:')) eventName = line.slice(6).trim()
    const value = parseSseDataLine(line)
    if (value !== null) data.push(value)
  }
  if (!data.length) return null
  const payload = data.join('\n')
  if (eventName === 'auth.invalidated' || eventName === 'error') {
    try {
      const parsed = JSON.parse(payload)
      if (!parsed.event) return {
        event: eventName, requestId: 'unknown', sequence: 0,
        data: { code: parsed.code || parsed.error || 'AI_STREAM_FAILED' }
      }
    } catch { return null }
  }
  return parseChatStreamData(payload)
}

export function chatStreamErrorMessage(code?: string): string {
  switch (code) {
    case 'AUTH_SESSION_INVALIDATED': return '登录会话已失效或暂时无法验证，请重新登录后重试'
    case 'SSE_IDLE_TIMEOUT': return '等待模型响应超时，请重试'
    case 'SSE_MAX_DURATION': return '本次回复已达到最长生成时间，请重试'
    case 'AI_STREAM_INTERRUPTED': return '模型连接中断，请重试'
    default: return `回复生成失败，请重试${code ? `（${code}）` : ''}`
  }
}
