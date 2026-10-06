<template>
  <el-popover
    v-if="composer"
    placement="top-end"
    trigger="click"
    :width="332"
    popper-class="composer-model-popover"
    @show="handleComposerOpen"
  >
    <template #reference>
      <button class="composer-model-trigger" type="button" aria-label="选择模型与思考强度" aria-haspopup="dialog" :title="settings.selectedModel">
        <span class="composer-model-copy">
          <span class="composer-model-effort">{{ activeReasoningShortLabel }}</span>
          <span class="composer-model-separator" aria-hidden="true">·</span>
          <span class="composer-model-name">{{ settings.selectedModel || '选择模型' }}</span>
        </span>
        <el-icon><ArrowDown /></el-icon>
      </button>
    </template>
    <div class="composer-model-panel">
      <div class="composer-model-panel__heading">
        <span class="composer-model-panel__icon"><el-icon><Opportunity /></el-icon></span>
        <div class="composer-model-panel__hero">
          <div class="composer-model-panel__effort">{{ activeReasoningLabel }} <el-icon><ArrowRight /></el-icon></div>
          <div class="composer-model-panel__model">{{ settings.selectedModel || '尚未选择模型' }}</div>
        </div>
      </div>

      <div class="reasoning-battery" :class="{ 'is-disabled': reasoningOptions.length < 2 }">
        <div class="reasoning-battery__meter">
          <span class="reasoning-battery__cap" aria-hidden="true"></span>
          <div class="reasoning-battery__case">
            <div class="reasoning-battery__cells" aria-hidden="true">
              <span
                v-for="(option, index) in batteryOptions"
                :key="option.value"
                class="reasoning-battery__segment"
                :class="{ active: index < batteryActiveCount }"
              ></span>
            </div>
            <input
              class="reasoning-battery__input"
              type="range"
              :min="0"
              :max="Math.max(reasoningOptions.length - 1, 0)"
              step="1"
              :value="reasoningIndex"
              :aria-valuetext="activeReasoningLabel"
              aria-label="调整思考强度"
              :disabled="reasoningOptions.length < 2"
              @input="updateReasoningFromSlider"
              @change="persistSettings"
            >
          </div>
        </div>
        <div class="reasoning-battery__options" role="radiogroup" aria-label="思考强度档位">
          <span
            v-for="option in displayReasoningOptions"
            :key="`label-${option.value}`"
            class="reasoning-battery__option"
            :class="{ active: isSelectedReasoningOption(option) }"
            role="radio"
            :aria-checked="isSelectedReasoningOption(option)"
            tabindex="0"
            @click="selectReasoningOption(option.value)"
            @keydown.enter.prevent="selectReasoningOption(option.value)"
            @keydown.space.prevent="selectReasoningOption(option.value)"
          >
            <span class="reasoning-battery__option-dot" aria-hidden="true"></span>
            <span class="reasoning-battery__option-copy">
              <strong>{{ reasoningShortLabel(option) }}</strong>
              <small>{{ reasoningDescription(option.value) }}</small>
            </span>
            <el-icon v-if="isSelectedReasoningOption(option)" class="reasoning-battery__option-check"><Check /></el-icon>
          </span>
        </div>
      </div>

      <div class="composer-model-panel__controls">
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
            :label="compactProviderLabel(provider.id)"
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
          <el-option v-for="model in availableModels" :key="model" :label="model" :value="model" />
        </el-select>
      </div>
    </div>
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
import { ArrowDown, ArrowRight, Check, Connection, Cpu, Opportunity } from '@element-plus/icons-vue'
import { apiUrl } from '@/platform'
import {
  MODEL_SETTINGS_EVENT,
  applyProviderPreset,
  capabilityFromPayload,
  defaultReasoningEffortFromCapability,
  effortValuesFromOptions,
  fetchModelCapability,
  isEffortKindOption,
  loadModelSettings,
  modelProviderPresets,
  reasoningOptionsFromCapability,
  saveModelSettings,
  type ReasoningEffort,
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
const reasoningSelection = computed<ThinkingMode | ReasoningEffort>({
  get: () => {
    if (usesEffortOptions.value) {
      const stored = settings.value.reasoningEffort
      const effortOptions = effortValuesFromOptions(reasoningOptions.value)
      if (stored && effortOptions.includes(stored)) return stored as ReasoningEffort
      if (settings.value.thinkingMode === 'disabled' && reasoningOptions.value.some(option => option.value === 'disabled')) {
        return 'disabled'
      }
      if (settings.value.thinkingMode === 'standard' && effortOptions.includes('low')) return 'low'
      if (settings.value.thinkingMode === 'deep' && effortOptions.includes('max')) return 'max'
      return defaultReasoningEffortFromCapability(modelCapability.value, reasoningOptions.value) as ReasoningEffort
    }
    return settings.value.thinkingMode
  },
  set: value => {
    const selected = reasoningOptions.value.find(option => option.value === value)
    if (selected?.kind === 'effort') {
      const effort = value as ReasoningEffort
      settings.value.reasoningEffort = effort
      settings.value.thinkingMode = effort === 'low' ? 'standard' : 'deep'
      return
    }
    settings.value.thinkingMode = value as ThinkingMode
    settings.value.reasoningEffort = undefined
  }
})
const selectedReasoningOption = computed(() => {
  const selected = reasoningOptions.value.find(option => String(option.value) === String(reasoningSelection.value))
  return selected || reasoningOptions.value[0]
})
const reasoningIndex = computed(() => {
  const selected = selectedReasoningOption.value
  const index = selected ? reasoningOptions.value.indexOf(selected) : 0
  return Math.max(0, index)
})
const batteryOptions = computed(() => reasoningOptions.value.filter(option => option.value !== 'disabled'))
const displayReasoningOptions = computed(() => [...reasoningOptions.value].reverse())
const batteryActiveCount = computed(() => {
  const selected = selectedReasoningOption.value
  const total = batteryOptions.value.length
  if (!total || !selected || selected.value === 'disabled') return 0
  const index = batteryOptions.value.findIndex(option => String(option.value) === String(selected.value))
  return index < 0 ? 0 : index + 1
})
const REASONING_LABELS: Record<string, string> = {
  disabled: '关闭',
  low: '轻度',
  standard: '标准',
  medium: '中度',
  high: '高强度',
  deep: '深度',
  xhigh: '极高',
  max: '极致'
}
const REASONING_SHORT_LABELS: Record<string, string> = {
  disabled: '关',
  low: '轻度',
  standard: '标准',
  medium: '中度',
  high: '高',
  deep: '深度',
  xhigh: '极高',
  max: '极致'
}
const REASONING_DESCRIPTIONS: Record<string, string> = {
  disabled: '快速响应，不额外推理',
  low: '轻量推理，响应更快',
  standard: '平衡速度与分析深度',
  medium: '平衡速度与分析深度',
  high: '更充分地分析复杂任务',
  deep: '深入拆解问题与步骤',
  xhigh: '为复杂任务保留更多推理',
  max: '适合最复杂的任务'
}
const activeReasoningLabel = computed(() => {
  const option = selectedReasoningOption.value
  return option ? reasoningLabel(option.value) : '标准'
})
const activeReasoningShortLabel = computed(() => {
  const option = selectedReasoningOption.value
  return option ? reasoningShortLabel(option) : '标准'
})
const providerTitle = computed(() => {
  const provider = modelProviderPresets.find(item => item.id === settings.value.provider)
  return provider ? `${provider.name} · ${provider.description}` : '选择模型服务商'
})

function persistSettings(): void {
  saveModelSettings(settings.value)
}

function reasoningLabel(value: ThinkingMode | ReasoningEffort): string {
  return REASONING_LABELS[String(value)] || String(value)
}

function reasoningShortLabel(option: { value: ThinkingMode | ReasoningEffort; shortLabel: string }): string {
  return REASONING_SHORT_LABELS[String(option.value)] || option.shortLabel
}

function reasoningDescription(value: ThinkingMode | ReasoningEffort): string {
  return REASONING_DESCRIPTIONS[String(value)] || '按模型能力调整推理深度'
}

function selectReasoningOption(value: ThinkingMode | ReasoningEffort): void {
  reasoningSelection.value = value
  persistSettings()
}

function isSelectedReasoningOption(option: { value: ThinkingMode | ReasoningEffort }): boolean {
  return String(option.value) === String(selectedReasoningOption.value?.value)
}

function updateReasoningFromSlider(event: Event): void {
  const index = Number((event.target as HTMLInputElement).value)
  const option = reasoningOptions.value[index]
  if (option) reasoningSelection.value = option.value
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
  void loadSystemModels()
})
onUnmounted(() => window.removeEventListener(MODEL_SETTINGS_EVENT, syncSettings))

