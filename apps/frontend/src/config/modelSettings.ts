import { apiUrl } from '@/platform'

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

// 模型清单不在此硬编码：system 供应商由 GET /ai/chat/models 动态下发，
// 其余供应商由用户在设置页自行填写（官方上新/改名零前端改动）。
export const modelProviderPresets: ModelProviderPreset[] = [
  {
    id: 'system',
    name: '系统默认',
    description: '使用服务端当前激活供应商的模型目录',
    baseUrl: '',
    models: []
  },
  {
    id: 'qwen',
    name: '通义千问',
    description: '阿里云百炼 OpenAI 兼容接口',
    baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    models: []
  },
  {
    id: 'deepseek',
    name: 'DeepSeek',
    description: 'DeepSeek 官方 OpenAI 兼容接口',
    baseUrl: 'https://api.deepseek.com/v1',
    models: []
  },
  {
    id: 'glm',
    name: 'GLM / 智谱',
    description: '智谱 AI 官方 OpenAI 兼容接口',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    models: []
  },
  {
    id: 'openai',
    name: 'OpenAI 兼容',
    description: 'OpenAI 官方或兼容 Chat Completions 的服务',
    baseUrl: 'https://api.openai.com/v1',
    models: []
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

// 已知档位的展示文案；未知档位直接展示原始值。
const EFFORT_LABELS: Record<string, string> = {
  low: 'low（较低思考强度）',
  high: 'high（较高思考强度）',
  max: 'max（最高思考强度）'
}

// ---- 服务端能力元数据驱动（GET /ai/chat/models 与 /ai/chat/model-capabilities） ----

export interface ModelCapability {
  thinkingModes: ThinkingMode[]
  alwaysThinking: boolean
  supportsReasoningEffort: boolean
  reasoningEfforts: string[]
  contextWindow?: number | null
}

export interface ReasoningOption {
  value: ThinkingMode | GlmReasoningEffort
  label: string
  shortLabel: string
  kind: 'effort' | 'thinking'
}

const ALL_THINKING_MODES: ThinkingMode[] = ['disabled', 'standard', 'deep']

export function capabilityFromPayload(payload: unknown): ModelCapability | null {
  if (!payload || typeof payload !== 'object') return null
  const raw = payload as Record<string, unknown>
  const modes = Array.isArray(raw.thinkingModes)
    ? raw.thinkingModes.filter((mode): mode is ThinkingMode => ALL_THINKING_MODES.includes(mode as ThinkingMode))
    : []
  const efforts = Array.isArray(raw.reasoningEfforts)
    ? raw.reasoningEfforts.filter((effort): effort is string => typeof effort === 'string' && Boolean(effort.trim()))
    : []
  if (!modes.length && !efforts.length) return null
  return {
    thinkingModes: modes,
    alwaysThinking: raw.alwaysThinking === true,
    supportsReasoningEffort: raw.supportsReasoningEffort === true,
    reasoningEfforts: efforts
  }
}

export function reasoningOptionsFromCapability(capability: ModelCapability | null): ReasoningOption[] {
  // 不可关思考的模型（如 GLM 5.3 系）语义是"档位"而非"开关"，按服务端下发的
  // reasoningEfforts 渲染；其余按思考开关三档渲染（服务端会按供应商纠正参数）。
  if (capability && capability.alwaysThinking && capability.reasoningEfforts.length) {
    return capability.reasoningEfforts.map(effort => ({
      value: effort as GlmReasoningEffort,
      kind: 'effort' as const,
      label: EFFORT_LABELS[effort] || effort,
      shortLabel: effort
    }))
  }
  const modes = capability?.thinkingModes?.length
    ? capability.thinkingModes
    : ALL_THINKING_MODES
  return thinkingOptions
    .filter(option => modes.includes(option.value))
    .map(option => ({ ...option, kind: 'thinking' as const }))
}

export function isEffortKindOption(options: ReasoningOption[]): boolean {
  return options.length > 0 && options.every(option => option.kind === 'effort')
}

export async function fetchModelCapability(model: string, baseUrl = ''): Promise<ModelCapability | null> {
  const trimmed = model.trim()
  if (!trimmed) return null
  const params = new URLSearchParams({ model: trimmed })
  if (baseUrl.trim()) params.set('base_url', baseUrl.trim())
  try {
    const token = localStorage.getItem('token')
    const response = await fetch(apiUrl(`/ai/chat/model-capabilities?${params.toString()}`), {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined
    })
    if (!response.ok) return null
    return capabilityFromPayload(await response.json())
  } catch {
    return null
  }
}

function migrateReasoningEffort(value: unknown): GlmReasoningEffort {
  return GLM_REASONING_EFFORTS.includes(value as GlmReasoningEffort)
    ? value as GlmReasoningEffort
    : 'max'
}

function thinkingModeForGlmEffort(effort: GlmReasoningEffort): ThinkingMode {
  return effort === 'low' ? 'standard' : 'deep'
}

function migrateThinkingMode(value: unknown): ThinkingMode {
  if (value === 'disabled' || value === 'standard' || value === 'deep') return value
  if (value === 'off') return 'disabled'
  if (value === 'low' || value === 'medium') return 'standard'
  if (value === 'high' || value === 'max' || value === 'xhigh') return 'deep'
  return 'disabled'
}

export function getDefaultModelSettings(): ModelSettings {
  return {
    provider: 'system',
    apiKey: '',
    baseUrl: '',
    models: [],
    selectedModel: '',
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
    // system 供应商的清单一律以服务端目录为准，旧的本地残留（含"系统默认"占位）清空重拉。
    const storedModels = provider === 'system'
      ? []
      : Array.isArray(parsed.models)
        ? parsed.models.filter(model => typeof model === 'string' && model.trim())
        : []
    const models = [...new Set(storedModels)]
    const selectedModel = parsed.selectedModel?.trim() && models.includes(parsed.selectedModel.trim())
      ? parsed.selectedModel.trim()
      : models[0] || ''

    const reasoningEffort = parsed.reasoningEffort
      ? migrateReasoningEffort(parsed.reasoningEffort)
      : undefined
    return {
      ...fallback,
      ...parsed,
      provider,
      models,
      selectedModel,
      thinkingMode: reasoningEffort
        ? thinkingModeForGlmEffort(reasoningEffort)
        : migrateThinkingMode(parsed.thinkingMode ?? parsed.reasoningEffort),
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
  const normalizedReasoningEffort = settings.reasoningEffort
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
      ...(normalizedReasoningEffort ? { reasoningEffort: normalizedReasoningEffort } : {})
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
      ...(settings.reasoningEffort
        ? { reasoningEffort: migrateReasoningEffort(settings.reasoningEffort) }
        : {})
    }
  }
  const savedConnection = provider === 'system' ? undefined : providerConnections[provider]
  const models = savedConnection?.models?.length ? [...savedConnection.models] : [...preset.models]
  const selectedModel = savedConnection?.selectedModel && models.includes(savedConnection.selectedModel)
    ? savedConnection.selectedModel
    : models[0] || ''
  const reasoningEffort = savedConnection?.reasoningEffort || settings.reasoningEffort
  const normalizedReasoningEffort = reasoningEffort
    ? migrateReasoningEffort(reasoningEffort)
    : undefined
  const thinkingMode = normalizedReasoningEffort
    ? thinkingModeForGlmEffort(normalizedReasoningEffort)
    : savedConnection?.thinkingMode || settings.thinkingMode
  return {
    ...settings,
    provider,
    baseUrl: savedConnection?.baseUrl || preset.baseUrl,
    models,
    selectedModel,
    thinkingMode,
    apiKey: savedConnection?.apiKey || '',
    reasoningEffort: normalizedReasoningEffort,
    providerConnections
  }
}

export function toModelRequestSettings(settings: ModelSettings) {
  if (settings.provider === 'system') {
    return {
      model: settings.selectedModel === '系统默认' ? undefined : settings.selectedModel,
      thinkingMode: settings.thinkingMode,
      ...(settings.reasoningEffort ? { reasoningEffort: migrateReasoningEffort(settings.reasoningEffort) } : {})
    }
  }
  return {
    model: settings.selectedModel,
    baseUrl: settings.baseUrl,
    apiKey: settings.apiKey,
    thinkingMode: settings.thinkingMode,
    ...(settings.reasoningEffort ? { reasoningEffort: migrateReasoningEffort(settings.reasoningEffort) } : {})
  }
}
