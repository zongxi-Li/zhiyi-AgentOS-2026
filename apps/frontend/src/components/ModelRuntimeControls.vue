<template>
  <el-popover v-if="composer" placement="top-end" trigger="click" :width="340" popper-class="composer-model-popover">
    <template #reference>
      <button class="composer-model-trigger" type="button" aria-label="选择模型" aria-haspopup="dialog" :title="settings.selectedModel">
        <span class="composer-model-name">{{ settings.selectedModel }}</span>
        <el-icon><ArrowDown /></el-icon>
      </button>
    </template>
    <div class="composer-model-heading">模型设置</div>
    <ModelRuntimeControls compact />
  </el-popover>
  <div v-else class="model-runtime-controls" :class="{ compact }" aria-label="模型运行设置">
    <el-select
      :model-value="settings.provider"
      class="provider-select"
      :title="providerTitle"
      aria-label="选择模型服务商"
      @change="selectProvider"
    >
      <template #prefix><el-icon><Connection /></el-icon></template>
      <el-option
        v-for="provider in modelProviderPresets"
        :key="provider.id"
        :label="compact ? compactProviderLabel(provider.id) : provider.name"
        :value="provider.id"
      />
    </el-select>

    <el-select
      v-model="settings.selectedModel"
      class="model-select"
      :loading="modelsLoading"
      placeholder="默认模型"
      aria-label="选择模型"
      @change="persistSettings"
    >
      <template #prefix><el-icon><Cpu /></el-icon></template>
      <el-option
        v-for="model in availableModels"
        :key="model"
        :label="model"
        :value="model"
      />
    </el-select>

    <el-select
      v-model="reasoningSelection"
      class="reasoning-select"
      aria-label="选择思考程度"
      @change="persistSettings"
    >
      <template #prefix><el-icon><Opportunity /></el-icon></template>
      <el-option
        v-for="option in reasoningOptions"
        :key="option.value"
        :label="compact ? option.shortLabel : option.label"
        :value="option.value"
      />
    </el-select>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowDown, Connection, Cpu, Opportunity } from '@element-plus/icons-vue'
import { apiUrl } from '@/platform'
import {
  MODEL_SETTINGS_EVENT,
  applyProviderPreset,
  capabilityFromPayload,
  fetchModelCapability,
  isEffortKindOption,
  loadModelSettings,
  modelProviderPresets,
  reasoningOptionsFromCapability,
  saveModelSettings,
  type GlmReasoningEffort,
  type ModelCapability,
  type ModelProviderId,
  type ModelSettings,
  type ThinkingMode
} from '@/config/modelSettings'

const props = withDefaults(defineProps<{ compact?: boolean; composer?: boolean }>(), { compact: false, composer: false })

const settings = ref(loadModelSettings())
const modelsLoading = ref(false)
let systemModelsRequest = 0
const availableModels = computed(() => settings.value.models)
const modelCapability = ref<ModelCapability | null>(null)
const reasoningOptions = computed(() => reasoningOptionsFromCapability(modelCapability.value))
const usesEffortOptions = computed(() => isEffortKindOption(reasoningOptions.value))
const reasoningSelection = computed<ThinkingMode | GlmReasoningEffort>({
  get: () => {
    if (usesEffortOptions.value) {
      const stored = settings.value.reasoningEffort
      const options = reasoningOptions.value.map(option => String(option.value))
      const matched = stored && options.includes(stored) ? stored : options[options.length - 1]
      return (matched || 'max') as GlmReasoningEffort
    }
    return settings.value.thinkingMode
  },
  set: value => {
    if (usesEffortOptions.value) {
      const effort = value as GlmReasoningEffort
      settings.value.reasoningEffort = effort
      settings.value.thinkingMode = effort === 'low' ? 'standard' : 'deep'
      return
    }
    settings.value.thinkingMode = value as ThinkingMode
    settings.value.reasoningEffort = undefined
  }
})
const providerTitle = computed(() => {
  const provider = modelProviderPresets.find(item => item.id === settings.value.provider)
  return provider ? `${provider.name} · ${provider.description}` : '选择模型服务商'
})

function persistSettings(): void {
  saveModelSettings(settings.value)
}

function compactProviderLabel(provider: ModelProviderId): string {
  const labels: Partial<Record<ModelProviderId, string>> = {
    system: '服务端',
    deepseek: 'DeepSeek',
    glm: 'GLM',
    qwen: 'Qwen',
    openai: 'OpenAI',
    custom: '自定义'
  }
  return labels[provider] || provider
}

function selectProvider(provider: ModelProviderId): void {
  if (!modelProviderPresets.some(item => item.id === provider)) return
  settings.value = applyProviderPreset(settings.value, provider)
  persistSettings()
  if (provider === 'system') void loadSystemModels()
}

function syncSettings(event: Event): void {
  const detail = (event as CustomEvent<ModelSettings>).detail
  const previousProvider = settings.value.provider
  settings.value = detail ? { ...detail, models: [...detail.models] } : loadModelSettings()
  if (settings.value.provider === 'system' && previousProvider !== 'system') void loadSystemModels(true)
}

