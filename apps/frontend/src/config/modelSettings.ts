export type ModelProviderId = 'system' | 'qwen' | 'deepseek' | 'glm' | 'openai' | 'custom'
export type ThinkingMode = 'disabled' | 'standard' | 'deep'
export const GLM_REASONING_EFFORTS = ['low', 'high', 'max'] as const
export type GlmReasoningEffort = typeof GLM_REASONING_EFFORTS[number]

export interface ModelProviderPreset {
  id: ModelProviderId
  name: string
  description: string
  baseUrl: string
  models: string[]
}

export interface ModelProviderConnection {
  apiKey: string
  baseUrl: string
  models: string[]
  selectedModel: string
  thinkingMode?: ThinkingMode
  reasoningEffort?: GlmReasoningEffort
}

export interface ModelSettings {
  provider: ModelProviderId
  apiKey: string
  baseUrl: string
  models: string[]
  selectedModel: string
  thinkingMode: ThinkingMode
  reasoningEffort?: GlmReasoningEffort
  providerConnections?: Partial<Record<Exclude<ModelProviderId, 'system'>, ModelProviderConnection>>
}

export const MODEL_SETTINGS_KEY = 'kinlin.model_settings'
export const MODEL_SETTINGS_EVENT = 'kinlin-model-settings-change'
export const SYSTEM_FALLBACK_MODELS = ['deepseek-v4-flash', 'deepseek-v4-pro']

export const modelProviderPresets: ModelProviderPreset[] = [
  {
    id: 'system',
    name: '系统默认',
    description: '使用服务端环境变量中已配置的模型',
    baseUrl: '',
    models: [...SYSTEM_FALLBACK_MODELS]
  },
  {
    id: 'qwen',
    name: '通义千问',
    description: '阿里云百炼 OpenAI 兼容接口',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    models: ['qwen3.7-plus', 'qwen3.7-max', 'qwen3.6-flash']
  },
  {
    id: 'deepseek',
    name: 'DeepSeek',
    description: 'DeepSeek 官方 OpenAI 兼容接口',
    baseUrl: 'https://api.deepseek.com/v1',
    models: ['deepseek-v4-flash', 'deepseek-v4-pro']
  },
  {
    id: 'glm',
    name: 'GLM / 智谱',
    description: '智谱 AI 官方 OpenAI 兼容接口',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    models: ['glm-5.3-flash']
  },
  {
    id: 'openai',
    name: 'OpenAI 兼容',
    description: 'OpenAI 官方或兼容 Chat Completions 的服务',
    baseUrl: 'https://api.openai.com/v1',
    models: ['gpt-5.2', 'gpt-5-mini']
  },
  {
    id: 'custom',
    name: '自定义',
    description: '连接自托管或其他 OpenAI 兼容服务',
    baseUrl: '',
    models: []
  }
]

export const thinkingOptions: Array<{ value: ThinkingMode; label: string; shortLabel: string }> = [
  { value: 'disabled', label: '关闭思考', shortLabel: '关' },
  { value: 'standard', label: '标准思考', shortLabel: '标准' },
  { value: 'deep', label: '深度思考', shortLabel: '深度' }
]

export const glmReasoningOptions: Array<{ value: GlmReasoningEffort; label: string; shortLabel: string }> = [
  { value: 'low', label: 'low（较低思考强度）', shortLabel: 'low' },
  { value: 'high', label: 'high（较高思考强度）', shortLabel: 'high' },
  { value: 'max', label: 'max（最高思考强度）', shortLabel: 'max' }
]

export function isGlmAlwaysThinkingModel(model: string): boolean {
  return model.trim().toLowerCase() === 'glm-5.3-flash'
}

function migrateReasoningEffort(value: unknown): GlmReasoningEffort {
  return GLM_REASONING_EFFORTS.includes(value as GlmReasoningEffort)
    ? value as GlmReasoningEffort
    : 'max'
}

function thinkingModeForGlmEffort(effort: GlmReasoningEffort): ThinkingMode {
  return effort === 'low' ? 'standard' : 'deep'
}

const LEGACY_MODEL_ALIASES: Record<string, string> = {
  'deepseek-chat': 'deepseek-v4-flash',
  'deepseek-reasoner': 'deepseek-v4-flash'
}

function migrateModel(model: string): string {
  return LEGACY_MODEL_ALIASES[model] || model
}

function migrateThinkingMode(value: unknown, legacyModel = ''): ThinkingMode {
  if (value === 'disabled' || value === 'standard' || value === 'deep') return value
  if (value === 'off') return 'disabled'
  if (value === 'low' || value === 'medium') return 'standard'
  if (value === 'high' || value === 'max' || value === 'xhigh') return 'deep'
  if (legacyModel === 'deepseek-reasoner') return 'standard'
  return 'disabled'
}

export function getDefaultModelSettings(): ModelSettings {
  return {
    provider: 'system',
    apiKey: '',
    baseUrl: '',
    models: [...SYSTEM_FALLBACK_MODELS],
    selectedModel: SYSTEM_FALLBACK_MODELS[0],
    thinkingMode: 'disabled'
  }
}

