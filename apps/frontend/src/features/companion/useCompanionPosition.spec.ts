import { ref } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useCompanionPosition } from './useCompanionPosition'
import { COMPANION_POSITION_KEY } from './position'

afterEach(() => { localStorage.clear(); vi.useRealTimers() })

describe('Companion position lifecycle', () => {
  it('clamps a remembered expanded panel and resets persisted placement', () => {
    localStorage.setItem(COMPANION_POSITION_KEY, '{"right":936,"bottom":300}')
    const p = useCompanionPosition({ stage: ref(null), expanded: ref(true), storage: localStorage })
    p.mount()
    expect(p.position.value).toEqual({ right: 692, bottom: 300 })
    expect(p.rootStyle.value['--companion-bottom']).toBe('300px')
    expect(localStorage.getItem(COMPANION_POSITION_KEY)).toContain('692')
    p.reset()
    expect(p.position.value).toBeNull()
    expect(localStorage.getItem(COMPANION_POSITION_KEY)).toBeNull()
    p.dispose()
  })

  it('owns drag listeners, persists on release and suppresses the generated click', () => {
    vi.useFakeTimers()
    const stage = document.createElement('div')
    vi.spyOn(stage, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 0, height: 0 } as DOMRect)
    const p = useCompanionPosition({ stage: ref(stage), expanded: ref(false), storage: localStorage })
    p.mount()
    p.onPointerDown(new MouseEvent('pointerdown', { button: 0, clientX: 100, clientY: 100 }) as PointerEvent)
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: 160, clientY: 150 }))
    expect(p.dragging.value).toBe(true)
    window.dispatchEvent(new MouseEvent('pointerup'))
    expect(p.dragging.value).toBe(false)
    expect(p.isClickSuppressed()).toBe(true)
    expect(JSON.parse(localStorage.getItem(COMPANION_POSITION_KEY)!)).toEqual({ right: 888, bottom: 396 })
    vi.runOnlyPendingTimers()
    expect(p.isClickSuppressed()).toBe(false)
    p.onPointerDown(new MouseEvent('pointerdown', { button: 0 }) as PointerEvent)
    p.dispose()
    const previous = p.position.value
    window.dispatchEvent(new MouseEvent('pointermove', { clientX: 700, clientY: 700 }))
    expect(p.position.value).toBe(previous)
    expect(p.dragging.value).toBe(false)
    expect(vi.getTimerCount()).toBe(0)
  })
})
