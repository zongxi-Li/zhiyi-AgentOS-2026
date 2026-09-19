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
})
