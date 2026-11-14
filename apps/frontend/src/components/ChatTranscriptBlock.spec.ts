import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ChatTranscriptBlock from './ChatTranscriptBlock.vue'
import type { TranscriptBlock } from '../../../backend/src/shared/chat-stream/index.mjs'

const reasoning = (state = 'streaming', text = 'Public progress'): TranscriptBlock => ({
  id: 'reasoning', kind: 'reasoning', state, text
})
const render = (block = reasoning()) => mount(ChatTranscriptBlock, {
  props: { block }, global: { stubs: { ConversationWorkFeed: true } }
})

describe('streaming progress visibility', () => {
  it('shows active progress before any answer text arrives and keeps it readable on completion', async () => {
    const wrapper = render()
    expect(wrapper.get('details').element.open).toBe(true)
    expect(wrapper.get('pre').text()).toBe('Public progress')
    await wrapper.setProps({ block: reasoning('completed') })
    expect(wrapper.get('details').element.open).toBe(true)
    wrapper.unmount()
  })

  it('keeps historical progress collapsed and respects a manual collapse during streaming', async () => {
    const history = render(reasoning('completed'))
    expect(history.get('details').element.open).toBe(false)
    history.unmount()
    const wrapper = render()
    const details = wrapper.get('details')
    details.element.open = false
    await details.trigger('toggle')
    await wrapper.setProps({ block: reasoning('streaming', 'New progress') })
    expect(details.element.open).toBe(false)
    await wrapper.setProps({ block: reasoning('completed', 'New progress') })
    expect(details.element.open).toBe(false)
    wrapper.unmount()
  })

  it('follows live output until the user scrolls back to read earlier progress', async () => {
    const wrapper = render()
    const content = wrapper.get('pre')
    Object.defineProperty(content.element, 'scrollHeight', { value: 900, configurable: true })
    Object.defineProperty(content.element, 'clientHeight', { value: 100, configurable: true })
    await wrapper.setProps({ block: reasoning('streaming', 'Latest progress') })
    expect(content.element.scrollTop).toBe(900)
    await content.trigger('wheel')
    content.element.scrollTop = 0
    await content.trigger('scroll')
    await wrapper.setProps({ block: reasoning('streaming', 'More progress') })
    expect(content.element.scrollTop).toBe(0)
    wrapper.unmount()
  })
})
