import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import CompanionHost from './CompanionHost.vue'
import { CUSTOMIZATION_STORAGE_KEY, DEFAULT_CUSTOMIZATION } from '@/features/companion/customization'
import type { RecognitionLike, RecognitionEventLike } from '@/features/companion/voice'

let recognition: RecognitionLike | null = null
let tray: ((action: string) => void) | null = null
class Recognition implements RecognitionLike {
  lang = ''; continuous = false; interimResults = false
  onresult: ((event: RecognitionEventLike) => void) | null = null
  onerror = null
  onend: (() => void) | null = null
  constructor() { recognition = this }
  start() {}
  stop() { this.onend?.() }
  abort() {}
}
const query = (id: string) => document.querySelector(`[data-testid="${id}"]`) as HTMLElement
const openDraft = async () => {
  const wrapper = mount(CompanionHost)
  await flushPromises()
  query('companion-avatar').click()
  await flushPromises()
  query('companion-settings-open').click()
  await flushPromises()
  query('companion-diy-open').click()
  await flushPromises()
  const name = query('companion-diy-name') as HTMLInputElement
  name.value = '未保存草稿'
  name.dispatchEvent(new Event('input'))
  await flushPromises()
  expect(query('companion-name').textContent).toBe('未保存草稿')
  return wrapper
}

beforeEach(() => {
  localStorage.clear()
  localStorage.setItem('companion.wake.v1', '0')
  vi.stubGlobal('SpeechRecognition', Recognition)
  Object.assign(window, { kinlinDesktop: { companion: { publishState: vi.fn(), notifyIfBackground: vi.fn(), onTrayAction: (callback: typeof tray) => { tray = callback; return () => { tray = null } } } } })
})
afterEach(() => { document.body.innerHTML = ''; localStorage.clear(); vi.unstubAllGlobals(); delete (window as any).kinlinDesktop; recognition = null; tray = null })

describe('Companion workshop exit semantics', () => {
  it('cancels preview when the panel collapses', async () => {
    const wrapper = await openDraft()
    query('companion-collapse').click()
    await flushPromises()
    query('companion-avatar').click()
    await flushPromises()
    expect(query('companion-customizer')).toBeNull()
    expect(query('companion-name').textContent).toBe(DEFAULT_CUSTOMIZATION.name)
    expect(localStorage.getItem(CUSTOMIZATION_STORAGE_KEY)).toBeNull()
    wrapper.unmount()
  })

  it('restores the saved appearance before tray listening can persist a mute command', async () => {
    const wrapper = await openDraft()
    tray?.('voice')
    await flushPromises()
    recognition?.onresult?.({ resultIndex: 0, results: [{ 0: { transcript: '静音' }, isFinal: true }] })
    await flushPromises()
    const saved = JSON.parse(localStorage.getItem(CUSTOMIZATION_STORAGE_KEY)!)
    expect(saved.name).toBe(DEFAULT_CUSTOMIZATION.name)
    expect(saved.voice.muted).toBe(true)
    expect(query('companion-customizer')).toBeNull()
    wrapper.unmount()
  })
})
