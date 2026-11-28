<template>
  <el-popover
    v-if="composer"
    placement="top-end"
    trigger="click"
    :width="232"
    :offset="10"
    :show-arrow="false"
    popper-class="composer-model-popover"
    @show="handleComposerOpen"
  >
    <template #reference>
      <button
        class="composer-model-trigger"
        type="button"
        :style="{ '--effort-color': activeReasoningColor }"
        :aria-label="triggerTitle"
        aria-haspopup="dialog"
        :title="triggerTitle"
      >
        <span class="composer-model-name">{{ settings.selectedModel || '选择模型' }}</span>
        <span v-if="settings.selectedModel" class="composer-model-effort">{{ activeReasoningShortLabel }}</span>
        <el-icon><ArrowDown /></el-icon>
      </button>
    </template>

    <div class="model-menu" role="dialog" aria-label="模型与思考强度" :style="{ '--effort-color': activeReasoningColor }">
      <div class="model-menu__head">
        <span class="model-menu__label">模型</span>
      </div>

      <div class="model-menu__list" role="listbox" aria-label="选择模型">
        <button
          v-for="model in availableModels"
          :key="model"
          class="model-menu__model"
          :class="{ 'is-selected': model === settings.selectedModel }"
          type="button"
          role="option"
          :aria-selected="model === settings.selectedModel"
          @click="selectModel(model)"
        >
          <span class="model-menu__model-name">{{ model }}</span>
          <el-icon v-if="model === settings.selectedModel" class="model-menu__check"><Check /></el-icon>
        </button>
        <p v-if="modelsLoading" class="model-menu__empty">正在加载模型…</p>
        <p v-else-if="!availableModels.length" class="model-menu__empty">暂无可用模型</p>
      </div>

      <div class="model-menu__divider" role="separator"></div>

      <div class="model-menu__effort">
        <span class="model-menu__label">思考强度</span>
        <div class="model-menu__gear">
          <NeuGearKnob
            :options="gearOptions"
            :model-value="selectedReasoningOption?.value ?? ''"
            :disabled="!activeCapability"
            aria-label="思考强度旋钮"
            @update:model-value="selectReasoningOption"
          />
        </div>
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
      :disabled="!activeCapability"
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
import { localFetch } from '@/platform/api'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowDown, Check, Connection, Cpu, Opportunity } from '@element-plus/icons-vue'
import NeuGearKnob from '@/components/common/NeuGearKnob.vue'
import { apiUrl } from '@/platform'
import {
  MODEL_SETTINGS_EVENT,
  applyProviderPreset,
  capabilityFromPayload,
  fetchModelCapability,
  loadModelSettings,
  modelProviderPresets,
  normalizeModelReasoning,
  reasoningOptionsFromCapability,
  saveModelSettings,
  type ReasoningEffort,
  type ModelCapability,
  type ModelProviderId,
  type ModelSettings,
  type ThinkingMode
} from '@/config/modelSettings'

withDefaults(defineProps<{ compact?: boolean; composer?: boolean }>(), { compact: false, composer: false })

