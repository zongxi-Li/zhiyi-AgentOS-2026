import { beforeEach, describe, expect, it } from 'vitest'
import {
  applyProviderPreset,
  capabilityFromPayload,
  defaultReasoningEffortFromCapability,
  getDefaultModelSettings,
  isEffortKindOption,
  loadModelSettings,
  normalizeModelReasoning,
  reasoningOptionsFromCapability,
  saveModelSettings,
  toModelRequestSettings
} from './modelSettings'

describe('model settings provider selection', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('keeps DeepSeek and GLM connection drafts separate when switching', () => {
    // 预设不再内置模型清单（目录来自服务端或用户填写），只承载连接信息。
    let settings = applyProviderPreset(getDefaultModelSettings(), 'deepseek')
    settings.apiKey = 'deepseek-key'
    settings.models = ['deepseek-flash']
    settings.selectedModel = 'deepseek-flash'

    settings = applyProviderPreset(settings, 'glm')
    expect(settings.apiKey).toBe('')
    expect(settings.baseUrl).toContain('bigmodel.cn')
    expect(settings.selectedModel).toBe('')

    settings.apiKey = 'glm-key'
    settings.models = ['glm-5.3-flash']
    settings.selectedModel = 'glm-5.3-flash'
    settings.reasoningEffort = 'high'

    settings = applyProviderPreset(settings, 'deepseek')
    expect(settings.apiKey).toBe('deepseek-key')
    expect(settings.selectedModel).toBe('deepseek-flash')

    settings = applyProviderPreset(settings, 'glm')
    expect(settings.apiKey).toBe('glm-key')
    expect(settings.selectedModel).toBe('glm-5.3-flash')
    expect(settings.reasoningEffort).toBe('high')
  })

  it('persists the selected provider and sends direct connection fields', () => {
    let settings = applyProviderPreset(getDefaultModelSettings(), 'glm')
    settings.apiKey = 'glm-key'
    settings.models = ['glm-5.3-flash']
    settings.selectedModel = 'glm-5.3-flash'
    settings.reasoningEffort = 'max'
    saveModelSettings(settings)

    const loaded = loadModelSettings()
    expect(loaded.provider).toBe('glm')
    expect(toModelRequestSettings(loaded)).toMatchObject({
      model: 'glm-5.3-flash',
      baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
      apiKey: 'glm-key',
      reasoningEffort: 'max'
    })
  })

  it('exposes DeepSeek off plus low/high/max reasoning options', () => {
    const capability = capabilityFromPayload({
      thinkingModes: ['disabled', 'standard', 'deep'],
      alwaysThinking: false,
      supportsReasoningEffort: true,
      reasoningEfforts: ['low', 'high', 'max'],
      defaultReasoningEffort: 'high'
    })
    const options = reasoningOptionsFromCapability(capability)

    expect(isEffortKindOption(options)).toBe(true)
    expect(options.map(option => option.value)).toEqual(['disabled', 'low', 'high', 'max'])
    expect(options.map(option => option.kind)).toEqual(['thinking', 'effort', 'effort', 'effort'])
    expect(defaultReasoningEffortFromCapability(capability, options)).toBe('high')
  })

  it('retains the server catalog and selected model across reads and sends', () => {
    const settings = getDefaultModelSettings()
    settings.models = ['glm-5.3-flash', 'glm-5.3']
    settings.selectedModel = 'glm-5.3'
    saveModelSettings(settings)

    for (let read = 0; read < 2; read++) {
      const loaded = loadModelSettings()
      expect(loaded.models).toEqual(settings.models)
      expect(loaded.selectedModel).toBe('glm-5.3')
      expect(toModelRequestSettings(loaded)).toMatchObject({ model: 'glm-5.3' })
      expect(toModelRequestSettings(loaded)).not.toHaveProperty('apiKey')
    }
  })

  it('discards the legacy system placeholder while retaining real models', () => {
    saveModelSettings({ ...getDefaultModelSettings(), models: ['系统默认', 'glm-5.3-flash'], selectedModel: '系统默认' })
    const loaded = loadModelSettings()
    expect(loaded.models).toEqual(['glm-5.3-flash'])
    expect(toModelRequestSettings(loaded).model).toBe('glm-5.3-flash')
  })

  it('keeps newly declared provider efforts dynamic', () => {
    const capability = capabilityFromPayload({
      thinkingModes: ['disabled', 'standard', 'deep'],
      alwaysThinking: false,
      supportsReasoningEffort: true,
      reasoningEfforts: ['low', 'high', 'max', 'ultra'],
      defaultReasoningEffort: 'ultra'
    })
    const options = reasoningOptionsFromCapability(capability)

    expect(options.map(option => option.value)).toEqual(['disabled', 'low', 'high', 'max', 'ultra'])
    expect(defaultReasoningEffortFromCapability(capability, options)).toBe('ultra')
  })

  const glmCapability = capabilityFromPayload({ thinkingModes: ['standard', 'deep'],
    alwaysThinking: true, reasoningEfforts: ['low', 'high', 'max'], supportsReasoningEffort: true })!

  it.each([['disabled', 'low'], ['standard', 'low'], ['deep', 'max']] as const)(
    'resolves legacy %s to the same GLM effort used by the backend', (thinkingMode, effort) => {
      const normalized = normalizeModelReasoning({ ...getDefaultModelSettings(), thinkingMode }, glmCapability)
      saveModelSettings(normalized)
      expect(toModelRequestSettings(loadModelSettings()).reasoningEffort).toBe(effort)
    })

  it.each(['low', 'high', 'max'])('retains explicit %s across save and reload', effort => {
    const normalized = normalizeModelReasoning({ ...getDefaultModelSettings(), reasoningEffort: effort }, glmCapability)
    saveModelSettings(normalized)
    expect(normalizeModelReasoning(loadModelSettings(), glmCapability).reasoningEffort).toBe(effort)
    expect(toModelRequestSettings(loadModelSettings()).reasoningEffort).toBe(effort)
  })

  it('preserves unknown exact efforts until current-model capabilities arrive', () => {
    const settings = { ...getDefaultModelSettings(), reasoningEffort: 'ultra' }
    expect(normalizeModelReasoning(settings, null)).toBe(settings)
  })

  it('preserves a supported off state and removes a stale effort on a non-effort model', () => {
    const switchable = { ...glmCapability, alwaysThinking: false, thinkingModes: ['disabled', 'standard', 'deep'] as const }
    const off = normalizeModelReasoning(getDefaultModelSettings(), { ...switchable,
      thinkingModes: [...switchable.thinkingModes] })
    expect(off.thinkingMode).toBe('disabled')
    expect(off.reasoningEffort).toBeUndefined()
    const plain = { ...glmCapability, alwaysThinking: false, supportsReasoningEffort: false, reasoningEfforts: [] }
    expect(normalizeModelReasoning({ ...getDefaultModelSettings(), thinkingMode: 'deep', reasoningEffort: 'max' }, plain))
      .toMatchObject({ thinkingMode: 'deep', reasoningEffort: undefined })
  })
})
