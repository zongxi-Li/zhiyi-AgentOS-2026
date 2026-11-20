import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CompanionDialogue from './CompanionDialogue.vue'

const props = {
  messages: [{ id: '1', role: 'companion' as const, content: '这是静音时也能读到的回复', createdAt: 0 }],
  pending: false, card: null, phase: 'idle' as const, hint: '点一下说话'
}

describe('Companion dialogue output and fallback', () => {
  it('shows final replies independently of synthesis and announces processing', async () => {
    const wrapper = mount(CompanionDialogue, { props })
    expect(wrapper.get('[data-testid="companion-messages"]').text()).toContain('静音时也能读到')
    await wrapper.setProps({ pending: true })
    expect(wrapper.get('[role="status"]').text()).toContain('回复中')
  })

  it('keeps typing optional and submits through the same utterance action', async () => {
    const wrapper = mount(CompanionDialogue, { props })
    expect(wrapper.find('input').exists()).toBe(false)
    await wrapper.get('[data-testid="companion-text-toggle"]').trigger('click')
    await wrapper.get('input').setValue('  查看进度  ')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('submit')).toEqual([['查看进度']])
    expect((wrapper.get('input').element as HTMLInputElement).value).toBe('')
    await wrapper.setProps({ pending: true })
    await wrapper.get('input').setValue('忙时不会再提交')
    await wrapper.get('form').trigger('submit')
    expect(wrapper.emitted('submit')).toHaveLength(1)
  })

  it('scrolls initial history and new replies after the bounded history reaches sixty messages', async () => {
    const messages = Array.from({ length: 60 }, (_, i) => ({ ...props.messages[0], id: String(i) }))
    const wrapper = mount(CompanionDialogue, { props: { ...props, messages } })
    const log = wrapper.get('[data-testid="companion-messages"]').element
    Object.defineProperty(log, 'scrollHeight', { configurable: true, value: 900 })
    await flushPromises()
    expect(log.scrollTop).toBe(900)
    log.scrollTop = 0
    await wrapper.setProps({ messages: [...messages.slice(1), { ...messages[0], id: 'new-reply' }] })
    await flushPromises()
    expect(log.scrollTop).toBe(900)
    wrapper.unmount()
  })
})