const settings = ref(loadModelSettings())
const modelsLoading = ref(false)
let systemModelsRequest = 0
const availableModels = computed(() => settings.value.models)
const modelCapability = ref<ModelCapability | null>(null)
const capabilityKey = ref('')
let capabilityRequest = 0
function modelKey(): string {
  return JSON.stringify([settings.value.provider, settings.value.selectedModel, settings.value.baseUrl])
}
const activeCapability = computed(() => capabilityKey.value === modelKey() ? modelCapability.value : null)
const reasoningOptions = computed(() => reasoningOptionsFromCapability(activeCapability.value))
watch(() => [activeCapability.value, settings.value] as const, ([capability, current]) => {
  const normalized = normalizeModelReasoning(current, capability)
  if (normalized === current) return
  settings.value = normalized
  saveModelSettings(normalized)
}, { flush: 'sync' })
const reasoningSelection = computed<ThinkingMode | ReasoningEffort>({
  get: () => settings.value.reasoningEffort || settings.value.thinkingMode,
  set: value => {
    const selected = reasoningOptions.value.find(option => option.value === value)
    if (selected?.kind === 'effort') {
      const effort = value as ReasoningEffort
      settings.value = { ...settings.value, reasoningEffort: effort,
        thinkingMode: effort === 'low' ? 'standard' : 'deep' }
      return
    }
    settings.value = { ...settings.value, thinkingMode: value as ThinkingMode, reasoningEffort: undefined }
  }
})
const selectedReasoningOption = computed(() => {
  const selected = reasoningOptions.value.find(option => String(option.value) === String(reasoningSelection.value))
  return selected || { value: reasoningSelection.value, label: String(reasoningSelection.value),
    shortLabel: String(reasoningSelection.value) }
})
const reasoningIndex = computed(() => {
  const option = selectedReasoningOption.value
  if (!option) return 0
  const index = reasoningOptions.value.findIndex(item => String(item.value) === String(option.value))
  return Math.max(0, index)
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
// 档位颜色沿用语义色板：越往上越“重”，关档保持中性。
const REASONING_COLORS: Record<string, string> = {
  disabled: 'var(--text-secondary)',
  low: 'var(--sem-flow)',
  standard: 'var(--sem-running)',
  medium: 'var(--sem-running)',
  high: 'var(--sem-waiting)',
  deep: 'var(--sem-artifact)',
  xhigh: 'var(--sem-artifact)',
  max: 'var(--sem-artifact)'
}
const activeReasoningLabel = computed(() => {
  if (!activeCapability.value) return '能力待确认'
  const option = selectedReasoningOption.value
  return option ? reasoningLabel(option.value) : '标准'
})
const activeReasoningShortLabel = computed(() => {
  if (!activeCapability.value) return '待确认'
  const option = selectedReasoningOption.value
  return option ? reasoningShortLabel(option) : '标准'
})
const activeReasoningColor = computed(() => {
  const option = selectedReasoningOption.value
  return reasoningColor(option ? option.value : 'standard')
})
const triggerTitle = computed(() => {
  const model = settings.value.selectedModel || '选择模型'
  return `${model} · 思考强度：${activeReasoningLabel.value}`
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

function reasoningColor(value: ThinkingMode | ReasoningEffort): string {
  return REASONING_COLORS[String(value)] || 'var(--text-secondary)'
}

function selectReasoningOption(value: ThinkingMode | ReasoningEffort): void {
  reasoningSelection.value = value
  persistSettings()
}

// 旋钮挡位选项（交互细节由 NeuGearKnob 承担）
const gearOptions = computed(() => reasoningOptions.value.map(option => ({
  value: option.value,
  label: reasoningShortLabel(option),
  color: reasoningColor(option.value)
})))

function selectModel(model: string): void {
  if (model === settings.value.selectedModel) return
  settings.value.selectedModel = model
  persistSettings()
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

    const response = await localFetch(apiUrl('/ai/chat/models'), {
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
  applyCapability(capabilityFromPayload(entry))
}

function applyCapability(capability: ModelCapability | null): void {
  if (!capability) return
  modelCapability.value = null
  capabilityKey.value = modelKey()
  modelCapability.value = capability
}

// 档位选择器随服务端能力元数据变化：system 供应商的目录响应已携带 capabilities，
// 其余供应商（自定义 base_url）按需走 /ai/chat/model-capabilities 单查。
watch(
  modelKey,
  () => {
    capabilityRequest++
    modelCapability.value = null
    const { provider, selectedModel, baseUrl } = settings.value
    if (selectedModel) void refreshCapability(selectedModel, provider === 'system' ? '' : baseUrl)
  },
  { immediate: true }
)

async function refreshCapability(model: string, baseUrl = ''): Promise<void> {
  const key = modelKey()
  const request = ++capabilityRequest
  const capability = await fetchModelCapability(model, baseUrl)
  if (request === capabilityRequest && key === modelKey()) {
    applyCapability(capability)
  }
}

onMounted(() => {
  window.addEventListener(MODEL_SETTINGS_EVENT, syncSettings)
  void loadSystemModels()
})
onUnmounted(() => {
  capabilityRequest++
  systemModelsRequest++
  window.removeEventListener(MODEL_SETTINGS_EVENT, syncSettings)
})

function handleComposerOpen(): void {
  if (settings.value.provider === 'system' && !availableModels.value.length) void loadSystemModels()
}
</script>

<style scoped>
.composer-model-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 240px;
  min-height: 28px;
  padding: 4px 7px 4px 9px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
  transition: background-color 160ms ease, color 160ms ease;
}
.composer-model-trigger:hover { background: color-mix(in srgb, var(--text-primary) 6%, transparent); color: var(--text-primary); }
.composer-model-trigger:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 1px; }
.composer-model-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.composer-model-effort { flex: 0 0 auto; color: color-mix(in srgb, var(--effort-color) 66%, var(--text-secondary)); font-size: 11px; transition: color 200ms ease; }
.composer-model-trigger:hover .composer-model-effort { color: color-mix(in srgb, var(--effort-color) 72%, var(--text-primary)); }
.composer-model-trigger .el-icon { flex: 0 0 auto; font-size: 10px; color: var(--text-muted); }
/* 新拟物令牌：表面=弹层实际底色（同色铁律），浅色方案白体系（暗角灰/亮角白），暗色方案覆盖派生比例 */
.model-menu { --neu-surface: var(--bg-card); --neu-dark: color-mix(in srgb, #000 16%, var(--neu-surface)); --neu-light: #ffffff; display: grid; gap: 2px; }
html[data-color-scheme='codex-dark'] .model-menu,
html[data-color-scheme='one-dark-modern'] .model-menu { --neu-dark: color-mix(in srgb, #000 26%, var(--neu-surface)); --neu-light: color-mix(in srgb, #fff 15%, var(--neu-surface)); }
.model-menu__head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 4px 8px 2px; }
.model-menu__label { color: var(--text-muted); font-size: 11px; font-weight: 600; letter-spacing: .02em; line-height: 16px; }
.model-menu__list {
  display: grid;
  gap: 1px;
  max-height: 202px;
  padding: 2px 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.model-menu__list::-webkit-scrollbar { width: 4px; }
.model-menu__list::-webkit-scrollbar-thumb { border-radius: 999px; background: color-mix(in srgb, var(--text-primary) 16%, transparent); }
.model-menu__model {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: 32px;
  padding: 0 8px 0 9px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-regular);
  font: inherit;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
  transition: background-color 140ms ease, color 140ms ease;
}
.model-menu__model:hover { background: color-mix(in srgb, var(--text-primary) 6%, transparent); color: var(--text-primary); }
.model-menu__model:focus-visible { outline: 2px solid var(--primary-color); outline-offset: -2px; }
.model-menu__model.is-selected { color: var(--text-primary); }
.model-menu__model-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.model-menu__check { flex: 0 0 auto; margin-left: auto; font-size: 12px; color: var(--text-secondary); }
.model-menu__empty { margin: 0; padding: 10px 8px; color: var(--text-muted); font-size: 11px; text-align: center; }
.model-menu__divider { height: 1px; margin: 6px 5px; background: color-mix(in srgb, var(--border-light) 62%, transparent); }
.model-menu__effort { display: grid; gap: 6px; padding: 2px 8px 6px; }
/* 思考强度 = 拟物挡位旋钮（NeuGearKnob），样式与交互都在组件内 */
.model-menu__gear { display: flex; justify-content: center; padding: 4px 0 8px; }
.model-menu__check { animation: model-menu-check-in 200ms cubic-bezier(.2, .9, .3, 1.35) both; }
@keyframes model-menu-check-in {
  from { opacity: 0; transform: scale(.55); }
  to { opacity: 1; transform: scale(1); }
}
.model-menu-pop-enter-active,
.model-menu-pop-leave-active { transition: opacity 120ms ease, transform 120ms ease; }
.model-menu-pop-enter-from,
.model-menu-pop-leave-to { opacity: 0; transform: translateY(-3px) scale(.98); }

@media (max-width: 620px) {
  .composer-model-trigger { max-width: 168px; padding-inline: 5px; font-size: 11px; }
}
@media (prefers-reduced-motion: reduce) {
  .model-menu__check { animation: none; transition: none; }
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
  width: min(232px, calc(100vw - 24px)) !important;
  max-width: calc(100vw - 24px);
  padding: 6px;
  border: 1px solid color-mix(in srgb, var(--border-light) 74%, transparent);
  border-radius: 16px;
  background: var(--bg-card);
  box-shadow: var(--shadow-lg), 0 0 0 1px color-mix(in srgb, var(--text-primary) 3%, transparent) inset;
  animation: composer-model-popover-in 140ms cubic-bezier(.2, .8, .2, 1);
}
.composer-model-popover .el-popper__arrow { display: none; }
@keyframes composer-model-popover-in {
  from { opacity: 0; transform: translateY(4px) scale(.985); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
@media (prefers-reduced-motion: reduce) {
  .composer-model-popover.el-popover.el-popper { animation: none; }
}
</style>
