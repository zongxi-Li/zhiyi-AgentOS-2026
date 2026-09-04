import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'
import GlassConstellation from './GlassConstellation.vue'

describe('GlassConstellation', () => {
  const mountAgent = () => mount(GlassConstellation, {
    global: { plugins: [createPinia()] }
  })

  it('exposes a controllable color agent visual for the landing hero', () => {
    const wrapper = mountAgent()

    expect(wrapper.find('[data-testid="glass-constellation"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="agent-avatar"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="agent-shape-option"]')).toHaveLength(4)
    expect(wrapper.findAll('[data-testid="agent-action-option"]')).toHaveLength(8)
    expect(wrapper.findAll('[data-testid="agent-color-option"]')).toHaveLength(8)
    expect(wrapper.get('[data-testid="agent-shape-option"][aria-label="切换为圆团"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-testid="agent-color-option"][aria-label="切换为紫晶"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.find('[data-testid="agent-voice-toggle"]').exists()).toBe(true)
  })

  it('changes shape, color, and action from the visible controls', async () => {
    const wrapper = mountAgent()

    await wrapper.get('[data-testid="agent-shape-option"][aria-label="切换为棱面"]').trigger('click')
    await wrapper.get('[data-testid="agent-color-option"][aria-label="切换为珊瑚"]').trigger('click')
    await wrapper.findAll('[data-testid="agent-action-option"]').find(button => button.text() === '思考')?.trigger('click')

    expect(wrapper.get('[data-testid="agent-shape-option"][aria-label="切换为棱面"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-testid="agent-color-option"][aria-label="切换为珊瑚"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.find('[data-testid="agent-avatar"]').attributes('aria-label')).toContain('珊瑚棱面')
    expect(wrapper.find('.agent-stage').classes()).toContain('agent-stage--thinking')
  })

  it('offers larger expressive reactions beyond the original four moods', async () => {
    const wrapper = mountAgent()

    await wrapper.findAll('[data-testid="agent-action-option"]').find(button => button.text() === '弹跳')?.trigger('click')
    expect(wrapper.find('.agent-stage').classes()).toContain('agent-stage--bounce')

    await wrapper.findAll('[data-testid="agent-action-option"]').find(button => button.text() === '惊讶')?.trigger('click')
    expect(wrapper.find('.agent-stage').classes()).toContain('agent-stage--surprise')
  })

  it('uses the reference blob coordinate system and geometry directly', async () => {
    const wrapper = mountAgent()

    await wrapper.get('[data-testid="agent-shape-option"][aria-label="切换为流体"]').trigger('click')

    expect(wrapper.get('[data-testid="agent-avatar"]').attributes('viewBox')).toBe('-15 -15 259 259')
    const activeBody = wrapper.findAll('[data-testid="agent-avatar"] .agent-avatar__body')
      .find(node => !node.classes().includes('agent-avatar__body--leaving'))
    expect(activeBody?.attributes('d')).toContain('228.541')
    expect(wrapper.find('[data-testid="agent-avatar"] .agent-avatar__reference-eye').exists()).toBe(true)
    expect(wrapper.find('[data-testid="agent-avatar"] .agent-avatar__star').exists()).toBe(true)
    expect(activeBody?.element.parentElement?.getAttribute('transform')).toBeNull()
    expect(wrapper.get('[data-testid="agent-avatar"] .agent-avatar__reference-eye').attributes('transform')).toBeUndefined()
    expect(wrapper.get('[data-testid="agent-avatar"] .agent-avatar__reference-eye').element.parentElement?.getAttribute('transform')).toBeNull()
    expect(wrapper.find('[data-testid="agent-avatar"] .agent-avatar__shadow').exists()).toBe(false)
  })

  it('keeps the original reference face geometry without custom facial elements', async () => {
    const wrapper = mountAgent()

    await wrapper.get('[data-testid="agent-shape-option"][aria-label="切换为流体"]').trigger('click')

    expect(wrapper.get('[data-testid="agent-avatar"] .agent-avatar__reference-eye').attributes('d')).toContain('M130.36 45.98')
    expect(wrapper.get('[data-testid="agent-avatar"] .agent-avatar__reference-eye:nth-of-type(2)').attributes('d')).toContain('M176.61 37.08')
    expect(wrapper.findAll('[data-testid="agent-avatar"] .agent-avatar__pupil')).toHaveLength(0)
    expect(wrapper.findAll('[data-testid="agent-avatar"] .agent-avatar__eye-glint')).toHaveLength(0)
    expect(wrapper.find('[data-testid="agent-avatar"] .agent-avatar__mouth').exists()).toBe(false)
  })

  it('keeps the eyes front-facing while following the pointer angle', async () => {
    const wrapper = mountAgent()
    const root = wrapper.get('[data-testid="glass-constellation"]')
    vi.spyOn(root.element, 'getBoundingClientRect').mockReturnValue({
      left: 0, top: 0, width: 100, height: 100, right: 100, bottom: 100,
      x: 0, y: 0, toJSON: () => ({})
    })

    await root.trigger('pointermove', { clientX: 100, clientY: 20 })
    const rightLook = wrapper.get('.agent-avatar__face').attributes('style') || ''
    expect(rightLook).toContain('rotateX(-0.92deg)')
    expect(rightLook).toContain('rotateY(-2.64deg)')
    expect(rightLook).toContain('rotate(1.66deg)')

    await root.trigger('pointermove', { clientX: 0, clientY: 80 })
    const leftLook = wrapper.get('.agent-avatar__face').attributes('style') || ''
    expect(leftLook).toContain('rotateX(0.92deg)')
    expect(leftLook).toContain('rotateY(2.64deg)')
    expect(leftLook).toContain('rotate(-1.66deg)')
    expect(leftLook).not.toBe(rightLook)
  })

  it('keeps non-blob eyes anchored to the active shape center', async () => {
    const wrapper = mountAgent()

    await wrapper.get('[data-testid="agent-shape-option"][aria-label="切换为圆团"]').trigger('click')

    const eyes = wrapper.findAll('.agent-avatar__eye')
    expect(eyes).toHaveLength(2)
    expect(eyes[0].attributes('transform')).toBeUndefined()
    expect(eyes[1].attributes('transform')).toBeUndefined()
    expect(eyes[0].element.parentElement?.getAttribute('transform')).toBe('translate(114.2705 114.228)')
  })

  it('keeps the hero focused on the agent without a decorative outer contour', () => {
    const wrapper = mountAgent()

    expect(wrapper.find('.agent-stage__rings').exists()).toBe(false)
    expect(wrapper.find('.agent-avatar__rim').exists()).toBe(false)
    expect(wrapper.find('.agent-avatar__edge').exists()).toBe(false)
  })

  it('reports unsupported speech recognition without breaking the visual control', async () => {
    const wrapper = mountAgent()

    await wrapper.get('[data-testid="agent-voice-toggle"]').trigger('click')

    expect(wrapper.text()).toContain('当前浏览器不支持语音识别')
  })

  it('keeps the control dock collapsed until the agent is clicked', async () => {
    const wrapper = mountAgent()

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
    const wrapper = mountAgent()

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

  it('keeps the landing surface when a signed-out voice conversation needs authentication', async () => {
    localStorage.removeItem('token')
    const recognition = {
      lang: '', continuous: false, interimResults: false,
      onresult: null as ((event: unknown) => void) | null,
      onerror: null as (() => void) | null,
      onend: null as (() => void) | null,
      start: vi.fn(), stop: vi.fn()
    }
    Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: vi.fn(() => recognition) })
    const wrapper = mountAgent()

    await wrapper.get('[data-testid="agent-voice-toggle"]').trigger('click')
    recognition.onresult?.({ results: [[{ transcript: 'Justin' }]], resultIndex: 0 })
    recognition.onresult?.({ results: [[{ transcript: '帮我分析一下这个任务' }]], resultIndex: 0 })
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('login-requested')).toBeUndefined()
    expect(wrapper.get('[data-testid="agent-conversation"]').text()).toContain('请先登录')
    wrapper.unmount()
    Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: undefined })
  })

  it('emits natural-language speech after Justin wakes the agent', async () => {
    localStorage.setItem('token', 'test-token')
    const recognition = {
      lang: '', continuous: false, interimResults: false,
      onresult: null as ((event: unknown) => void) | null,
      onerror: null as (() => void) | null,
      onend: null as (() => void) | null,
      start: vi.fn(), stop: vi.fn()
    }
    Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: vi.fn(() => recognition) })
    const wrapper = mountAgent()

    await wrapper.get('[data-testid="agent-voice-toggle"]').trigger('click')
    recognition.onresult?.({ results: [[{ transcript: 'Justin' }]], resultIndex: 0 })
    recognition.onresult?.({ results: [[{ transcript: '帮我分析一下这个任务' }]], resultIndex: 0 })
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('voice-message')?.[0]).toEqual(['帮我分析一下这个任务'])
    wrapper.unmount()
    localStorage.removeItem('token')
    Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: undefined })
  })

  it('renders the authenticated backend stream in the Justin conversation bubble', async () => {
    localStorage.setItem('token', 'test-token')
    const recognition = {
      lang: '', continuous: false, interimResults: false,
      onresult: null as ((event: unknown) => void) | null,
      onerror: null as (() => void) | null,
      onend: null as (() => void) | null,
      start: vi.fn(), stop: vi.fn()
    }
    Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: vi.fn(() => recognition) })
    const chunks = [
      `data: ${JSON.stringify({ event: 'content_delta', data: { delta: '这是后端回复' } })}\n`,
      `data: ${JSON.stringify({ event: 'done', data: { contextId: 'ctx-justin' } })}\n`
    ]
    let chunkIndex = 0
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      body: {
        getReader: () => ({
          read: async () => chunkIndex < chunks.length
            ? { done: false, value: new TextEncoder().encode(chunks[chunkIndex++]) }
            : { done: true, value: undefined }
        })
      }
    })))
    const wrapper = mountAgent()

    await wrapper.get('[data-testid="agent-voice-toggle"]').trigger('click')
    recognition.onresult?.({ results: [[{ transcript: 'Justin 帮我分析一下' }]], resultIndex: 0 })
    await flushPromises()

    expect(wrapper.get('[data-testid="agent-conversation"]').text()).toContain('这是后端回复')
    wrapper.unmount()
    vi.unstubAllGlobals()
    localStorage.removeItem('token')
    Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: undefined })
  })
})
