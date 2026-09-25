import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'

const setupVoice = async (chatStoreFactory: () => unknown) => {
  vi.resetModules()
  vi.doMock('@/stores/chat', chatStoreFactory)
  const { default: GlassConstellation } = await import('./GlassConstellation.vue')
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
  Object.defineProperty(window, 'SpeechRecognition', {
    configurable: true,
    value: vi.fn(() => recognition)
  })
  localStorage.setItem('token', 'test-token')
  const wrapper = mount(GlassConstellation, { global: { plugins: [createPinia()] } })

  await wrapper.get('[data-testid="agent-voice-toggle"]').trigger('click')
  recognition.onresult?.({
    results: [[{ transcript: 'Justin 帮我分析一下' }]],
    resultIndex: 0
  })
  await flushPromises()

  return { wrapper, recognition }
}

afterEach(() => {
  localStorage.clear()
  Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: undefined })
  vi.doUnmock('@/stores/chat')
  vi.resetModules()
})

describe('GlassConstellation lazy chat store lifecycle', () => {
  it('does not instantiate the chat store when unmounted during its import', async () => {
    let resolveStoreModule: ((module: unknown) => void) | undefined
    const useChatStore = vi.fn(() => ({
      messages: [],
      sendMessageStream: vi.fn(),
      cancelMessageStream: vi.fn()
    }))
    const { wrapper } = await setupVoice(() => new Promise(resolve => {
      resolveStoreModule = resolve
    }))

    expect(resolveStoreModule).toBeDefined()
    wrapper.unmount()
    resolveStoreModule?.({ useChatStore })
    await flushPromises()

    expect(useChatStore).not.toHaveBeenCalled()
  })

  it('cancels an active stream through the same lazily loaded store', async () => {
    const store = {
      messages: [],
      sendMessageStream: vi.fn(() => new Promise<void>(() => {})),
      cancelMessageStream: vi.fn()
    }
    const useChatStore = vi.fn(() => store)
    const { wrapper } = await setupVoice(async () => ({ useChatStore }))

    expect(useChatStore).toHaveBeenCalledOnce()
    expect(store.sendMessageStream).toHaveBeenCalledOnce()

    wrapper.unmount()

    expect(store.cancelMessageStream).toHaveBeenCalledOnce()
  })
})
