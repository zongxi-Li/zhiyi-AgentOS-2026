import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import GlassConstellation from './GlassConstellation.vue'

describe('GlassConstellation', () => {
  it('exposes a controllable color agent visual for the landing hero', () => {
    const wrapper = mount(GlassConstellation)

    expect(wrapper.find('[data-testid="glass-constellation"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="agent-avatar"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="agent-shape-option"]')).toHaveLength(4)
    expect(wrapper.findAll('[data-testid="agent-action-option"]')).toHaveLength(8)
    expect(wrapper.findAll('[data-testid="agent-color-option"]')).toHaveLength(4)
    expect(wrapper.find('[data-testid="agent-voice-toggle"]').exists()).toBe(true)
  })

  it('changes shape, color, and action from the visible controls', async () => {
    const wrapper = mount(GlassConstellation)

    await wrapper.get('[data-testid="agent-shape-option"][aria-label="切换为棱面"]').trigger('click')
    await wrapper.get('[data-testid="agent-color-option"][aria-label="切换为珊瑚"]').trigger('click')
    await wrapper.findAll('[data-testid="agent-action-option"]').find(button => button.text() === '思考')?.trigger('click')

    expect(wrapper.get('[data-testid="agent-shape-option"][aria-label="切换为棱面"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-testid="agent-color-option"][aria-label="切换为珊瑚"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.find('[data-testid="agent-avatar"]').attributes('aria-label')).toContain('珊瑚棱面')
    expect(wrapper.find('.agent-stage').classes()).toContain('agent-stage--thinking')
  })

  it('offers larger expressive reactions beyond the original four moods', async () => {
    const wrapper = mount(GlassConstellation)

    await wrapper.findAll('[data-testid="agent-action-option"]').find(button => button.text() === '弹跳')?.trigger('click')
    expect(wrapper.find('.agent-stage').classes()).toContain('agent-stage--bounce')

    await wrapper.findAll('[data-testid="agent-action-option"]').find(button => button.text() === '惊讶')?.trigger('click')
    expect(wrapper.find('.agent-stage').classes()).toContain('agent-stage--surprise')
  })

  it('uses the reference blob coordinate system and geometry directly', () => {
    const wrapper = mount(GlassConstellation)

    expect(wrapper.get('[data-testid="agent-avatar"]').attributes('viewBox')).toBe('-15 -15 259 259')
    expect(wrapper.get('[data-testid="agent-avatar"] .agent-avatar__body').attributes('d')).toContain('228.541')
    expect(wrapper.find('[data-testid="agent-avatar"] .agent-avatar__reference-eye').exists()).toBe(true)
    expect(wrapper.find('[data-testid="agent-avatar"] .agent-avatar__star').exists()).toBe(true)
    expect(wrapper.get('[data-testid="agent-avatar"] .agent-avatar__body').element.parentElement?.getAttribute('transform')).toBeNull()
    expect(wrapper.get('[data-testid="agent-avatar"] .agent-avatar__reference-eye').attributes('transform')).toBeUndefined()
    expect(wrapper.get('[data-testid="agent-avatar"] .agent-avatar__reference-eye').element.parentElement?.getAttribute('transform')).toBeNull()
    expect(wrapper.get('[data-testid="agent-avatar"] .agent-avatar__shadow').attributes('transform')).toBe('translate(114.2705 114.228)')
  })

  it('keeps the hero focused on the agent without a decorative outer contour', () => {
    const wrapper = mount(GlassConstellation)

    expect(wrapper.find('.agent-stage__rings').exists()).toBe(false)
    expect(wrapper.find('.agent-avatar__rim').exists()).toBe(false)
    expect(wrapper.find('.agent-avatar__edge').exists()).toBe(false)
  })

  it('reports unsupported speech recognition without breaking the visual control', async () => {
    const wrapper = mount(GlassConstellation)

    await wrapper.get('[data-testid="agent-voice-toggle"]').trigger('click')

    expect(wrapper.text()).toContain('当前浏览器不支持语音识别')
  })

  it('keeps the control dock collapsed until the agent is clicked', async () => {
    const wrapper = mount(GlassConstellation)

    expect(wrapper.get('[data-testid="agent-controls"]').classes()).not.toContain('is-open')
    expect(wrapper.get('[data-testid="agent-avatar-trigger"]').attributes('aria-expanded')).toBe('false')

    await wrapper.get('[data-testid="agent-avatar-trigger"]').trigger('click')

    expect(wrapper.get('[data-testid="agent-controls"]').classes()).toContain('is-open')
    expect(wrapper.get('[data-testid="agent-avatar-trigger"]').attributes('aria-expanded')).toBe('true')

    await wrapper.get('[data-testid="agent-avatar-trigger"]').trigger('click')
    expect(wrapper.get('[data-testid="agent-controls"]').classes()).not.toContain('is-open')
  })

  it('uses Justin as the voice wake word before applying a command', async () => {
    const recognition = {
      lang: '',
      continuous: false,
      interimResults: false,
      onresult: null as ((event: unknown) => void) | null,
      onerror: null as (() => void) | null,
      onend: null as (() => void) | null,
      start: vi.fn(),
      stop: vi.fn()
    }
    const Recognition = vi.fn(() => recognition)
    Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: Recognition })
    const wrapper = mount(GlassConstellation)

    await wrapper.get('[data-testid="agent-voice-toggle"]').trigger('click')
    expect(recognition.continuous).toBe(true)
    expect(wrapper.get('[data-testid="glass-constellation"]').attributes('data-voice-state')).toBe('waiting')

    recognition.onresult?.({ results: [[{ transcript: 'Justin' }]], resultIndex: 0 })
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[data-testid="glass-constellation"]').attributes('data-voice-state')).toBe('awake')
    expect(wrapper.text()).toContain('已唤醒')

    recognition.onresult?.({ results: [[{ transcript: '换成紫色' }]], resultIndex: 0 })
    await wrapper.vm.$nextTick()
    expect(wrapper.get('[data-testid="agent-color-option"][aria-label="切换为紫晶"]').attributes('aria-pressed')).toBe('true')

    recognition.onresult?.({ results: [[{ transcript: '弹跳起来' }]], resultIndex: 0 })
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.agent-stage').classes()).toContain('agent-stage--bounce')

    wrapper.unmount()
    Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: undefined })
  })
})
