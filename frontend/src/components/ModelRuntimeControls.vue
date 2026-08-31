<template>
  <div class="model-runtime-controls" :class="{ compact }" aria-label="模型运行设置">
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
      aria-label="选择模型"
      @change="persistSettings"
    >
      <template #prefix><el-icon><Cpu /></el-icon></template>
      <el-option
        v-for="model in availableModels"
        :key="model"
        :label="compact ? compactModelLabel(model) : model"
        :value="model"
      />
    </el-select>

    <el-select
      v-model="settings.thinkingMode"
      class="reasoning-select"
      aria-label="选择思考程度"
      @change="persistSettings"
    >
      <template #prefix><el-icon><Opportunity /></el-icon></template>
      <el-option
        v-for="option in thinkingOptions"
        :key="option.value"
        :label="compact ? option.shortLabel : option.label"
        :value="option.value"
      />
    </el-select>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Connection, Cpu, Opportunity } from '@element-plus/icons-vue'
import { apiUrl } from '@/platform'
import {
  MODEL_SETTINGS_EVENT,
  SYSTEM_FALLBACK_MODELS,
  applyProviderPreset,
  loadModelSettings,
  modelProviderPresets,
  thinkingOptions,
  saveModelSettings,
  type ModelProviderId,
  type ModelSettings
} from '@/config/modelSettings'

withDefaults(defineProps<{ compact?: boolean }>(), { compact: false })

const settings = ref(loadModelSettings())
const modelsLoading = ref(false)
let systemModelsRequest = 0
const availableModels = computed(() => settings.value.models.length ? settings.value.models : SYSTEM_FALLBACK_MODELS)
const providerTitle = computed(() => {
  const provider = modelProviderPresets.find(item => item.id === settings.value.provider)
  return provider ? `${provider.name} · ${provider.description}` : '选择模型服务商'
})

function persistSettings(): void {
  saveModelSettings(settings.value)
}

function compactModelLabel(model: string): string {
  const labels: Record<string, string> = {
    'deepseek-v4-flash': 'Flash',
    'deepseek-v4-pro': 'Pro',
    'glm-5.2': 'GLM 5.2'
  }
  return labels[model] || model
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
  settings.value = detail ? { ...detail, models: [...detail.models] } : loadModelSettings()
  if (settings.value.provider === 'system') void loadSystemModels()
}

async function loadSystemModels(): Promise<void> {
  if (settings.value.provider !== 'system') return
  const requestId = ++systemModelsRequest
  modelsLoading.value = true
  try {
    const token = localStorage.getItem('token')
    const response = await fetch(apiUrl('/ai/chat/models'), {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined
    })
    if (!response.ok || requestId !== systemModelsRequest || settings.value.provider !== 'system') return
    const data = await response.json() as { models?: unknown; default_model?: unknown }
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
      selectedModel: models.includes(settings.value.selectedModel) ? settings.value.selectedModel : defaultModel
    }
    saveModelSettings(settings.value)
  } catch {
    // Keep the system-default fallback when the model catalog is unavailable.
  } finally {
    if (requestId === systemModelsRequest) modelsLoading.value = false
  }
}

onMounted(() => {
  window.addEventListener(MODEL_SETTINGS_EVENT, syncSettings)
  void loadSystemModels()
})
onUnmounted(() => window.removeEventListener(MODEL_SETTINGS_EVENT, syncSettings))
</script>

<style scoped>
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