function handleComposerOpen(): void {
  if (settings.value.provider === 'system' && !availableModels.value.length) void loadSystemModels()
}
</script>

<style scoped>
.composer-model-trigger {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  max-width: 230px;
  min-height: 30px;
  padding: 5px 8px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  transition: background 160ms ease, color 160ms ease, transform 160ms ease;
}
.composer-model-trigger:hover { background: color-mix(in srgb, var(--text-primary) 7%, transparent); color: var(--text-primary); }
.composer-model-trigger:active { transform: translateY(1px); }
.composer-model-trigger:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
.composer-model-copy { display: inline-flex; align-items: baseline; min-width: 0; gap: 5px; }
.composer-model-effort { color: var(--text-primary); font-size: 11px; font-weight: 700; white-space: nowrap; }
.composer-model-separator { color: var(--text-muted); }
.composer-model-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.composer-model-trigger .el-icon { flex-shrink: 0; font-size: 10px; color: var(--text-muted); }
.composer-model-panel { display: grid; gap: 4px; }
.composer-model-panel__heading { display: flex; align-items: center; gap: 8px; padding: 0; }
.composer-model-panel__icon { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; flex: 0 0 24px; border-radius: 8px; background: color-mix(in srgb, var(--primary-color) 14%, transparent); color: var(--primary-color); }
.composer-model-panel__icon .el-icon { font-size: 14px; }
.composer-model-panel__hero { min-width: 0; }
.composer-model-panel__effort { display: inline-flex; align-items: center; gap: 3px; color: var(--primary-color); font-size: 14px; font-weight: 700; letter-spacing: .01em; line-height: 1.1; }
.composer-model-panel__effort .el-icon { font-size: 13px; opacity: .78; }
.composer-model-panel__model { overflow: hidden; margin-top: 2px; color: var(--text-muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.composer-model-panel__controls { display: flex; align-items: center; gap: 6px; min-width: 0; padding-top: 2px; }
.composer-model-panel__controls .provider-select { width: 100px; flex: 0 0 100px; }
.composer-model-panel__controls .model-select { width: auto; flex: 1 1 auto; min-width: 0; }
.composer-model-panel__controls :deep(.el-select) { min-width: 0; }
.composer-model-panel__controls :deep(.el-select__wrapper) { min-height: 28px; padding: 0 5px; border: 0 !important; border-radius: 7px; background: transparent !important; box-shadow: none !important; }
.composer-model-panel__controls :deep(.el-select__selected-item),
.composer-model-panel__controls :deep(.el-select__placeholder) { font-size: 11px; }
.composer-model-panel__controls :deep(.el-select__prefix),
.composer-model-panel__controls :deep(.el-select__suffix) { font-size: 12px; }
.composer-model-panel__controls :deep(.el-select__wrapper:hover),
.composer-model-panel__controls :deep(.el-select__wrapper.is-focused) { background: color-mix(in srgb, var(--text-primary) 6%, transparent) !important; box-shadow: none !important; }

.reasoning-battery { display: grid; grid-template-columns: 48px minmax(0, 1fr); align-items: center; gap: 10px; min-height: 102px; padding: 0 5px 1px 11px; }
.reasoning-battery.is-disabled { opacity: .58; }
.reasoning-battery__meter { position: relative; display: flex; flex-direction: column; align-items: center; gap: 3px; }
.reasoning-battery__cap {
  width: 12px; height: 5px; border-radius: 2px 2px 1px 1px;
  background: linear-gradient(180deg, color-mix(in srgb, var(--text-primary) 40%, var(--bg-panel)), color-mix(in srgb, var(--text-primary) 16%, var(--bg-panel)));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .28), 0 1px 1px rgba(0, 0, 0, .4);
}
.reasoning-battery__case {
  position: relative; width: 28px; height: 84px; padding: 3px;
  border-radius: 9px;
  background: linear-gradient(180deg, color-mix(in srgb, var(--text-primary) 18%, var(--bg-panel)), color-mix(in srgb, var(--text-primary) 7%, var(--bg-panel)));
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, .22),
    inset 0 -1px 1px rgba(0, 0, 0, .35),
    0 2px 5px rgba(0, 0, 0, .32);
}
.reasoning-battery__cells {
  position: relative; display: flex; flex-direction: column-reverse; gap: 3px; width: 100%; height: 100%; padding: 2px;
  border-radius: 5px;
  background: color-mix(in srgb, var(--text-primary) 9%, var(--bg-panel));
  box-shadow: inset 0 1px 3px rgba(0, 0, 0, .5), inset 0 -1px 0 rgba(255, 255, 255, .06);
}
.reasoning-battery__segment {
  position: relative; flex: 1 1 0; min-height: 0; border-radius: 3px;
  background: linear-gradient(180deg, rgba(0, 0, 0, .32), rgba(0, 0, 0, .1));
  box-shadow: inset 0 1px 2px rgba(0, 0, 0, .45), inset 0 -1px 0 rgba(255, 255, 255, .05);
  transition: background 180ms ease, box-shadow 180ms ease;
}
.reasoning-battery__segment::after {
  content: ''; position: absolute; inset: 0; border-radius: inherit; pointer-events: none;
  background: linear-gradient(180deg, rgba(255, 255, 255, .12), rgba(255, 255, 255, .02) 50%, rgba(255, 255, 255, 0) 80%);
}
.reasoning-battery__segment.active {
  background: linear-gradient(180deg,
    color-mix(in srgb, var(--accent-color) 52%, #fff) 0%,
    var(--accent-color) 40%,
    color-mix(in srgb, var(--accent-color) 60%, #000) 100%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, .5),
    inset 0 -2px 3px color-mix(in srgb, var(--accent-color) 45%, #000),
    0 0 9px color-mix(in srgb, var(--accent-color) 38%, transparent);
}
.reasoning-battery__input { position: absolute; top: 50%; left: 50%; width: 84px; height: 28px; margin: 0; opacity: 0; cursor: pointer; transform: translate(-50%, -50%) rotate(-90deg); z-index: 2; }
.reasoning-battery__case:focus-within .reasoning-battery__cells { outline: 2px solid color-mix(in srgb, var(--primary-color) 70%, transparent); outline-offset: 3px; }
.reasoning-battery__options { display: grid; align-content: center; gap: 4px; min-width: 0; }
.reasoning-battery__option { display: flex; align-items: center; gap: 7px; min-height: 28px; padding: 3px 6px; border-radius: 8px; color: var(--text-secondary); cursor: pointer; transition: background 160ms ease, color 160ms ease; }
.reasoning-battery__option:hover,
.reasoning-battery__option:focus-visible { outline: none; background: color-mix(in srgb, var(--text-primary) 6%, transparent); color: var(--text-primary); }
.reasoning-battery__option.active { background: color-mix(in srgb, var(--primary-color) 10%, transparent); color: var(--primary-color); }
.reasoning-battery__option-dot { width: 6px; height: 6px; flex: 0 0 6px; border-radius: 50%; background: color-mix(in srgb, var(--text-primary) 26%, transparent); }
.reasoning-battery__option.active .reasoning-battery__option-dot { background: var(--accent-color); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent-color) 14%, transparent); }
.reasoning-battery__option-copy { display: grid; min-width: 0; gap: 1px; }
.reasoning-battery__option-copy strong { font-size: 11px; font-weight: 600; line-height: 1.1; }
.reasoning-battery__option-copy small { overflow: hidden; color: var(--text-muted); font-size: 8px; line-height: 1.15; text-overflow: ellipsis; white-space: nowrap; }
.reasoning-battery__option-check { margin-left: auto; flex: 0 0 auto; font-size: 12px; }

@media (max-width: 620px) {
  .composer-model-trigger { max-width: 160px; font-size: 11px; padding-inline: 4px; }
  .composer-model-panel__controls .provider-select { width: 96px; flex-basis: 96px; }
}
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
  width: min(366px, calc(100vw - 24px)) !important;
  max-width: calc(100vw - 24px);
  background: color-mix(in srgb, var(--bg-card) 98%, var(--bg-panel));
  border: 1px solid color-mix(in srgb, var(--border-color) 88%, transparent);
  border-radius: 16px;
  padding: 14px;
  box-shadow: 0 20px 46px rgba(0, 0, 0, .34), 0 0 0 1px rgba(255, 255, 255, .02) inset;
  animation: composer-model-popover-in 160ms cubic-bezier(.2,.8,.2,1);
}
.composer-model-popover.el-popper .el-popper__arrow::before { background: var(--bg-card); border-color: var(--border-color); }
@keyframes composer-model-popover-in {
  from { opacity: 0; transform: translateY(5px) scale(.98); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
@media (prefers-reduced-motion: reduce) {
  .composer-model-popover.el-popover.el-popper,
  .reasoning-battery__segment { animation: none; transition: none; }
}
</style>
