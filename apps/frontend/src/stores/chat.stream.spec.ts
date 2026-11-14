import { chatExecutionFetch } from './chatTestFetch'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useChatStore } from './chat'
import type { ModelSettings } from '@/config/modelSettings'
import { chatApi } from '@/services/api/chat'
import { conversationApi } from '@/services/api/conversation'

const settings: ModelSettings = {
  provider: 'system', selectedModel: 'deepseek-flash', models: ['deepseek-flash'],
  apiKey: '', baseUrl: '', thinkingMode: 'standard'
}
const frame = (event: string, data: object) => `event:${event}\ndata:${JSON.stringify({event, data})}\n\n`
const respond = (chunks: string[], status = 200) => {
  vi.stubGlobal('fetch', chatExecutionFetch(vi.fn().mockImplementation(() => new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk))
      controller.close()
    }
  }), {status}))))
}
describe('Chat stream termination', () => {
  it('keeps the server watermark after a later failed call and ignores old cumulative usage', async () => {
    respond([frame('model_context',{contextUsage:{usedTokens:205000,maxTokens:1000000,measurement:'provider',source:'model'}}),
      frame('usage',{input_tokens:3000000,output_tokens:100000}),
      frame('error',{message:'later model request failed'})])
    const store = useChatStore()
    await store.sendMessageStream('task','default',settings)
    expect(store.contextUsedTokens).toBe(205000)
    expect(store.contextUsageState?.source).toBe('model')
    expect(store.messages.at(-1)?.chatExecutionState).toBe('failed')
  })
  it('updates capacity between model calls before the user turn ends, without accumulating input or bytes', async () => {
    let controller!: ReadableStreamDefaultController<Uint8Array>
    const stream = new ReadableStream<Uint8Array>({start(value) { controller = value }})
    vi.stubGlobal('fetch', chatExecutionFetch(() => new Response(stream)))
    const store = useChatStore()
    const running = store.sendMessageStream('long task', 'default', settings)
    const send = (data: object) => controller.enqueue(new TextEncoder().encode(frame('model_context', data)))
    try {
      send({contextMeasurement:'provider-usage',last_input_tokens:200000,last_output_tokens:1000,
        contextInputTokens:200000,contextWindowTokens:1000000,effectiveModel:'deepseek-flash'})
      await vi.waitFor(() => expect(store.contextUsedTokens).toBe(201000))
      expect(store.isStreaming).toBe(true)
      send({contextMeasurement:'request-bytes',requestBodyBytes:850000,contextWindowTokens:1000000})
      await vi.waitFor(() => expect(store.messages.at(-1)?.requestBodyBytes).toBe(850000))
      expect(store.contextUsedTokens).toBe(201000)
      send({contextMeasurement:'provider-usage',last_input_tokens:250000,last_output_tokens:500,
        contextInputTokens:250000,contextWindowTokens:1000000,effectiveModel:'deepseek-flash'})
      await vi.waitFor(() => expect(store.contextUsedTokens).toBe(250500))
      expect(store.isStreaming).toBe(true)
      expect(store.messages.at(-1)?.lastInputTokens).toBe(250000)
      expect(store.messages.at(-1)?.tokensUsed).toBeUndefined()
      // Compaction can decrease occupancy; the counter is not a cumulative sum.
      send({contextMeasurement:'provider-usage',last_input_tokens:40000,last_output_tokens:100,
        contextWindowTokens:1000000})
      await vi.waitFor(() => expect(store.contextUsedTokens).toBe(40100))
    } finally {
      controller.enqueue(new TextEncoder().encode(frame('done',{status:'completed'})))
      controller.close()
      await running
    }
  })
  it('uses full protocol input and last model call instead of summed multi-call input for capacity', async () => {
    respond([frame('model_context', { contextInputTokens: 4096, contextWindowTokens: 1048576,
      contextMeasurement: 'protocol-utf8-upper-bound', effectiveModel: 'glm-5.3-flash' }),
      frame('content_delta', { delta: 'ok' }), frame('usage', { input_tokens: 9000, output_tokens: 100,
      last_input_tokens: 3000, last_output_tokens: 20, cached_tokens: 2048, cacheUsageAvailable: true,
      contextWindowTokens: 1048576, protocolSession: true }), frame('done', { status: 'completed' })])
    const store = useChatStore()
    await store.sendMessageStream('test', 'default', settings)
    expect(store.contextUsedTokens).toBe(3020)
    expect(store.contextWindowTokens).toBe(1048576)
    expect(store.messages.at(-1)?.cachedTokens).toBe(2048)
    expect(store.nextContextTokens).toBeNull()
  })
  it('keeps actual token usage while a larger request byte count is reported', async () => {
    let finish!: () => void
    const stream = new ReadableStream({start(controller) {
      controller.enqueue(new TextEncoder().encode(frame('model_context', {requestBodyBytes:836280,contextMeasurement:'request-bytes',contextWindowTokens:1048576,
        responseTimings:{contextPreparationMs:12}})))
      finish = () => {controller.enqueue(new TextEncoder().encode(frame('done',{status:'completed'})));controller.close()}
    }})
    vi.stubGlobal('fetch', chatExecutionFetch(() => new Response(stream)))
    const store = useChatStore()
    store.contextUsedTokens = 200862
    const running = store.sendMessageStream('next', 'default', settings)
    try {
      await vi.waitFor(() => expect(store.messages.at(-1)?.requestBodyBytes).toBe(836280))
      expect(store.contextUsedTokens).toBe(200862)
      expect(store.contextMeasurement).toBe('usage')
      expect(store.messages.at(-1)?.responseTimings?.contextPreparationMs).toBe(12)
    } finally {finish(); await running}
  })

  it('does not overwrite measured reasoning time with total response time', async () => {
    respond([frame('reasoning_start',{}),frame('reasoning_end',{reasoningPhaseMs:17}),
      frame('content_delta',{delta:'answer'}),frame('done',{status:'completed'})])
    const store = useChatStore()
    await store.sendMessageStream('next', 'default', settings)
    expect(store.messages.at(-1)?.thinkingDurationMs).toBe(17)
  })
  beforeEach(() => {
    localStorage.clear(); setActivePinia(createPinia())
    vi.spyOn(chatApi,'getContextUsage').mockResolvedValue({contextUsage:null})
  })
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it.each([
    [frame('approval_required', { toolName: 'write_file' }), '等待你的确认'],
    [frame('execution_started', { toolName: 'run_command' }), '执行受控命令'],
    [frame('model_phase', { phase: 'tool_arguments' }), '正在准备工具调用'],
    [frame('model_phase', { phase: 'waiting', turn: 2 }), '操作已完成，等待模型处理结果'],
    [frame('model_phase', { phase: 'waiting', turn: 2 }) + frame('tool_result', {toolName:'read_file',callId:'late'}), '操作已完成，等待模型处理结果'],
    [frame('content_delta', { delta: '正文' }), '正在生成回复'],
  ])('does not let a heartbeat replace the current phase', async (phase, expected) => {
    let finish!: () => void
    const stream = new ReadableStream({ start(controller) {
      for (const value of [frame('content_delta', { delta: '部分正文' }), phase, frame('heartbeat', {}), frame('model_activity', {})]) {
        controller.enqueue(new TextEncoder().encode(value))
      }
      finish = () => { controller.enqueue(new TextEncoder().encode(frame('done', { status: 'completed' }))); controller.close() }
    } })
    vi.stubGlobal('fetch', chatExecutionFetch(vi.fn().mockResolvedValue(new Response(stream))))
    const store = useChatStore()
    const running = store.sendMessageStream('测试', 'default', settings)
    try {
      await vi.waitFor(() => expect(store.messages.at(-1)?.lastProviderActivityAt).toBeTypeOf('number'))
      const message = store.messages.at(-1)!
      expect(message.streamPhase).toBe(expected)
      expect(message.lastHeartbeatAt).toBeTypeOf('number')
    } finally { finish(); await running }
  })

  it.each(['ask', 'auto', 'full'] as const)('sends the selected %s approval mode with the tool request', async mode => {
    respond(['data:[DONE]'])
    const store = useChatStore()
    expect(store.approvalMode).toBe('ask')
    store.approvalMode = mode
    await store.sendMessageStream('检查文件', 'default', settings)
    const init = vi.mocked(fetch).mock.calls[0][1]!
    expect(JSON.parse(init.body as string)).toMatchObject({ tool_mode: 'auto', approval_mode: mode })
  })

  it('recognizes a split gateway error event and clears running status', async () => {
    respond([frame('reasoning_start', {}), 'event:err', 'or\r\ndata:{"code":"AI_UPSTREAM_TIMEOUT"}\r\n\r\n'])
    const store = useChatStore()
    await store.sendMessageStream('你好', 'default', settings)
    const reply = store.messages.at(-1)!
    expect(reply.content).toContain('模型响应超时')
    expect(reply.thinkingState).toBe('error')
    expect(reply.streamActivity).toBe('complete')
    expect(reply.streamPhase).toBe('请求未完成')
    expect(store.isStreaming).toBe(false)
    expect(reply.modelInfo).toBe('deepseek-flash')
  })

  it('preserves partial content while visibly marking an unexpected EOF', async () => {
    respond(['data:' + JSON.stringify({event:'content_delta', sequence:1, data:{delta:'已收到的正文'}}) + '\n\n'])
    const store = useChatStore()
    await store.sendMessageStream('介绍活动', 'default', settings)
    const reply = store.messages.at(-1)!
    expect(reply.content).toBe('已收到的正文')
    expect(reply.streamError).toContain('意外结束')
    expect(reply.thinkingState).toBe('error')
    expect(reply.streamActivity).toBe('complete')
  })

  it('does not turn a provider error followed by done into success', async () => {
    respond([frame('content_delta', {delta: '部分正文'}), frame('error', {code: 'AI_STREAM_FAILED'}), frame('done', {status:'completed'})])
    const store = useChatStore()
    await store.sendMessageStream('你好', 'default', settings)
    expect(store.messages.at(-1)?.thinkingState).toBe('error')
    expect(store.messages.at(-1)?.streamError).toContain('AI_STREAM_FAILED')
  })

  it('preserves partial output and shows the model idle timeout clearly', async () => {
    respond([frame('content_delta', { delta: '已生成的内容' }),
      frame('error', { code: 'AI_MODEL_IDLE_TIMEOUT', retryable: false })])
    const store = useChatStore()
    await store.sendMessageStream('继续写文件', 'default', settings)
    expect(store.messages.at(-1)).toMatchObject({ content: '已生成的内容',
      streamError: '模型输出长时间停顿，本次回复已中断', thinkingState: 'error', streamActivity: 'complete' })
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('consumes the last frame without a newline and completes normally', async () => {
    respond([frame('content_delta', {delta:'你好'}), 'data:[DONE]'])
    const store = useChatStore()
    await store.sendMessageStream('你好', 'default', settings)
    expect(store.messages.at(-1)).toMatchObject({content:'你好', thinkingState:'complete',streamActivity:'complete'})
    expect(store.messages.at(-1)?.streamError).toBeUndefined()
  })

  it('finishes HTTP rejection without a running trace', async () => {
    respond([], 401)
    const store = useChatStore()
    await store.sendMessageStream('你好', 'default', settings)
    expect(store.messages.at(-1)).toMatchObject({thinkingState:'error',streamActivity:'complete',streamPhase:'请求未完成'})
  })

  it('stops a pending read without replacing partial text', async () => {
    let reading!: () => void
    const pendingRead = new Promise<void>(resolve => { reading = resolve })
    vi.stubGlobal('fetch', chatExecutionFetch(vi.fn().mockImplementation(async (_url, init) => {
      let first = true
      return {ok:true, headers:new Headers(), body:{getReader:() => ({cancel:async () => {}, releaseLock:() => {}, read:() => {
        if (first) {
          first = false
          return Promise.resolve({done:false,value:new TextEncoder().encode(frame('content_delta', {delta:'部分正文'}))})
        }
        reading()
        return new Promise((_resolve,reject) => init.signal.addEventListener('abort', () => reject(new DOMException('Stopped','AbortError'))))
      }})}}
    })))
    const store = useChatStore()
    const running = store.sendMessageStream('介绍活动', 'default', settings)
    await pendingRead
    await store.cancelMessageStream()
    await running
    expect(store.messages.at(-1)).toMatchObject({content:'部分正文',streamError:'已停止生成',streamActivity:'complete'})
    expect(store.loading).toBe(false)
  })

  it('restores an interrupted reply from the existing history summary', async () => {
    vi.spyOn(conversationApi, 'getConversation').mockResolvedValue({ contextId: 'ctx-history' } as any)
    vi.spyOn(chatApi, 'getHistory').mockResolvedValue([{
      id:'reply',role:'ASSISTANT',content:'部分正文',metadata:{thinkingEnabled:true,
        executionSummary:[{stage:'chat_stream',status:'failed',description:'模型连接中断，请重试'}]}
    }])
    const store = useChatStore()
    await store.loadHistory('ctx-history')
    expect(store.messages.at(-1)).toMatchObject({content:'部分正文',thinkingState:'error',streamActivity:'complete',streamError:'模型连接中断，请重试'})
  })

  it('remembers a stop clicked before acknowledgement and cancels the accepted execution', async () => {
    let acknowledge!: (response: Response) => void
    const fetch = vi.fn().mockImplementationOnce(() => new Promise<Response>(resolve => {acknowledge = resolve}))
      .mockResolvedValueOnce(Response.json({cancelled: true}))
    vi.stubGlobal('fetch', fetch)
    const store = useChatStore()
    const running = store.sendMessageStream('once', 'default', settings)
    await store.cancelMessageStream()
    expect(store.messages.at(-1)?.streamPhase).toBe('正在停止生成')
    acknowledge(Response.json({chatExecutionId: 'accepted', contextId: 'context'}))
    await running
    expect(fetch.mock.calls[1][0]).toContain('/accepted/cancel')
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(store.messages.at(-1)?.chatExecutionState).toBe('cancelled')
    expect(store.isStreaming).toBe(false)
  })
})
