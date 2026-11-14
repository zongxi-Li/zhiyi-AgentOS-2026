/** Extract an SSE data field while accepting the optional space allowed after `data:`. */
export function parseSseDataLine(line: string): string | null {
  const normalized = line.endsWith('\r') ? line.slice(0, -1) : line
  if (!normalized.startsWith('data:')) return null

  const value = normalized.slice('data:'.length)
  return value.startsWith(' ') ? value.slice(1) : value
}

export interface SseFrame { event: string; data: string }

/** Decode protocol fields only; payload validation belongs to each caller. */
export function parseSseFrame(frame: string): SseFrame | null {
  let event = ''
  const data: string[] = []
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    const value = parseSseDataLine(line)
    if (value !== null) data.push(value)
  }
  return data.length ? { event, data: data.join('\n') } : null
}

/** Read frames without owning endpoint-specific retry or completion rules. */
export async function* readSseFrames(body: ReadableStream<Uint8Array>, options: {
  signal?: AbortSignal
  onActivity?: () => void
  /** Retain compatibility with endpoints that omit the final empty line. */
  flushAtEof?: boolean
} = {}): AsyncGenerator<SseFrame> {
  const { signal, onActivity, flushAtEof = false } = options
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let cancellation: Promise<void> | undefined
  const cancel = () => cancellation ||= reader.cancel().catch(() => {})
  const onAbort = () => { void cancel() }
  const checkAbort = () => {
    if (signal?.aborted) throw signal.reason ?? new DOMException('Aborted', 'AbortError')
  }
  signal?.addEventListener('abort', onAbort, { once: true })
  try {
    checkAbort()
    while (true) {
      const { done, value } = await reader.read()
      checkAbort()
      if (!done) onActivity?.()
      buffer += decoder.decode(value, { stream: !done })
      let boundary: RegExpExecArray | null
      while ((boundary = /\r?\n\r?\n/.exec(buffer))) {
        checkAbort()
        const frame = parseSseFrame(buffer.slice(0, boundary.index))
        buffer = buffer.slice(boundary.index + boundary[0].length)
        if (frame) {
          yield frame
          checkAbort()
        }
      }
      if (done) {
        const frame = flushAtEof ? parseSseFrame(buffer) : null
        if (frame) yield frame
        return
      }
    }
  } finally {
    signal?.removeEventListener('abort', onAbort)
    await cancel()
    reader.releaseLock()
  }
}

export type ChatStreamEventType =
  | 'snapshot'
  | 'heartbeat'
  | 'model_phase'
  | 'model_activity'
  | 'model_context'
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
export function parseChatStreamFrame(frame: string | SseFrame): ChatStreamEvent | null {
  const parsedFrame = typeof frame === 'string' ? parseSseFrame(frame) : frame
  if (!parsedFrame) return null
  const { event: eventName, data: payload } = parsedFrame
  if (eventName === 'error') {
    try {
      const parsed = JSON.parse(payload)
      if (!parsed.event) {
        const data: Record<string, any> = { code: parsed.code || parsed.error || 'AI_STREAM_FAILED' }
        if (typeof parsed.message === 'string' && parsed.message) data.message = parsed.message
        if (typeof parsed.retryable === 'boolean') data.retryable = parsed.retryable
        return { event: eventName, requestId: 'unknown', sequence: 0, data }
      }
    } catch { return null }
  }
  return parseChatStreamData(payload)
}

const STREAM_ERROR_MESSAGES: Record<string, string> = {
  SSE_IDLE_TIMEOUT: '等待模型响应超时，请重试',
  SSE_MAX_DURATION: '本次回复已达到最长生成时间，请重试',
  AI_STREAM_INTERRUPTED: '模型连接中断，请重试',
  AI_TURN_LIMIT_EXCEEDED: '本次回复达到工具轮数上限，请重试',
  AI_UPSTREAM_TIMEOUT: '模型响应超时，请重试',
  AI_MODEL_FIRST_RESPONSE_TIMEOUT: '等待模型开始响应超时，请重试',
  AI_MODEL_IDLE_TIMEOUT: '模型输出长时间停顿，本次回复已中断',
  AI_MODEL_TOTAL_TIMEOUT: '本次模型请求已达到时间上限',
  AI_UPSTREAM_UNREACHABLE: '无法连接模型服务，请检查网络或代理后重试',
  AI_UPSTREAM_REJECTED: '模型服务拒绝了本次请求，请重试',
  AI_CONTEXT_OVERFLOW: '上下文超出模型窗口，请缩短对话后重试'
}

export function chatStreamErrorMessage(code?: string, message?: string): string {
  const known = code ? STREAM_ERROR_MESSAGES[code] : undefined
  if (known) return known
  // Unknown code: prefer the server's fixed text, but keep the code visible so
  // a user can report it and the log line can be matched.
  if (message) return code ? `${message}（${code}）` : message
  return `回复生成失败，请重试${code ? `（${code}）` : ''}`
}