async function loadSystemModels(preferServerDefault = false): Promise<void> {
  if (settings.value.provider !== 'system') return
  const requestId = ++systemModelsRequest
  modelsLoading.value = true
  try {
    const token = localStorage.getItem('token')
    const response = await fetch(apiUrl('/ai/chat/models'), {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined
    })
    if (!response.ok || requestId !== systemModelsRequest || settings.value.provider !== 'system') return
    const data = await response.json() as { models?: unknown; default_model?: unknown; capabilities?: unknown }
    const models = Array.isArray(data.models)
      ? data.models.filter((model): model is string => typeof model === 'string' && Boolean(model.trim()))
      : []
    if (!models.length || requestId !== systemModelsRequest || settings.value.provider !== 'system') return

    const defaultModel = typeof data.default_model === 'string' && models.includes(data.default_model)
      ? data.default_model
      : models[0]
    settings.value = {
      ...settings.value,
      models,
      selectedModel: preferServerDefault || !models.includes(settings.value.selectedModel)
        ? defaultModel
        : settings.value.selectedModel
    }
    saveModelSettings(settings.value)
    syncCapabilityFromCatalog(data.capabilities, settings.value.selectedModel)
  } catch {
    // Keep the system-default fallback when the model catalog is unavailable.
  } finally {
    if (requestId === systemModelsRequest) modelsLoading.value = false
  }
}

function syncCapabilityFromCatalog(catalog: unknown, model: string): void {
  const entry = catalog && typeof catalog === 'object'
    ? (catalog as Record<string, unknown>)[model]
    : undefined
  modelCapability.value = capabilityFromPayload(entry)
}

// 档位选择器随服务端能力元数据变化：system 供应商的目录响应已携带 capabilities，
// 其余供应商（自定义 base_url）按需走 /ai/chat/model-capabilities 单查。
watch(
  () => [settings.value.provider, settings.value.selectedModel, settings.value.baseUrl] as const,
  ([provider, model, baseUrl]) => {
    if (provider === 'system') {
      // 目录尚未拉取时不主动清空已有能力；loadSystemModels 会带目录回填。
      if (!modelCapability.value && model) void refreshCapability(model)
      return
    }
    modelCapability.value = null
    if (model) void refreshCapability(model, baseUrl)
  },
  { immediate: true }
)

async function refreshCapability(model: string, baseUrl = ''): Promise<void> {
  const capability = await fetchModelCapability(model, baseUrl)
  if (model === settings.value.selectedModel && (settings.value.provider === 'system' || baseUrl === settings.value.baseUrl)) {
    modelCapability.value = capability
  }
}

onMounted(() => {
  window.addEventListener(MODEL_SETTINGS_EVENT, syncSettings)
  if (!props.composer) void loadSystemModels()
})
onUnmounted(() => window.removeEventListener(MODEL_SETTINGS_EVENT, syncSettings))
</script>

<style scoped>
.composer-model-trigger {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 210px;
  min-height: 30px;
  padding: 5px 9px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  transition: background 160ms ease, color 160ms ease;
}
.composer-model-trigger:hover { background: color-mix(in srgb, var(--text-primary) 7%, transparent); color: var(--text-primary); }
.composer-model-trigger:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
.composer-model-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.composer-model-trigger .el-icon { flex-shrink: 0; font-size: 10px; color: var(--text-muted); }
.composer-model-heading { margin: 0 0 12px; color: var(--text-secondary); font-size: 13px; font-weight: 600; }
@media (max-width: 620px) { .composer-model-trigger { max-width: 120px; font-size: 11px; padding-inline: 4px; } }
.model-runtime-controls {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}

.model-select {
  width: 164px;
}

.provider-select {
  width: 138px;
}

.reasoning-select {
  width: 126px;
}

.model-runtime-controls.compact .provider-select {
  width: 88px;
}

.model-runtime-controls.compact .model-select {
  width: 112px;
}

.model-runtime-controls.compact .reasoning-select {
  width: 82px;
}

.model-runtime-controls :deep(.el-select__wrapper) {
  min-height: 28px;
  padding: 0 8px;
  border-radius: 6px;
  background: color-mix(in srgb, var(--bg-card) 78%, transparent);
  box-shadow: 0 0 0 1px var(--border-light) inset;
}

.model-runtime-controls :deep(.el-select__selected-item),
.model-runtime-controls :deep(.el-select__placeholder) {
  font-size: 11px;
}

.model-runtime-controls :deep(.el-select__prefix),
.model-runtime-controls :deep(.el-select__suffix) {
  font-size: 12px;
}

.model-runtime-controls :deep(.el-select__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--border-hover) inset;
}

@media (max-width: 620px) {
  .model-runtime-controls,
  .model-runtime-controls.compact {
    width: 100%;
  }

  .model-runtime-controls .model-select,
  .model-runtime-controls.compact .model-select {
    width: auto;
    flex: 1 1 auto;
  }

  .model-runtime-controls .provider-select,
  .model-runtime-controls.compact .provider-select {
    width: 92px;
    flex: 0 0 92px;
  }

  .model-runtime-controls .reasoning-select,
  .model-runtime-controls.compact .reasoning-select {
    width: 92px;
    flex: 0 0 92px;
  }
}
</style>

<style>
.composer-model-popover.el-popover.el-popper {
  background: var(--bg-card);
  border: 1px solid var(--border-color);
  border-radius: 14px;
  padding: 16px;
  box-shadow: 0 16px 40px rgba(0, 0, 0, .25);
}
.composer-model-popover.el-popper .el-popper__arrow::before { background: var(--bg-card); border-color: var(--border-color); }
</style>
