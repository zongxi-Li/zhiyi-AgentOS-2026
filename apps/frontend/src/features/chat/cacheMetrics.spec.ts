import { describe, expect, it } from 'vitest'
import { conversationCacheMetric } from './cacheMetrics'

describe('conversation cache metrics', () => {
  it('keeps completed usage visible while another reply streams and uses matching aggregate input', () => {
    const result = conversationCacheMetric([
      { role: 'assistant', inputTokens: 1000, cachedTokens: 800, cacheUsageAvailable: true },
      { role: 'user' }, { role: 'assistant' },
    ], true)
    expect(result).toMatchObject({ label: '80.0%', detail: '800 / 1,000 输入 Token', scope: '生成中 · 最近已统计轮次' })
  })
  it('distinguishes reported zero, unavailable vendor statistics, and legacy history', () => {
    expect(conversationCacheMetric([{ role: 'assistant', inputTokens: 100, cachedTokens: 0 }], false).label).toBe('0.0%')
    expect(conversationCacheMetric([{ role: 'assistant', inputTokens: 100, cacheUsageAvailable: false }], false).detail).toContain('供应商')
    expect(conversationCacheMetric([{ role: 'assistant', inputTokens: 100 }], false).detail).toContain('历史记录')
  })
  it('does not replace a newer unreported round with an older known hit rate', () => {
    expect(conversationCacheMetric([
      { role: 'assistant', inputTokens: 100, cachedTokens: 80 },
      { role: 'assistant', inputTokens: 200, cacheUsageAvailable: false },
    ], false)).toMatchObject({ available: false, label: '未统计' })
  })
})
