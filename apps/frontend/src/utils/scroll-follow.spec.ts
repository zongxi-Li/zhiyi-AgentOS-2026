import { describe, expect, it } from 'vitest'
import { nextFollowState } from './scroll-follow'

describe('scroll follow hysteresis', () => {
  it('stays attached through growth that lands between scroll events', () => {
    // 触底后流式增长把距底距离推大（期间无滚动事件），任何非上滚的滚动事件不得误脱离
    expect(nextFollowState(true, 1000, 1000, 300)).toBe(true)
  })

  it('detaches only on user upward scroll and re-attaches at the bottom', () => {
    expect(nextFollowState(true, 980, 1000, 20)).toBe(false)
    expect(nextFollowState(false, 1000, 980, 4)).toBe(true)
    expect(nextFollowState(false, 990, 980, 30)).toBe(false)
  })

  it('keeps detached state across growth ticks and tolerates tiny jitter', () => {
    expect(nextFollowState(false, 980, 980, 500)).toBe(false)
    expect(nextFollowState(true, 999, 1000, 0)).toBe(true)
  })
})
