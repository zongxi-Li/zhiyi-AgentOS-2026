interface CacheMessage {
  role: string
  inputTokens?: number
  cachedTokens?: number
  cacheUsageAvailable?: boolean
}

/** Cache reuse is measured against all input tokens in the same completed turn. */
export function conversationCacheMetric(messages: CacheMessage[], streaming: boolean) {
  const latestAssistant = [...messages].reverse().find(message => message.role === 'assistant')
  const latest = [...messages].reverse().find(message => message.role === 'assistant'
    && typeof message.inputTokens === 'number' && Number.isFinite(message.inputTokens) && message.inputTokens >= 0)
  const input = latest?.inputTokens
  const cached = latest?.cachedTokens
  const reported = latest?.cacheUsageAvailable !== false && typeof cached === 'number'
    && Number.isFinite(cached) && cached >= 0 && typeof input === 'number' && cached <= input
  const ratio = reported && input! > 0 ? cached! / input! : null
  const priorRound = streaming && latest !== latestAssistant && Boolean(latest)
  const detail = ratio !== null
    ? `${cached!.toLocaleString('zh-CN')} / ${input!.toLocaleString('zh-CN')} 输入 Token`
    : !latest ? streaming ? '本轮生成结束后统计' : '发送消息后统计'
      : latest.cacheUsageAvailable === false ? '供应商未返回完整缓存统计'
        : reported ? '本轮没有输入 Token' : '该轮历史记录未保存缓存统计'
  return {
    label: ratio === null ? '未统计' : `${(ratio * 100).toFixed(1)}%`,
    available: ratio !== null,
    priorRound,
    detail,
    scope: streaming && latest ? '生成中 · 最近已统计轮次' : '最近已统计轮次',
  }
}