export function loadModelSettings(): ModelSettings {
  const fallback = getDefaultModelSettings()
  try {
    const raw = localStorage.getItem(MODEL_SETTINGS_KEY)
    if (!raw) return fallback
    const parsed = JSON.parse(raw) as Partial<ModelSettings> & { reasoningEffort?: unknown }
    const provider = modelProviderPresets.some(item => item.id === parsed.provider)
      ? parsed.provider as ModelProviderId
      : fallback.provider
    const storedModels = Array.isArray(parsed.models)
      ? parsed.models
        .filter(model => typeof model === 'string' && model.trim())
        .map(model => migrateModel(model.trim()))
      : fallback.models
    const models = provider === 'system' && (
      storedModels.length === 0 || storedModels.includes('系统默认')
    )
      ? [...SYSTEM_FALLBACK_MODELS]
      : [...new Set(storedModels)]
    const legacySelectedModel = parsed.selectedModel?.trim() || ''
    const storedSelectedModel = migrateModel(legacySelectedModel)
    const selectedModel = models.includes(storedSelectedModel)
      ? storedSelectedModel
      : models[0] || fallback.selectedModel

    const reasoningEffort = isGlmAlwaysThinkingModel(selectedModel)
      ? migrateReasoningEffort(parsed.reasoningEffort)
      : undefined
    return {
      ...fallback,
      ...parsed,
      provider,
      models: models.length ? models : fallback.models,
      selectedModel,
      thinkingMode: reasoningEffort
        ? thinkingModeForGlmEffort(reasoningEffort)
        : migrateThinkingMode(parsed.thinkingMode ?? parsed.reasoningEffort, legacySelectedModel),
      reasoningEffort
    }
  } catch {
    return fallback
  }
}

export function saveModelSettings(settings: ModelSettings): void {
  const selectedModel = settings.selectedModel.trim()
  const models = [...new Set([
    ...settings.models.map(model => model.trim()).filter(Boolean),
    ...(selectedModel ? [selectedModel] : [])
  ])]
  const providerConnections = { ...(settings.providerConnections || {}) }
  const normalizedReasoningEffort = isGlmAlwaysThinkingModel(selectedModel)
    ? migrateReasoningEffort(settings.reasoningEffort)
    : undefined
  const normalizedThinkingMode = normalizedReasoningEffort
    ? thinkingModeForGlmEffort(normalizedReasoningEffort)
    : settings.thinkingMode
  if (settings.provider !== 'system') {
    providerConnections[settings.provider] = {
      apiKey: settings.apiKey.trim(),
      baseUrl: settings.baseUrl.trim().replace(/\/$/, ''),
      models,
      selectedModel,
      thinkingMode: normalizedThinkingMode,
      ...(isGlmAlwaysThinkingModel(selectedModel)
        ? { reasoningEffort: normalizedReasoningEffort }
        : {})
    }
  }
  const normalized: ModelSettings = {
    ...settings,
    apiKey: settings.apiKey.trim(),
    baseUrl: settings.baseUrl.trim().replace(/\/$/, ''),
    models,
    selectedModel,
    thinkingMode: normalizedThinkingMode,
    reasoningEffort: normalizedReasoningEffort,
    providerConnections
  }
  localStorage.setItem(MODEL_SETTINGS_KEY, JSON.stringify(normalized))
  window.dispatchEvent(new CustomEvent(MODEL_SETTINGS_EVENT, { detail: normalized }))
}

export function applyProviderPreset(settings: ModelSettings, provider: ModelProviderId): ModelSettings {
  const preset = modelProviderPresets.find(item => item.id === provider) || modelProviderPresets[0]
  const providerConnections = { ...(settings.providerConnections || {}) }
  if (settings.provider !== 'system') {
    providerConnections[settings.provider] = {
      apiKey: settings.apiKey.trim(),
      baseUrl: settings.baseUrl.trim().replace(/\/$/, ''),
      models: [...settings.models],
      selectedModel: settings.selectedModel.trim(),
      thinkingMode: settings.thinkingMode,
      ...(isGlmAlwaysThinkingModel(settings.selectedModel)
        ? { reasoningEffort: migrateReasoningEffort(settings.reasoningEffort) }
        : {})
    }
  }
  const savedConnection = provider === 'system' ? undefined : providerConnections[provider]
  const models = savedConnection?.models?.length ? [...savedConnection.models] : [...preset.models]
  const selectedModel = savedConnection?.selectedModel && models.includes(savedConnection.selectedModel)
    ? savedConnection.selectedModel
    : models[0] || ''
  const reasoningEffort = isGlmAlwaysThinkingModel(selectedModel)
    ? migrateReasoningEffort(savedConnection?.reasoningEffort || settings.reasoningEffort)
    : undefined
  const thinkingMode = reasoningEffort
    ? thinkingModeForGlmEffort(reasoningEffort)
    : savedConnection?.thinkingMode || settings.thinkingMode
  return {
    ...settings,
    provider,
    baseUrl: savedConnection?.baseUrl || preset.baseUrl,
    models,
    selectedModel,
    thinkingMode,
    apiKey: savedConnection?.apiKey || '',
    reasoningEffort,
    providerConnections
  }
}

export function toModelRequestSettings(settings: ModelSettings) {
  if (settings.provider === 'system') {
    return {
      model: settings.selectedModel === '系统默认' ? undefined : settings.selectedModel,
      thinkingMode: settings.thinkingMode,
      ...(isGlmAlwaysThinkingModel(settings.selectedModel)
        ? { reasoningEffort: migrateReasoningEffort(settings.reasoningEffort) }
        : {})
    }
  }
  return {
    model: settings.selectedModel,
    baseUrl: settings.baseUrl,
    apiKey: settings.apiKey,
    thinkingMode: settings.thinkingMode,
    ...(isGlmAlwaysThinkingModel(settings.selectedModel)
      ? { reasoningEffort: migrateReasoningEffort(settings.reasoningEffort) }
      : {})
  }
}
