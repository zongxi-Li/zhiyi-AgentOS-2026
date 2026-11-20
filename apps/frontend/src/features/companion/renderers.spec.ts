import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DEFAULT_CUSTOMIZATION } from './customization'
import { BUILTIN_SKINS } from './skins'
import { DiySvgRenderer, GrokRenderer, InlineSvgRenderer } from './renderers'

const engine = vi.hoisted(() => ({ instances: [] as any[], options: [] as any[] }))
vi.mock('@/lib/grok-character', () => ({
  GrokCharacter: vi.fn(function (_svg, options) {
    const bot = { setState: vi.fn(), setInk: vi.fn(), setEyeColor: vi.fn(), destroy: vi.fn() }
    engine.instances.push(bot)
    engine.options.push(options)
    return bot
  })
}))

beforeEach(() => { vi.useFakeTimers(); engine.instances.length = 0; engine.options.length = 0 })
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

describe('Companion renderer capabilities', () => {
  for (const [name, Renderer, index] of [
    ['static', InlineSvgRenderer, 0], ['diy', DiySvgRenderer, 2]
  ] as const) {
    it(`${name} honors palette/motion and retains voice flags across state changes`, () => {
      const stage = document.createElement('div')
      const renderer = new Renderer()
      renderer.mount(stage, { ...BUILTIN_SKINS[index], custom: { ...DEFAULT_CUSTOMIZATION, primary: '#123456', accent: '#abcdef', motion: false } })
      renderer.setSpeaking(true)
      renderer.setListening(true)
      renderer.setState('working')
      const svg = stage.querySelector('svg')!
      expect(svg.dataset.companionSpeaking).toBe('1')
      expect(svg.dataset.companionListening).toBe('1')
      expect(stage.querySelector('[stroke="#123456"]')).not.toBeNull()
      expect(stage.querySelector('.companion-face-ring')?.getAttribute('opacity')).not.toBe('0')
      expect(vi.getTimerCount()).toBe(0)
      renderer.destroy()
      expect(stage.childElementCount).toBe(0)
    })
  }

  it('adds mouth/listening feedback to Grok without replacing its eyes', async () => {
    const stage = document.createElement('div')
    const renderer = new GrokRenderer()
    await renderer.mount(stage, { ...BUILTIN_SKINS[1], custom: { ...DEFAULT_CUSTOMIZATION, motion: false } })
    renderer.setSpeaking(true)
    renderer.setListening(true)
    renderer.setState('thinking')
    const overlay = stage.querySelector('.companion-grok-voice')!
    expect(overlay).not.toBeNull()
    expect(overlay.querySelectorAll('path')).toHaveLength(1)
    expect(overlay.querySelector('.companion-face-mouth')?.getAttribute('opacity')).toBe('1')
    expect(overlay.getAttribute('data-companion-speaking')).toBe('1')
    expect(overlay.getAttribute('data-companion-listening')).toBe('1')
    expect(engine.options[0]).toMatchObject({ followPointer: false, reduceMotion: true })
    expect(engine.instances[0].setInk).toHaveBeenCalledWith(DEFAULT_CUSTOMIZATION.primary)
    expect(engine.instances[0].setEyeColor).toHaveBeenCalledWith(DEFAULT_CUSTOMIZATION.accent)
    renderer.setSpeaking(false)
    expect(overlay.querySelector('.companion-face-mouth')?.getAttribute('opacity')).toBe('0')
    renderer.destroy()
    expect(engine.instances[0].destroy).toHaveBeenCalledOnce()
    expect(stage.childElementCount).toBe(0)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('disposes blink/talk timers and respects the system reduced motion preference', () => {
    const renderer = new InlineSvgRenderer()
    renderer.mount(document.createElement('div'), BUILTIN_SKINS[0])
    renderer.setSpeaking(true)
    expect(vi.getTimerCount()).toBeGreaterThan(0)
    renderer.destroy()
    expect(vi.getTimerCount()).toBe(0)
    vi.stubGlobal('matchMedia', () => ({ matches: true }))
    const reduced = new InlineSvgRenderer()
    reduced.mount(document.createElement('div'), BUILTIN_SKINS[0])
    reduced.setSpeaking(true)
    expect(vi.getTimerCount()).toBe(0)
    reduced.destroy()
  })

  it('does not mount a Grok engine after destruction during its lazy import', async () => {
    const renderer = new GrokRenderer()
    const stage = document.createElement('div')
    const mounting = renderer.mount(stage, BUILTIN_SKINS[1])
    renderer.destroy()
    await mounting
    expect(engine.instances).toHaveLength(0)
    expect(stage.childElementCount).toBe(0)
  })
})
