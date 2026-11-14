import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ModelRuntimeControls from './ModelRuntimeControls.vue'
import { getDefaultModelSettings, loadModelSettings, saveModelSettings, toModelRequestSettings } from '@/config/modelSettings'

vi.mock('@/platform/api', () => ({ localFetch: (...args: any[]) => fetch(...args as [any]), apiUrl: (p: string) => p }))
vi.mock('@/platform', () => ({ apiUrl: (p: string) => p }))

const glm = { thinkingModes: ['standard', 'deep'], alwaysThinking: true,
  supportsReasoningEffort: true, reasoningEfforts: ['low', 'high', 'max'] }
const deepseek = { thinkingModes: ['disabled', 'standard', 'deep'], alwaysThinking: false,
  supportsReasoningEffort: true, reasoningEfforts: ['low', 'high', 'max'], defaultReasoningEffort: 'high' }
const mounts: ReturnType<typeof mount>[] = []
const render = () => {
  const wrapper = mount(ModelRuntimeControls, { props: { composer: true }, global: { stubs: {
    'el-popover': { template: '<div><slot name="reference"/><slot/></div>' },
    'el-icon': { template: '<span><slot/></span>' },
  } } })
  mounts.push(wrapper)
  return wrapper
}
const seed = () => saveModelSettings({ ...getDefaultModelSettings(), provider: 'custom',
  baseUrl: 'https://example.test/v1', models: ['glm-5.3-flash', 'deepseek-flash'], selectedModel: 'glm-5.3-flash' })
const json = (value: unknown) => ({ ok: true, json: async () => value })

beforeEach(() => {
  localStorage.clear()
  seed()
  vi.stubGlobal('fetch', vi.fn(async () => json(glm)))
})
afterEach(() => {
  for (const wrapper of mounts.splice(0)) wrapper.unmount()
  vi.unstubAllGlobals()
})

describe('reasoning control uses the saved request value', () => {
  it('shows and persists low for legacy disabled GLM instead of a display-only max', async () => {
    const wrapper = render()
    await flushPromises()
    expect(wrapper.find('.composer-model-trigger').text()).toContain('轻度')
    expect(toModelRequestSettings(loadModelSettings())).toMatchObject({ thinkingMode: 'standard', reasoningEffort: 'low' })
  })

  it('sends exactly the selected radio value and restores it after remount', async () => {
    const wrapper = render()
    await flushPromises()
    for (const [index, effort] of ['low', 'high', 'max'].entries()) {
      await wrapper.findAll('[role="radio"]')[index].trigger('click')
      expect(toModelRequestSettings(loadModelSettings()).reasoningEffort).toBe(effort)
    }
    wrapper.unmount()
    const restored = render()
    await flushPromises()
    expect(restored.find('.composer-model-trigger').attributes('title')).toContain('极致')
    expect(toModelRequestSettings(loadModelSettings()).reasoningEffort).toBe('max')
  })

  it('ignores a late capability response for the previous model and retains a real off state', async () => {
    let finishOld!: (value: any) => void
    vi.stubGlobal('fetch', vi.fn((url: string) => url.includes('glm-5.3-flash')
      ? new Promise(resolve => { finishOld = resolve }) : Promise.resolve(json(deepseek))))
    const wrapper = render()
    expect(wrapper.find('.composer-model-trigger').text()).toContain('待确认')
    await wrapper.findAll('.model-menu__model')[1].trigger('click')
    await flushPromises()
    finishOld(json(glm))
    await flushPromises()
    expect(loadModelSettings()).toMatchObject({ selectedModel: 'deepseek-flash', thinkingMode: 'disabled', reasoningEffort: undefined })
    expect(wrapper.find('.composer-model-trigger').text()).toContain('关')
    // Selecting an effort and then off must be one atomic state update.
    await wrapper.findAll('[role="radio"]')[3].trigger('click')
    await wrapper.findAll('[role="radio"]')[0].trigger('click')
    expect(toModelRequestSettings(loadModelSettings())).toMatchObject({ thinkingMode: 'disabled' })
    expect(toModelRequestSettings(loadModelSettings()).reasoningEffort).toBeUndefined()
  })
})
