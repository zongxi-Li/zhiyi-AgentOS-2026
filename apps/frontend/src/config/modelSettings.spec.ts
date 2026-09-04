import { beforeEach, describe, expect, it } from 'vitest'
import {
  applyProviderPreset,
  getDefaultModelSettings,
  loadModelSettings,
  saveModelSettings,
  toModelRequestSettings
} from './modelSettings'

describe('model settings provider selection', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('keeps DeepSeek and GLM connection drafts separate when switching', () => {
    let settings = applyProviderPreset(getDefaultModelSettings(), 'deepseek')
    settings.apiKey = 'deepseek-key'

    settings = applyProviderPreset(settings, 'glm')
    expect(settings.apiKey).toBe('')
    expect(settings.baseUrl).toContain('bigmodel.cn')
    expect(settings.selectedModel).toBe('glm-5.3-flash')
    expect(settings.reasoningEffort).toBe('max')

    settings.apiKey = 'glm-key'
    settings.reasoningEffort = 'high'
    settings = applyProviderPreset(settings, 'deepseek')
    expect(settings.apiKey).toBe('deepseek-key')
    expect(settings.selectedModel).toBe('deepseek-v4-flash')

    settings = applyProviderPreset(settings, 'glm')
    expect(settings.apiKey).toBe('glm-key')
    expect(settings.selectedModel).toBe('glm-5.3-flash')
    expect(settings.reasoningEffort).toBe('high')
  })

  it('persists the selected provider and sends direct connection fields', () => {
    let settings = applyProviderPreset(getDefaultModelSettings(), 'glm')
    settings.apiKey = 'glm-key'
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
})
