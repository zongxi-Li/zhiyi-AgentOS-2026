<template>
  <WorkbenchLayout :show-left="false" :show-right="false" storage-key="zhiyi.create-mission.layout.v1">
    <template #main>
      <main class="create-mission" aria-label="Create Mission">
        <div class="create-mission__workspace">
          <header class="create-mission__topbar">
            <button class="create-mission__back" type="button" @click="goBack">
              <span class="create-mission__back-icon" aria-hidden="true">←</span>
              <span>返回项目</span>
            </button>
            <div class="create-mission__topbar-title">
              <span class="create-mission__eyebrow">CREATE MISSION</span>
              <h1>新建任务</h1>
            </div>
            <span class="create-mission__topbar-mode">MISSION COMPOSER</span>
          </header>

          <section class="prompt-import" aria-labelledby="prompt-import-title">
            <div class="prompt-import__lead">
              <span class="prompt-import__eyebrow">PROMPT LIBRARY</span>
              <div>
                <strong id="prompt-import-title">快速填充 ACG 任务</strong>
                <p>从提示词库选择任务，自动填入基本信息。</p>
              </div>
            </div>
            <div class="prompt-import__controls">
              <label class="prompt-import__file">
                <span>{{ promptLoading ? '读取中…' : promptFileName ? '更换提示词文件' : '选择提示词文件' }}</span>
                <input type="file" accept=".md,text/markdown" @change="handlePromptFile" />
              </label>
              <label v-if="promptTasks.length" class="prompt-import__select">
                <span>任务</span>
                <select v-model="selectedPromptTaskId" aria-label="ACG 提示词任务" @change="applySelectedPromptTask">
                  <option value="">请选择任务…</option>
                  <option v-for="task in promptTasks" :key="task.id" :value="task.id">{{ task.name }}</option>
                </select>
              </label>
            </div>
            <p v-if="promptFileName" class="prompt-import__meta">已载入 {{ promptFileName }} · {{ promptTasks.length }} 个任务</p>
            <p v-if="promptError" class="prompt-import__error" role="alert">{{ promptError }}</p>
          </section>

          <form class="create-mission__form" @submit.prevent="submit">
          <div class="create-mission__workspace-body">
          <section class="mission-pane" aria-labelledby="mission-section-title">
            <div class="workspace-pane__heading">
              <span class="workspace-pane__eyebrow">MISSION</span>
              <h2 id="mission-section-title">Mission</h2>
            </div>
            <div class="mission-pane__scroll">
              <div class="mission-fields">
                <label class="field-block field-block--name" for="mission-title">
                  <span>Name</span>
                  <input id="mission-title" v-model="draft.title" class="create-mission__title" type="text" autocomplete="off" />
                </label>
                <label class="field-block field-block--brief" for="mission-goal">
                  <div class="field-block__header"><span>Objective</span><em>MISSION BRIEF</em></div>
                  <textarea id="mission-goal" v-model="draft.taskGoal" rows="8" placeholder="描述需要完成什么、关键约束以及最终希望得到什么结果。"></textarea>
                </label>
              </div>
            </div>
          </section>

          <aside class="create-mission__right-column" aria-label="Mission context and execution">
            <section class="context-panel" aria-labelledby="attachment-input-title">
              <div class="workspace-pane__heading workspace-pane__heading--row">
                <div>
                  <span class="workspace-pane__eyebrow">CONTEXT</span>
                  <h2 id="attachment-input-title">Context</h2>
                </div>
                <div class="context-panel__meta"><strong>{{ contextSummary }}</strong><label class="panel-action" for="mission-files">+ 添加上下文<input id="mission-files" type="file" accept=".pdf,.docx,.txt,.md" multiple @change="handleFiles" /></label></div>
              </div>
              <div class="context-panel__body">
                <div class="attachment-input__dropzone" :class="{ 'is-dragging': attachmentDragging }" role="region" aria-label="Context 文件区域" @dragenter.prevent="attachmentDragging = true" @dragover.prevent="attachmentDragging = true" @dragleave.prevent="attachmentDragging = false" @drop.prevent="handleDrop">
                  <div v-if="!attachments.length" class="context-empty">
                    <span class="context-empty__eyebrow">CONTEXT / READY TO ADD</span>
                    <p>为这次 Mission 提供 AgentOS 可以读取的参考材料。</p>
                    <div class="context-empty__actions"><label class="context-empty__action" for="mission-files">添加文件</label><span>支持 TXT、Markdown、PDF、DOCX · 也可直接拖入</span></div>
                  </div>
                  <article v-for="item in attachments" :key="item.localId" class="attachment-row">
                    <div class="attachment-row__file"><span class="attachment-row__file-mark" aria-hidden="true">▤</span><div><strong :title="item.file.name">{{ item.file.name }}</strong><small>{{ fileFormat(item.file.name) }} · {{ formatBytes(item.file.size) }}</small></div></div>
                    <div class="attachment-row__state" :class="`is-${item.status.toLowerCase()}`">
                      <span>{{ attachmentStatusLabel(item) }}</span>
                      <div v-if="item.status === 'UPLOADING'" class="attachment-row__progress" aria-hidden="true"><span :style="{ width: `${Math.max(0, item.progress)}%` }"></span></div>
                      <small v-if="item.error">{{ item.error }}</small>
                    </div>
                    <div class="attachment-row__actions"><button v-if="item.status === 'FAILED'" type="button" @click="retryAttachment(item)">重试</button><button class="attachment-row__remove" type="button" :disabled="item.status === 'UPLOADING' || item.status === 'PARSING'" :aria-label="`移除 ${item.file.name}`" @click="removeAttachment(item)">×</button></div>
                  </article>
                </div>
              </div>
            </section>

            <section class="execution-panel" aria-labelledby="execution-section-title">
              <div class="workspace-pane__heading">
                  <span class="workspace-pane__eyebrow">EXECUTION</span>
                  <h2 id="execution-section-title">Execution</h2>
                </div>
            <div class="execution-overview">
              <div class="execution-overview__content">
                <span class="execution-overview__eyebrow">CURRENT STRATEGY</span>
                <strong>{{ planningModeSummary }} · {{ capabilitySummary }} · {{ executionControlSummary }}</strong>
                <small>{{ contextSummary }} · {{ advancedSettingsSummary }}</small>
              </div>
              <details class="execution-config">
                <summary><span>调整策略</span></summary>
                <div class="execution-config__body">
            <div class="execution-settings">
              <div class="config-line config-line--top">
                <div class="config-line__label"><strong>Capabilities</strong><small>基础能力始终启用，可选择一个能力包。</small></div>
                <div class="capability-choice">
                  <div class="capability-baseline"><span class="capability-baseline__mark">✓</span><div><strong>Native Core</strong><small>基础运行能力 · 始终启用</small></div></div>
                  <span class="config-sub-label">Additional capability pack</span>
                  <div class="config-options" role="radiogroup" aria-label="附加能力包">
                    <button class="config-option" :class="{ 'is-selected': !draft.enabledPluginIds.length }" type="button" role="radio" :aria-checked="!draft.enabledPluginIds.length" @click="clearPlugin">不添加</button>
                    <button v-for="plugin in plugins" :key="plugin.pluginId" class="config-option" :class="{ 'is-selected': draft.enabledPluginIds.includes(plugin.pluginId) }" type="button" role="radio" :aria-checked="draft.enabledPluginIds.includes(plugin.pluginId)" @click="togglePlugin(plugin.pluginId)">{{ plugin.displayName }}</button>
                  </div>
                </div>
              </div>
              <div class="config-line">
                <div class="config-line__label"><strong>Planning</strong><small>决定 TaskPlan 如何被生成。</small></div>
                <div class="planning-choice">
                <div class="config-options" role="radiogroup" aria-label="规划方式">
                  <button class="config-option" :class="{ 'is-selected': draft.planningMode === 'dynamic' }" type="button" role="radio" :aria-checked="draft.planningMode === 'dynamic'" @click="draft.planningMode = 'dynamic'">Dynamic</button>
                  <button class="config-option" :class="{ 'is-selected': draft.planningMode === 'template_preferred' }" type="button" role="radio" :aria-checked="draft.planningMode === 'template_preferred'" @click="draft.planningMode = 'template_preferred'">Template preferred</button>
                </div>
                <p class="planning-choice__hint"><strong>{{ planningModeLabel }}</strong><span>{{ planningModeDescription }}</span></p>
              </div>
            </div>
            <div class="config-line">
              <div class="config-line__label"><strong>Execution Control</strong><small>控制高风险步骤是否进入审核节点。</small></div>
              <div class="execution-control-choice">
                <div class="config-options" role="radiogroup" aria-label="执行控制">
                  <button class="config-option" :class="{ 'is-selected': draft.reviewMode === 'auto' }" type="button" role="radio" :aria-checked="draft.reviewMode === 'auto'" @click="draft.reviewMode = 'auto'">自动执行</button>
                  <button class="config-option" :class="{ 'is-selected': draft.reviewMode === 'human_in_loop' }" type="button" role="radio" :aria-checked="draft.reviewMode === 'human_in_loop'" @click="draft.reviewMode = 'human_in_loop'">人工审核</button>
                </div>
                <p class="planning-choice__hint"><strong>{{ executionControlLabel }}</strong><span>{{ executionControlDescription }}</span></p>
              </div>
            </div>
            </div>

            <details class="advanced-config" @toggle="syncAdvancedConfigState">
              <summary>
                <span><strong>Advanced Runtime Settings</strong><small>{{ advancedSettingsSummary }}</small></span>
                <span class="advanced-config__hint">{{ advancedConfigOpen ? '收起' : '展开' }}</span>
              </summary>
              <div class="advanced-config__body">
                <div class="advanced-config__presets">
                  <span class="config-line__label">Quick preset</span>
                  <div class="config-options">
                    <button class="config-option" :class="{ 'is-selected': advancedPreset === 'fast' }" type="button" @click="applyAdvancedPreset('fast')">Fast</button>
                    <button class="config-option" :class="{ 'is-selected': advancedPreset === 'balanced' }" type="button" @click="applyAdvancedPreset('balanced')">Balanced</button>
                    <button class="config-option" :class="{ 'is-selected': advancedPreset === 'deep' }" type="button" @click="applyAdvancedPreset('deep')">Deep</button>
                  </div>
                </div>
                <div class="advanced-config__grid">
                  <label class="advanced-field">
                    <span>{{ usesGlmReasoningEffort ? 'reasoning_effort' : 'Thinking strength' }}<small v-if="usesGlmReasoningEffort">GLM-5.3-Flash · low / high / max</small></span>
                    <select v-model="thinkingSelection" aria-label="Thinking strength">
                      <option v-for="option in reasoningOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
                    </select>
                  </label>
                  <label class="advanced-field">
                    <span>Planning diversity</span>
                    <select v-model="draft.planningDiversity" aria-label="Planning diversity">
                      <option value="stable">Stable</option>
                      <option value="balanced">Balanced</option>
                      <option value="exploratory">Exploratory</option>
                    </select>
                  </label>
                  <label class="advanced-field">
                    <span>Capability profile</span>
                    <select v-model="draft.capabilityProfile" aria-label="Capability profile">
                      <option value="auto">Auto</option>
                      <option value="standard">Standard</option>
                      <option value="full">Full</option>
                    </select>
                  </label>
                  <label class="advanced-field">
                    <span>Planning seed <small>optional</small></span>
                    <input v-model.number="draft.planningSeed" aria-label="Planning seed" type="number" min="0" max="2147483647" placeholder="Auto" />
                  </label>
                  <label class="advanced-toggle">
                    <span><strong>Web search</strong><small>按模型隔离：GLM → 智谱原生 · DeepSeek → Tavily</small></span>
                    <input v-model="draft.webSearchEnabled" type="checkbox" />
                  </label>
                  <label class="advanced-toggle">
                    <span><strong>Debug trace</strong><small>记录更详细的执行诊断</small></span>
                    <input v-model="debugTraceEnabled" type="checkbox" />
                  </label>
                  <label class="advanced-toggle">
                    <span><strong>Provenance</strong><small>保留通信来源与去向</small></span>
                    <input v-model="provenanceEnabled" type="checkbox" />
                  </label>
                </div>
              </div>
            </details>

              <PluginExtensionHost :extensions="draftExtensions" :draft="draft" @update:plugin-data="draft.pluginData = $event" />
                </div>
              </details>
            </div>
          </section>
        </aside>
      </div>
      <footer class="launch-bar">
        <div class="launch-bar__summary">
          <span class="launch-bar__eyebrow">LAUNCH PREVIEW</span>
          <strong>{{ planningModeSummary }} · {{ capabilitySummary }} · {{ contextSummary }} · {{ executionControlSummary }}</strong>
          <span v-if="runSummaryIssues.length" class="launch-bar__notice" role="status">{{ runSummaryIssues.join(' · ') }}</span>
          <span v-else class="launch-bar__ready">Ready to run</span>
          <p v-if="errorMessage" class="create-mission__error" role="alert">{{ errorMessage }}</p>
        </div>
        <div class="launch-bar__actions">
          <button class="create-mission__cancel" type="button" @click="goBack">取消</button>
          <button class="create-mission__submit" type="submit" :disabled="!isReadyToRun" :aria-busy="submitting">
            <span>{{ submitting ? '正在创建 Run…' : '创建并运行' }}</span>
            <span aria-hidden="true">→</span>
          </button>
        </div>
      </footer>
      </form>
    </div>
      </main>
    </template>
  </WorkbenchLayout>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import defaultAcgPromptMarkdown from '../assets/prompts/ACG 提示词.md?raw'
import WorkbenchLayout from '@/components/workbench/WorkbenchLayout.vue'
import PluginExtensionHost from '@/features/acg/PluginExtensionHost.vue'
import { workflowApi } from '@/services/api/workflow'
import type { InputAttachment } from '@/services/api/agentos'
import { buildWorkbenchStartRequest, createNativeWorkbenchDraft, type WorkbenchDraft } from '@/features/acg/workbench'
import { pluginUiExtensions } from '@/plugins'
import { parseAcgPromptTasks, type AcgPromptTask } from '@/utils/acgPromptLibrary'
import { apiUrl } from '@/platform'
import {
  MODEL_SETTINGS_EVENT,
  glmReasoningOptions,
  isGlmAlwaysThinkingModel,
  loadModelSettings,
  thinkingOptions,
  type GlmReasoningEffort,
  type ModelSettings,
  type ThinkingMode
} from '@/config/modelSettings'

const router = useRouter()
const draft = ref<WorkbenchDraft>(createNativeWorkbenchDraft())
const submitting = ref(false)
const errorMessage = ref('')
type AttachmentDraft = { localId: string; file: File; status: 'UPLOADING' | 'PARSING' | 'READY' | 'FAILED'; progress: number; attachment?: InputAttachment; error?: string }
const attachments = ref<AttachmentDraft[]>([])
const attachmentDragging = ref(false)
const attachmentsCommitted = ref(false)
const attachmentsPending = computed(() => attachments.value.some(item => item.status !== 'READY'))
const debugTraceEnabled = ref(false)
const provenanceEnabled = ref(true)
let controller: AbortController | null = null
const promptTasks = ref<AcgPromptTask[]>(parseAcgPromptTasks(defaultAcgPromptMarkdown))
const selectedPromptTaskId = ref('')
const promptFileName = ref(promptTasks.value.length ? 'ACG 提示词.md' : '')
const promptLoading = ref(false)
const promptError = ref('')
const modelSettings = ref<ModelSettings>(loadModelSettings())
const serverSystemModel = ref('')
let systemModelsRequest = 0
const activeModel = computed(() => (
  modelSettings.value.provider === 'system' && serverSystemModel.value
    ? serverSystemModel.value
    : modelSettings.value.selectedModel
))
const usesGlmReasoningEffort = computed(() => isGlmAlwaysThinkingModel(activeModel.value))
const reasoningOptions = computed(() => usesGlmReasoningEffort.value ? glmReasoningOptions : thinkingOptions)
const thinkingSelection = computed<GlmReasoningEffort | ThinkingMode>({
  get: () => usesGlmReasoningEffort.value
    ? draft.value.reasoningEffort || modelSettings.value.reasoningEffort || 'max'
    : draft.value.thinkingMode,
  set: value => {
    if (usesGlmReasoningEffort.value) {
      const effort = value as GlmReasoningEffort
      draft.value.reasoningEffort = effort
      draft.value.thinkingMode = effort === 'low' ? 'standard' : 'deep'
      return
    }
    draft.value.reasoningEffort = undefined
    draft.value.thinkingMode = value as ThinkingMode
  }
})

type AdvancedPreset = 'fast' | 'balanced' | 'deep' | 'custom'
const advancedPreset = computed<AdvancedPreset>(() => {
  if (usesGlmReasoningEffort.value) {
    const effort = draft.value.reasoningEffort || modelSettings.value.reasoningEffort || 'max'
    if (effort === 'low' && !draft.value.webSearchEnabled && draft.value.planningDiversity === 'stable') return 'fast'
    if (effort === 'high' && draft.value.webSearchEnabled && draft.value.planningDiversity === 'balanced') return 'balanced'
    if (effort === 'max' && draft.value.webSearchEnabled && draft.value.planningDiversity === 'exploratory') return 'deep'
    return 'custom'
  }
  if (draft.value.thinkingMode === 'disabled' && !draft.value.webSearchEnabled && draft.value.planningDiversity === 'stable') return 'fast'
  if (draft.value.thinkingMode === 'standard' && draft.value.webSearchEnabled && draft.value.planningDiversity === 'balanced') return 'balanced'
  if (draft.value.thinkingMode === 'deep' && draft.value.webSearchEnabled && draft.value.planningDiversity === 'exploratory') return 'deep'
  return 'custom'
})
const advancedConfigOpen = ref(false)
const planningModeLabel = computed(() => draft.value.planningMode === 'dynamic' ? '动态规划' : '模板优先')
const planningModeDescription = computed(() => draft.value.planningMode === 'dynamic'
  ? '根据任务目标动态拆解，并选择当前可用能力。'
  : '优先复用已验证模板，未命中时自动切换动态规划。')
const advancedSettingsSummary = computed(() => [
  usesGlmReasoningEffort.value
    ? `GLM reasoning_effort: ${draft.value.reasoningEffort || modelSettings.value.reasoningEffort || 'max'}`
    : draft.value.thinkingMode === 'disabled' ? '关闭思考' : draft.value.thinkingMode === 'standard' ? '标准思考' : '深度思考',
  draft.value.webSearchEnabled ? '联网' : '仅本地',
  draft.value.planningDiversity === 'stable' ? '稳定规划' : draft.value.planningDiversity === 'balanced' ? '均衡规划' : '探索规划'
].join(' · '))
const plugins = computed(() => pluginUiExtensions.all())
const draftExtensions = computed(() => pluginUiExtensions.resolve(draft.value.enabledPluginIds))
const planningModeSummary = computed(() => draft.value.planningMode === 'dynamic' ? 'Dynamic' : 'Template preferred')
const executionControlLabel = computed(() => draft.value.reviewMode === 'auto' ? '自动执行' : '人工审核')
const executionControlSummary = computed(() => draft.value.reviewMode === 'auto' ? 'Auto Execute' : 'Human Review')
const executionControlDescription = computed(() => draft.value.reviewMode === 'auto'
  ? '运行过程中继续自动处理，不要求人工审核。'
  : '高风险步骤完成后暂停，等待人工审核。')
const capabilitySummary = computed(() => {
  const selected = draft.value.enabledPluginIds
    .map(pluginId => plugins.value.find(plugin => plugin.pluginId === pluginId)?.displayName)
    .filter((name): name is string => Boolean(name))
  return selected.length ? `Native Core · ${selected.join(' · ')}` : 'Native Core'
})
const contextSummary = computed(() => {
  if (!attachments.value.length) return 'No context files'
  const readyCount = attachments.value.filter(item => item.status === 'READY').length
  return readyCount === attachments.value.length
    ? `${readyCount} ${readyCount === 1 ? 'file' : 'files'} ready`
    : `${readyCount}/${attachments.value.length} files ready`
})
const extensionValidationMessage = computed(() => {
  for (const extension of draftExtensions.value) {
    const validation = extension.validateDraft?.(draft.value)
    if (validation && !validation.valid) return validation.message || `${extension.displayName} 配置不完整`
  }
  return ''
})
const runSummaryIssues = computed(() => {
  const issues: string[] = []
  if (!draft.value.title.trim()) issues.push('填写 Mission 名称')
  if (!draft.value.taskGoal.trim()) issues.push('补充 Objective')
  const processingCount = attachments.value.filter(item => item.status === 'UPLOADING' || item.status === 'PARSING').length
  const failedCount = attachments.value.filter(item => item.status === 'FAILED').length
  if (processingCount) issues.push(`${processingCount} 个 Context 文件仍在处理中`)
  if (failedCount) issues.push(`${failedCount} 个 Context 文件失败，请重试或移除`)
  if (extensionValidationMessage.value) issues.push(extensionValidationMessage.value)
  return issues
})
const isReadyToRun = computed(() => !submitting.value && runSummaryIssues.value.length === 0)
const constraintsText = computed({
  get: () => draft.value.constraints.join('，'),
  set: value => { draft.value.constraints = value.split(/[,，\n]/).map(item => item.trim()).filter(Boolean) }
})
const expectedArtifactsText = computed({
  get: () => draft.value.expectedArtifacts.join('，'),
  set: value => { draft.value.expectedArtifacts = value.split(/[,，\n]/).map(item => item.trim()).filter(Boolean) }
})

const applyAdvancedPreset = (preset: AdvancedPreset) => {
  draft.value.capabilityProfile = preset === 'fast' ? 'standard' : preset === 'deep' ? 'full' : 'auto'
  if (usesGlmReasoningEffort.value) {
    const effort: GlmReasoningEffort = preset === 'fast' ? 'low' : preset === 'balanced' ? 'high' : 'max'
    draft.value.reasoningEffort = effort
    draft.value.thinkingMode = effort === 'low' ? 'standard' : 'deep'
    draft.value.webSearchEnabled = preset !== 'fast'
    draft.value.planningDiversity = preset === 'fast' ? 'stable' : preset === 'balanced' ? 'balanced' : 'exploratory'
    return
  }
  if (preset === 'fast') {
    draft.value.thinkingMode = 'disabled'
    draft.value.webSearchEnabled = false
    draft.value.planningDiversity = 'stable'
    return
  }
  if (preset === 'balanced') {
    draft.value.thinkingMode = 'standard'
    draft.value.webSearchEnabled = true
    draft.value.planningDiversity = 'balanced'
    return
  }
  draft.value.thinkingMode = 'deep'
  draft.value.webSearchEnabled = true
  draft.value.planningDiversity = 'exploratory'
}

const syncAdvancedConfigState = (event: Event) => {
  const details = event.currentTarget as HTMLDetailsElement
  advancedConfigOpen.value = details.open
}

const syncDraftRuntimeSelection = () => {
  if (usesGlmReasoningEffort.value) {
    const effort = draft.value.reasoningEffort || modelSettings.value.reasoningEffort || 'max'
    draft.value.reasoningEffort = effort
    draft.value.thinkingMode = effort === 'low' ? 'standard' : 'deep'
  } else if (draft.value.reasoningEffort) {
    draft.value.reasoningEffort = undefined
  }
}

const loadSystemModel = async (): Promise<void> => {
  if (modelSettings.value.provider !== 'system' || typeof fetch !== 'function') return
  const requestId = ++systemModelsRequest
  try {
    const token = localStorage.getItem('token')
    const response = await fetch(apiUrl('/ai/chat/models'), {
      headers: token ? { Authorization: `Bearer ${token}` } : undefined
    })
    if (!response.ok || requestId !== systemModelsRequest || modelSettings.value.provider !== 'system') return
    const data = await response.json() as { models?: unknown; default_model?: unknown }
    const models = Array.isArray(data.models)
      ? data.models.filter((model): model is string => typeof model === 'string' && Boolean(model.trim()))
      : []
    const defaultModel = typeof data.default_model === 'string' && models.includes(data.default_model)
      ? data.default_model
      : models[0]
    if (defaultModel && requestId === systemModelsRequest && modelSettings.value.provider === 'system') {
      serverSystemModel.value = defaultModel
      syncDraftRuntimeSelection()
    }
  } catch {
    // Keep local model settings as the fallback when the catalog is unavailable.
  }
}

const syncModelSettings = (event: Event) => {
  const detail = (event as CustomEvent<ModelSettings>).detail
  modelSettings.value = detail
    ? { ...detail, models: [...detail.models] }
    : loadModelSettings()
  serverSystemModel.value = ''
  syncDraftRuntimeSelection()
  if (modelSettings.value.provider === 'system') void loadSystemModel()
}

watch(activeModel, syncDraftRuntimeSelection, { immediate: true })
onMounted(() => {
  window.addEventListener(MODEL_SETTINGS_EVENT, syncModelSettings)
  void loadSystemModel()
})

const handlePromptFile = async (event: Event) => {
  const input = event.currentTarget as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  promptLoading.value = true
  promptError.value = ''
  try {
    const tasks = parseAcgPromptTasks(await file.text())
    if (!tasks.length) throw new Error('没有找到可填充的结构化任务，请选择 ACG 提示词.md。')
    promptTasks.value = tasks
    selectedPromptTaskId.value = ''
    promptFileName.value = file.name
  } catch (error: any) {
    promptError.value = error?.message || '提示词文件读取失败'
  } finally {
    promptLoading.value = false
    input.value = ''
  }
}

const applySelectedPromptTask = () => {
  const task = promptTasks.value.find(item => item.id === selectedPromptTaskId.value)
  if (!task) return

  draft.value.title = task.name
  draft.value.materialText = task.materialText
  draft.value.taskGoal = task.taskGoal
  draft.value.constraints = [...task.constraints]
  draft.value.expectedArtifacts = [...task.expectedArtifacts]
  draft.value.materialIds = []
  errorMessage.value = ''
}

const togglePlugin = (pluginId: string) => {
  if (draft.value.enabledPluginIds.includes(pluginId)) {
    clearPlugin()
    return
  }
  draft.value.enabledPluginIds = [pluginId]
  const defaults = pluginUiExtensions.get(pluginId)?.createDefaults?.()
  if (!defaults) return
  const nativeDefaults = createNativeWorkbenchDraft()
  if (!draft.value.title && defaults.title) draft.value.title = defaults.title
  if (!draft.value.taskGoal && defaults.taskGoal) draft.value.taskGoal = defaults.taskGoal
  if (!draft.value.expectedArtifacts.length && defaults.expectedArtifacts) draft.value.expectedArtifacts = [...defaults.expectedArtifacts]
  if (defaults.reviewMode) draft.value.reviewMode = defaults.reviewMode
  if (defaults.capabilityProfile && draft.value.capabilityProfile === nativeDefaults.capabilityProfile) draft.value.capabilityProfile = defaults.capabilityProfile
  if (defaults.planningDiversity && draft.value.planningDiversity === nativeDefaults.planningDiversity) draft.value.planningDiversity = defaults.planningDiversity
  if (typeof defaults.webSearchEnabled === 'boolean' && draft.value.webSearchEnabled === nativeDefaults.webSearchEnabled) draft.value.webSearchEnabled = defaults.webSearchEnabled
  if (defaults.thinkingMode && draft.value.thinkingMode === nativeDefaults.thinkingMode) draft.value.thinkingMode = defaults.thinkingMode
  if (defaults.reasoningEffort && !draft.value.reasoningEffort) draft.value.reasoningEffort = defaults.reasoningEffort
  if (defaults.pluginData) draft.value.pluginData = { ...draft.value.pluginData, ...defaults.pluginData }
}

const clearPlugin = () => {
  draft.value.enabledPluginIds = []
  draft.value.pluginData = {}
  draft.value.reviewMode = 'auto'
}

const createClientRequestId = () => typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`

const extensionOf = (filename: string) => filename.includes('.') ? filename.slice(filename.lastIndexOf('.')).toLowerCase() : 'file'
const formatBytes = (bytes: number) => bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`
const fileFormat = (filename: string) => extensionOf(filename).replace('.', '').toUpperCase()
const attachmentStatusLabel = (item: AttachmentDraft) => {
  if (item.status === 'UPLOADING') return item.progress > 0 ? `正在上传 ${item.progress}%` : '正在上传'
  if (item.status === 'PARSING') return '正在解析…'
  if (item.status === 'READY') return '✓ 已就绪'
  return '失败'
}
const uploadAttachment = async (item: AttachmentDraft) => {
  item.status = 'UPLOADING'; item.progress = 0; item.error = undefined
  try {
    item.attachment = await workflowApi.uploadAttachment(item.file, { onProgress: value => { item.progress = value; if (value >= 100) item.status = 'PARSING' } })
    item.status = item.attachment.status === 'READY' ? 'READY' : 'FAILED'
    if (item.status === 'FAILED') item.error = item.attachment.parseError || '文件解析失败'
  } catch (error: any) {
    item.status = 'FAILED'
    const detail = error?.response?.data?.detail
    item.error = detail?.message || error?.response?.data?.message || error?.message || '文件上传失败'
  }
}
const addFiles = (files: File[]) => {
  const accepted = new Set(['.txt', '.md', '.pdf', '.docx'])
  for (const file of files) {
    if (!accepted.has(extensionOf(file.name))) { errorMessage.value = `不支持的文件类型：${file.name}`; continue }
    // 必须 reactive 包裹后入队：uploadAttachment 若拿到原生对象，status/progress 赋值
    // 不触发响应式更新，行状态会永远停在"上传中…"并锁死提交按钮。
    const item = reactive<AttachmentDraft>({ localId: createClientRequestId(), file, status: 'UPLOADING', progress: 0 })
    attachments.value.push(item); void uploadAttachment(item)
  }
}
const handleFiles = (event: Event) => { const input = event.currentTarget as HTMLInputElement; addFiles(Array.from(input.files || [])); input.value = '' }
const handleDrop = (event: DragEvent) => { attachmentDragging.value = false; addFiles(Array.from(event.dataTransfer?.files || [])) }
const retryAttachment = async (item: AttachmentDraft) => { if (item.attachment) { try { await workflowApi.deleteAttachment(item.attachment.attachmentId) } catch {} item.attachment = undefined }; await uploadAttachment(item) }
const removeAttachment = async (item: AttachmentDraft) => { attachments.value = attachments.value.filter(candidate => candidate.localId !== item.localId); if (item.attachment) { try { await workflowApi.deleteAttachment(item.attachment.attachmentId) } catch { ElMessage.error('附件删除失败') } } }

const submit = async () => {
  if (submitting.value) return
  if (!draft.value.title.trim()) { errorMessage.value = '请输入 Mission 名称'; return }
  if (!draft.value.taskGoal.trim()) { errorMessage.value = '请输入 Objective'; return }
  if (attachmentsPending.value) { errorMessage.value = '请等待所有附件解析完成，或移除失败的附件。'; return }
  for (const extension of draftExtensions.value) {
    const validation = extension.validateDraft?.(draft.value)
    if (validation && !validation.valid) {
      errorMessage.value = validation.message || `${extension.displayName}配置不完整`
      return
    }
  }
  submitting.value = true
  errorMessage.value = ''
  controller?.abort()
  controller = new AbortController()
  try {
    const request = buildWorkbenchStartRequest(draft.value, draftExtensions.value, createClientRequestId())
    request.attachmentIds = attachments.value.map(item => item.attachment?.attachmentId).filter((item): item is string => Boolean(item))
    request.input = {
      ...request.input,
      taskName: draft.value.title.trim(),
      debugTrace: debugTraceEnabled.value,
      lowEntropyOptions: provenanceEnabled.value ? ['trace_provenance'] : []
    }
    if (draft.value.materialText.trim()) {
      const manifest = await workflowApi.createMaterial(draft.value.materialText.trim(), 'text/plain')
      request.materialRefs = [manifest.manifestId]
      delete request.input.materialText
    }
    const run = await workflowApi.startWorkflowAsync(request, { signal: controller.signal })
    attachmentsCommitted.value = true
    await router.replace({ name: 'MissionWorkspace', params: { missionId: run.missionId }, query: { runId: run.runId } })
  } catch (error: any) {
    if (error?.name === 'CanceledError' || error?.name === 'AbortError') return
    errorMessage.value = error?.response?.data?.detail || error?.message || 'Mission 创建失败，请稍后重试。'
    ElMessage.error(errorMessage.value)
  } finally {
    submitting.value = false
  }
}

const goBack = () => { void router.replace({ name: 'AcgVisualization', query: {} }) }
onBeforeUnmount(() => {
  controller?.abort()
  systemModelsRequest += 1
  window.removeEventListener(MODEL_SETTINGS_EVENT, syncModelSettings)
  if (!attachmentsCommitted.value) for (const item of attachments.value) if (item.attachment) void workflowApi.deleteAttachment(item.attachment.attachmentId).catch(() => undefined)
})
</script>

<style scoped>
.create-mission { display: flex; flex-direction: column; width: 100%; height: 100%; min-height: 0; overflow: hidden; color: var(--text-primary); background: var(--bg-app); }
.create-mission__topbar { flex: 0 0 auto; padding: 18px clamp(22px, 6vw, 88px) 8px; }
.create-mission__scroll-region { flex: 1 1 auto; min-height: 0; overflow-y: auto; overflow-x: hidden; overscroll-behavior: contain; scrollbar-color: var(--scrollbar-thumb, var(--border-hover)) transparent; scrollbar-gutter: stable; scrollbar-width: thin; scroll-padding-block: 24px; padding: 0 clamp(22px, 6vw, 88px) 28px; }
.create-mission__back { display: inline-flex; align-items: center; gap: 8px; min-height: 30px; padding: 0; border: 0; color: var(--text-secondary); background: transparent; cursor: pointer; font: inherit; font-size: 12px; transition: color 160ms var(--ease-out), transform 160ms var(--ease-out); }
.create-mission__back:hover { color: var(--text-primary); transform: translateX(-2px); }
.create-mission__back-icon { color: var(--text-muted); font-size: 18px; line-height: 1; }
.create-mission__header, .create-mission__form { max-width: 940px; margin: 0 auto; }
.create-mission__header { padding: 24px 0 25px; border-bottom: 1px solid var(--border-light); }
.create-mission__eyebrow { color: var(--primary-color); font: 10px var(--font-mono, monospace); letter-spacing: .14em; }
.create-mission h1 { margin: 8px 0 5px; font-size: 25px; line-height: 1.2; }
.create-mission__header p { margin: 0; color: var(--text-secondary); font-size: 12px; }
.prompt-import { display: none; }
.create-section--task-options { display: none; }
.prompt-import__lead { display: flex; align-items: flex-start; gap: 12px; min-width: 0; }
.prompt-import__lead > div { min-width: 0; }
.prompt-import__eyebrow { flex: 0 0 auto; padding-top: 3px; color: var(--primary-color); font: 9px var(--font-mono, monospace); letter-spacing: .12em; }
.prompt-import__lead strong { display: block; color: var(--text-primary); font-size: 12px; }
.prompt-import__lead p { margin: 4px 0 0; color: var(--text-muted); font-size: 10px; }
.prompt-import__controls { display: flex; align-items: center; justify-content: flex-end; gap: 16px; width: max-content; max-width: 100%; min-width: 0; }
.prompt-import__file { display: inline-flex !important; align-items: center; margin: 0 !important; color: var(--primary-color) !important; cursor: pointer; font-size: 11px !important; font-weight: 600 !important; white-space: nowrap; }
.prompt-import__file:hover { color: var(--primary-hover) !important; }
.prompt-import__file input { display: none; }
.prompt-import__select { display: flex !important; align-items: center; gap: 8px; width: max-content !important; margin: 0 !important; }
.prompt-import__select > span { color: var(--text-muted); font-size: 10px; font-weight: 500; }
.prompt-import__select select { width: 248px !important; min-width: 0; max-width: 38vw; height: 32px; padding: 0 8px; border: 1px solid var(--border-light); border-radius: 4px; outline: 0; color: var(--text-primary); background: var(--bg-card); font: inherit; font-size: 11px; }
.prompt-import__select select:focus { border-color: var(--primary-color); box-shadow: 0 0 0 2px var(--primary-fade); }
.prompt-import__meta, .prompt-import__error { grid-column: 1 / -1; margin: 0; font-size: 10px; }
.prompt-import__meta { color: var(--text-muted); }
.prompt-import__error { color: var(--danger); }
.create-section { padding: 23px 0; border-bottom: 1px solid var(--border-light); }
.create-section label { display: block; margin-bottom: 9px; color: var(--text-primary); font-size: 12px; font-weight: 650; }
.create-section input[type='text'], .create-section input[type='number'], .create-section textarea, .advanced-field select, .advanced-field input { width: 100%; border: 1px solid var(--border-light); border-radius: 4px; outline: 0; color: var(--text-primary); background: var(--bg-card); font: inherit; font-size: 12px; }
.create-section input[type='text'] { height: 40px; padding: 0 11px; }
.create-section textarea { min-height: 80px; padding: 10px 11px; resize: vertical; line-height: 1.6; }
.create-section input:focus, .create-section textarea:focus, .advanced-field select:focus, .advanced-field input:focus { border-color: var(--primary-color); box-shadow: 0 0 0 2px var(--primary-fade); }
.create-section--split { display: grid; grid-template-columns: 1fr 1fr; gap: 30px; }
.create-file { display: flex !important; align-items: center; gap: 10px; margin-top: 10px; color: var(--primary-color) !important; cursor: pointer; font-weight: 500 !important; }
.create-file small { color: var(--text-muted); font-size: 10px; font-weight: 400; }
.create-file input { display: none; }
.attachment-input { display: grid; gap: 12px; }
.attachment-input__heading { display: flex; align-items: center; justify-content: space-between; gap: 20px; }
.attachment-input__heading > div { display: grid; gap: 4px; }
.attachment-input__heading label { margin: 0; }
.attachment-input__heading small { color: var(--text-muted); font-size: 10px; }
.attachment-input__add { margin: 0 !important; color: var(--primary-color) !important; cursor: pointer; font-size: 11px !important; }
.attachment-input__add input { display: none; }
.attachment-input__dropzone { min-height: 70px; padding: 10px 12px; border: 1px dashed var(--border-light); border-radius: 6px; background: color-mix(in srgb, var(--bg-card) 70%, transparent); transition: border-color 160ms var(--ease-out), background 160ms var(--ease-out); }
.attachment-input__dropzone.is-dragging { border-color: var(--primary-color); background: var(--primary-fade); }
.attachment-input__dropzone > p { margin: 14px 0; color: var(--text-muted); font-size: 11px; text-align: center; }
.attachment-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(110px, auto) auto; align-items: center; gap: 14px; min-height: 52px; }
.attachment-row + .attachment-row { border-top: 1px solid var(--border-light); }
.attachment-row__file { display: flex; align-items: center; gap: 10px; min-width: 0; }
.attachment-row__file > span { color: var(--primary-color); font-size: 17px; }
.attachment-row__file > div, .attachment-row__state { display: grid; gap: 3px; min-width: 0; }
.attachment-row__file strong { overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.attachment-row__file small, .attachment-row__state small { color: var(--text-muted); font-size: 9px; }
.attachment-row__state { color: var(--text-secondary); font: 10px var(--font-mono, monospace); }
.attachment-row__state.is-ready { color: var(--success, #35a66f); }
.attachment-row__state.is-failed, .attachment-row__state.is-failed small { color: var(--danger); }
.attachment-row__actions { display: flex; gap: 8px; }
.attachment-row__actions button { padding: 3px 0; border: 0; color: var(--text-muted); background: transparent; cursor: pointer; font-size: 10px; }
.attachment-row__actions button:hover { color: var(--text-primary); }
.attachment-row__actions button:disabled { cursor: default; opacity: .45; }
.create-section--config { display: grid; gap: 17px; }
.create-section__heading { padding-bottom: 3px; }
.create-section__heading strong, .create-section__heading span { display: block; }
.create-section__heading strong { font-size: 13px; }
.create-section__heading span { margin-top: 4px; color: var(--text-secondary); font-size: 11px; }
.config-line { display: grid; grid-template-columns: 130px minmax(0, 1fr); align-items: center; gap: 14px; min-height: 34px; }
.config-line--top { align-items: flex-start; }
.config-line__label { color: var(--text-secondary); font-size: 11px; }
.config-options { display: flex; flex-wrap: wrap; gap: 8px; }
.planning-choice { display: grid; gap: 8px; }
.planning-choice__hint { display: grid; gap: 3px; margin: 0; color: var(--text-muted); font-size: 10px; line-height: 1.45; }
.planning-choice__hint strong { color: var(--text-secondary); font-size: 11px; font-weight: 600; }
.config-option { padding: 7px 10px; border: 1px solid var(--border-light); border-radius: 4px; color: var(--text-secondary); background: transparent; cursor: pointer; font-size: 11px; transition: border-color 160ms var(--ease-out), color 160ms var(--ease-out), background 160ms var(--ease-out); }
.config-option:hover { border-color: var(--border-hover); color: var(--text-primary); }
.config-option b { margin-left: 7px; color: var(--text-muted); font-weight: 500; }
.config-option.is-selected { border-color: var(--primary-line); color: var(--primary-color); background: var(--primary-fade); }
.config-option.is-selected b { color: var(--primary-color); }
.advanced-config { margin-top: 3px; border-top: 1px solid var(--border-light); }
.advanced-config summary { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 15px 0 4px; cursor: pointer; list-style: none; }
.advanced-config summary::-webkit-details-marker { display: none; }
.advanced-config summary::after { content: '⌄'; color: var(--text-muted); font-size: 16px; transform: translateY(-2px); transition: transform 160ms var(--ease-out); }
.advanced-config[open] summary::after { transform: rotate(180deg) translateY(-2px); }
.advanced-config summary > span:first-child { display: grid; gap: 4px; }
.advanced-config summary strong { color: var(--text-primary); font-size: 12px; }
.advanced-config summary small, .advanced-config__hint { color: var(--text-muted); font-size: 10px; }
.advanced-config__hint { margin-left: auto; }
.advanced-config__body { display: grid; gap: 16px; padding: 8px 0 2px; }
.advanced-config__presets { display: grid; grid-template-columns: 130px minmax(0, 1fr); align-items: center; gap: 14px; }
.advanced-config__grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px 20px; padding-left: 144px; }
.advanced-field, .advanced-toggle { display: grid !important; gap: 7px; margin: 0 !important; }
.advanced-field > span, .advanced-toggle strong { color: var(--text-primary); font-size: 11px; font-weight: 600; }
.advanced-field > span small { color: var(--text-muted); font-size: 10px; font-weight: 400; }
.advanced-field select, .advanced-field input { height: 32px; padding: 0 8px; }
.advanced-toggle { grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 10px; }
.advanced-toggle span { display: grid; gap: 3px; }
.advanced-toggle small { color: var(--text-muted); font-size: 10px; line-height: 1.35; }
.advanced-toggle input { width: 30px; height: 18px; margin: 0; accent-color: var(--primary-color); cursor: pointer; }
.create-mission__error { margin: 18px 0 0; color: var(--danger); font-size: 12px; }
.create-mission__footer { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-top: 20px; padding: 20px 0 8px; }
.create-mission__footer-hint { color: var(--text-muted); font-size: 11px; }
.create-mission__footer-actions { display: flex; gap: 10px; }
.create-mission__cancel, .create-mission__submit { min-width: 82px; height: 38px; padding: 0 14px; border-radius: 6px; cursor: pointer; font-size: 12px; }
.create-mission__cancel { border: 1px solid var(--border-light); color: var(--text-secondary); background: transparent; }
.create-mission__cancel:hover { border-color: var(--border-hover); color: var(--text-primary); }
.create-mission__submit { display: inline-flex; align-items: center; justify-content: center; gap: 12px; min-width: 126px; border: 1px solid var(--primary-color); color: var(--on-primary, #fff); background: var(--primary-color); font-weight: 700; box-shadow: 0 8px 18px color-mix(in srgb, var(--primary-color) 20%, transparent); transition: transform 160ms var(--ease-out), background 160ms var(--ease-out), box-shadow 160ms var(--ease-out); }
.create-mission__submit:hover:not(:disabled) { background: var(--primary-hover); box-shadow: 0 11px 24px color-mix(in srgb, var(--primary-color) 28%, transparent); transform: translateY(-1px); }
.create-mission__submit:active:not(:disabled) { transform: translateY(1px); }
.create-mission__submit:disabled { opacity: .6; cursor: wait; }
@media (max-width: 720px) {
  .create-mission__topbar { padding: 14px 18px 8px; }
  .create-mission__scroll-region { padding: 0 18px 28px; scroll-padding-block: 18px; }
  .create-mission__header { padding-top: 22px; }
  .prompt-import { grid-template-columns: 1fr; gap: 13px; }
  .prompt-import__controls { align-items: stretch; justify-content: flex-start; flex-direction: column; width: 100%; gap: 11px; }
  .prompt-import__select { width: 100% !important; }
  .prompt-import__select select { width: 100% !important; max-width: none; flex: 1; }
  .create-section--split { grid-template-columns: 1fr; gap: 22px; }
  .config-line, .advanced-config__presets { grid-template-columns: 1fr; gap: 7px; }
  .advanced-config__grid { grid-template-columns: 1fr; padding-left: 0; }
  .create-mission__footer { align-items: flex-start; flex-direction: column; gap: 12px; }
  .create-mission__footer-actions { width: 100%; }
  .create-mission__cancel, .create-mission__submit { flex: 1; }
}
.create-mission__topbar { padding: 16px max(22px, calc((100vw - 1120px) / 2)) 4px; }
.create-mission__scroll-region { padding: 0 max(22px, calc((100vw - 1120px) / 2)) 40px; }
.create-mission__back { min-height: 28px; color: var(--text-muted); font-size: 12px; }
.create-mission__header, .create-mission__form { max-width: 980px; }
.create-mission__header { padding: 22px 0 30px; border-bottom: 0; }
.create-mission__eyebrow { color: var(--primary-color); font-size: 10px; letter-spacing: .16em; }
.create-mission h1 { margin: 8px 0 6px; font-size: 28px; line-height: 1.15; }
.create-mission__header p { font-size: 12px; }
.create-section { padding: 30px 0; border-bottom: 0; }
.create-section--context, .create-section--config, .run-summary { border-top: 1px solid color-mix(in srgb, var(--border-light) 62%, transparent); }
.section-heading { display: flex; align-items: flex-start; gap: 14px; margin-bottom: 22px; }
.section-heading--with-action { justify-content: space-between; gap: 24px; }
.section-heading__main { display: flex; align-items: flex-start; gap: 14px; min-width: 0; }
.section-heading__index { flex: 0 0 auto; padding-top: 2px; color: var(--primary-color); font: 10px var(--font-mono, monospace); letter-spacing: .08em; }
.section-heading h2 { margin: 0; color: var(--text-primary); font-family: var(--font-sans); font-size: 13px; font-weight: 650; letter-spacing: .01em; }
.section-heading p { margin: 5px 0 0; color: var(--text-muted); font-size: 11px; line-height: 1.5; }
.mission-fields { display: grid; gap: 20px; }
.field-block { display: grid !important; gap: 9px; margin: 0 !important; color: var(--text-primary); }
.field-block > span { color: var(--text-primary); font-size: 12px; font-weight: 600; }
.field-block > small { margin-top: -3px; color: var(--text-muted); font-size: 11px; line-height: 1.5; }
.create-section input[type='text'], .create-section input[type='number'], .create-section textarea, .advanced-field select, .advanced-field input { border-color: color-mix(in srgb, var(--border-light) 82%, transparent); border-radius: 4px; background: color-mix(in srgb, var(--bg-card) 76%, var(--bg-app)); }
.create-section input[type='text'] { height: 40px; padding: 0 11px; }
.create-section textarea { min-height: 138px; padding: 11px; resize: vertical; line-height: 1.65; }
.create-section input:focus, .create-section textarea:focus, .advanced-field select:focus, .advanced-field input:focus { border-color: var(--border-focus); box-shadow: 0 0 0 2px var(--primary-fade); }
.attachment-input { display: block; }
.attachment-input__heading { display: block; }
.attachment-input__heading > div { display: block; }
.attachment-input__heading label { margin: 0; }
.attachment-input__add { flex: 0 0 auto; margin: 1px 0 0 !important; color: var(--primary-color) !important; cursor: pointer; font-size: 11px !important; font-weight: 600 !important; white-space: nowrap; }
.attachment-input__add:hover { color: var(--primary-hover) !important; }
.attachment-input__add input { display: none; }
.attachment-input__dropzone { min-height: 78px; padding: 8px 14px; border-color: color-mix(in srgb, var(--border-light) 76%, transparent); border-radius: 5px; background: color-mix(in srgb, var(--bg-input) 72%, transparent); }
.attachment-input__dropzone.is-dragging { border-color: var(--primary-color); background: var(--primary-fade); }
.attachment-input__dropzone > p { margin: 17px 0; color: var(--text-muted); font-size: 11px; }
.attachment-row { grid-template-columns: minmax(0, 1fr) minmax(158px, auto) 34px; gap: 18px; min-height: 56px; }
.attachment-row + .attachment-row { border-top-color: color-mix(in srgb, var(--border-light) 54%, transparent); }
.attachment-row__file { gap: 10px; }
.attachment-row__file-mark { color: var(--primary-color); font-size: 15px; }
.attachment-row__file strong { font-size: 11px; font-weight: 600; }
.attachment-row__file small, .attachment-row__state small { font-size: 10px; }
.attachment-row__state { justify-items: start; min-width: 0; color: var(--text-secondary); font-size: 10px; white-space: nowrap; }
.attachment-row__state.is-ready { color: var(--success, #35a66f); }
.attachment-row__state.is-failed, .attachment-row__state.is-failed small { color: var(--danger); }
.attachment-row__progress { width: 100%; height: 3px; overflow: hidden; background: color-mix(in srgb, var(--border-light) 70%, transparent); }
.attachment-row__progress span { display: block; height: 100%; background: var(--primary-color); transition: width 160ms var(--ease-out); }
.attachment-row__actions { justify-content: flex-end; gap: 8px; }
.attachment-row__actions button { min-width: 24px; padding: 3px 0; font-size: 10px; }
.attachment-row__remove { color: var(--text-muted); font-size: 18px !important; line-height: 1; opacity: .08; transition: opacity 160ms var(--ease-out), color 160ms var(--ease-out); }
.attachment-row:hover .attachment-row__remove, .attachment-row__remove:focus-visible { opacity: 1; }
.attachment-row__remove:hover { color: var(--text-primary); }
.create-section--config { display: block; }
.execution-settings { display: grid; gap: 22px; }
.config-line { grid-template-columns: 190px minmax(0, 1fr); align-items: start; gap: 22px; min-height: 34px; }
.config-line__label { display: grid; gap: 4px; color: var(--text-primary); font-size: 11px; }
.config-line__label strong { color: var(--text-primary); font-size: 12px; font-weight: 600; }
.config-line__label small, .config-sub-label { color: var(--text-muted); font-size: 10px; line-height: 1.45; }
.capability-choice, .planning-choice, .execution-control-choice { display: grid; gap: 10px; min-width: 0; }
.capability-baseline { display: flex; align-items: center; gap: 10px; min-height: 32px; }
.capability-baseline__mark { color: var(--success); font-size: 12px; }
.capability-baseline div { display: grid; gap: 2px; }
.capability-baseline strong { color: var(--text-primary); font-size: 11px; font-weight: 600; }
.capability-baseline small { color: var(--text-muted); font-size: 10px; }
.config-sub-label { margin-top: 2px; }
.config-options { gap: 7px; }
.config-option { min-height: 32px; padding: 6px 10px; border-color: var(--border-light); border-radius: 4px; color: var(--text-secondary); font-size: 11px; }
.config-option:hover { border-color: var(--border-hover); color: var(--text-primary); background: color-mix(in srgb, var(--bg-card) 64%, transparent); }
.config-option.is-selected { border-color: var(--primary-line); color: var(--primary-color); background: var(--primary-fade); }
.config-option b { display: none; }
.planning-choice__hint { gap: 3px; margin: 0; color: var(--text-muted); font-size: 10px; line-height: 1.45; }
.planning-choice__hint strong { color: var(--text-secondary); font-size: 11px; font-weight: 600; }
.advanced-config { margin-top: 26px; border-top-color: color-mix(in srgb, var(--border-light) 62%, transparent); }
.advanced-config summary { padding: 16px 0 4px; }
.advanced-config summary strong { font-size: 12px; font-weight: 600; }
.advanced-config summary small, .advanced-config__hint { font-size: 10px; }
.advanced-config__body { gap: 18px; padding: 10px 0 2px; }
.advanced-config__presets { grid-template-columns: 190px minmax(0, 1fr); gap: 22px; }
.advanced-config__grid { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px 20px; padding-left: 212px; }
.advanced-field, .advanced-toggle { gap: 7px; }
.advanced-field > span, .advanced-toggle strong { font-size: 11px; }
.advanced-field select, .advanced-field input { height: 34px; }
.run-summary { padding-bottom: 8px; }
.run-summary__grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px; margin: 0; }
.run-summary__grid > div { min-width: 0; }
.run-summary__grid dt { margin-bottom: 5px; color: var(--text-muted); font-size: 10px; }
.run-summary__grid dd { overflow: hidden; color: var(--text-primary); font-size: 11px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.run-summary__notice { margin-top: 18px; padding-left: 12px; border-left: 2px solid var(--warning); color: var(--text-secondary); font-size: 11px; line-height: 1.5; }
.run-summary__notice strong { color: var(--warning); font-weight: 600; }
.run-summary__notice ul { margin: 4px 0 0 16px; }
.create-mission__error { margin: 18px 0 0; font-size: 11px; }
.create-mission__footer { margin-top: 24px; padding: 20px 0 8px; border-top: 1px solid color-mix(in srgb, var(--border-light) 62%, transparent); }
.create-mission__footer-hint { color: var(--text-muted); font-size: 11px; }
.create-mission__footer-actions { gap: 9px; }
.create-mission__cancel, .create-mission__submit { height: 38px; border-radius: 4px; font-size: 12px; }
.create-mission__submit { min-width: 132px; box-shadow: none; transition: background-color 160ms var(--ease-out), border-color 160ms var(--ease-out), color 160ms var(--ease-out); }
.create-mission__submit:hover:not(:disabled) { box-shadow: none; transform: none; }
.create-mission__submit:disabled { cursor: not-allowed; opacity: .42; }
.create-mission button:focus-visible, .create-mission input:focus-visible, .create-mission textarea:focus-visible, .create-mission select:focus-visible, .create-mission summary:focus-visible { outline: 2px solid var(--border-focus); outline-offset: 2px; }
@media (max-width: 760px) {
  .create-mission__topbar { padding: 14px 18px 4px; }
  .create-mission__scroll-region { padding: 0 18px 28px; }
  .create-mission__header { padding: 22px 0 26px; }
  .create-mission h1 { font-size: 26px; }
  .section-heading--with-action { align-items: flex-start; flex-direction: column; gap: 12px; }
  .attachment-input__add { margin-left: 28px !important; }
  .config-line, .advanced-config__presets { grid-template-columns: 1fr; gap: 9px; }
  .advanced-config__grid { grid-template-columns: 1fr; padding-left: 0; }
  .run-summary__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .create-mission__footer { align-items: flex-start; flex-direction: column; gap: 16px; }
  .create-mission__footer-actions { width: 100%; }
  .create-mission__cancel, .create-mission__submit { flex: 1; }
}
@media (max-width: 520px) {
  .attachment-row { grid-template-columns: minmax(0, 1fr) auto; gap: 8px 12px; }
  .attachment-row__state { grid-column: 1; grid-row: 2; }
  .attachment-row__actions { grid-column: 2; grid-row: 1 / span 2; }
  .run-summary__grid { grid-template-columns: 1fr 1fr; gap: 16px 12px; }
}
.field-block--name input { border-width: 0 0 1px !important; border-radius: 0; border-color: color-mix(in srgb, var(--border-light) 72%, transparent) !important; background: transparent !important; padding-right: 0; padding-left: 0; }
.field-block--name input:focus { border-color: var(--border-focus) !important; box-shadow: none !important; }
.field-block--brief { gap: 8px; padding: 14px 0 0 16px; border-left: 2px solid color-mix(in srgb, var(--primary-color) 58%, transparent); }
.field-block__header { display: flex; align-items: baseline; justify-content: space-between; gap: 14px; }
.field-block__header > span { color: var(--text-primary); font-size: 12px; font-weight: 600; }
.field-block__header em { color: var(--text-muted); font: 9px var(--font-mono, monospace); font-style: normal; letter-spacing: .1em; }
.field-block--brief textarea { min-height: 118px; padding: 4px 0 0; border: 0 !important; border-radius: 0; background: transparent !important; box-shadow: none !important; }
.field-block--brief textarea:focus { border: 0 !important; box-shadow: none !important; }
.attachment-input__dropzone { min-height: 0; padding: 0; border: 0; border-radius: 0; background: transparent; }
.attachment-input__dropzone.is-dragging { border: 0; background: transparent; box-shadow: inset 2px 0 0 var(--primary-color); }
.context-empty { display: grid; gap: 8px; padding: 20px 0 17px; border-top: 1px solid color-mix(in srgb, var(--border-light) 56%, transparent); border-bottom: 1px solid color-mix(in srgb, var(--border-light) 56%, transparent); }
.context-empty__eyebrow { color: var(--text-muted); font: 9px var(--font-mono, monospace); letter-spacing: .12em; }
.context-empty p { margin: 0; color: var(--text-secondary); font-size: 11px; }
.context-empty__actions { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; color: var(--text-muted); font-size: 10px; }
.context-empty__action { margin: 0 !important; padding: 0 0 2px; border-bottom: 1px solid color-mix(in srgb, var(--primary-color) 58%, transparent); color: var(--primary-color) !important; cursor: pointer; font-size: 11px !important; font-weight: 600 !important; }
.context-empty__action:hover { color: var(--primary-hover) !important; }
.execution-overview { display: grid; gap: 18px; }
.execution-overview__content { display: grid; gap: 5px; padding: 2px 0 2px; }
.execution-overview__eyebrow { color: var(--text-muted); font: 9px var(--font-mono, monospace); letter-spacing: .12em; }
.execution-overview__content strong { overflow: hidden; color: var(--text-primary); font-size: 13px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.execution-overview__content small { overflow: hidden; color: var(--text-muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.execution-config { border-top: 1px solid color-mix(in srgb, var(--border-light) 54%, transparent); }
.execution-config summary { display: flex; align-items: center; gap: 10px; padding: 12px 0 6px; color: var(--text-secondary); cursor: pointer; list-style: none; }
.execution-config summary::-webkit-details-marker { display: none; }
.execution-config summary::after { margin-left: auto; content: '⌄'; color: var(--text-muted); font-size: 14px; transform: translateY(-1px); transition: transform 160ms var(--ease-out); }
.execution-config[open] summary::after { transform: rotate(180deg) translateY(-1px); }
.execution-config summary span { color: var(--text-primary); font-size: 11px; font-weight: 600; }
.execution-config summary small { color: var(--text-muted); font-size: 10px; }
.execution-config__body { display: grid; gap: 24px; padding: 14px 0 2px; }
.execution-config__body > .extension-host { padding-top: 2px; }
.create-mission { display: block; width: 100%; height: 100%; min-height: 0; overflow: hidden; }
.create-mission__workspace { display: grid; grid-template-rows: 54px minmax(0, 1fr); width: 100%; height: 100%; min-height: 0; overflow: hidden; }
.create-mission__topbar { display: grid; grid-template-columns: minmax(160px, 1fr) auto minmax(160px, 1fr); align-items: center; gap: 18px; height: 54px; padding: 0 clamp(18px, 3vw, 42px); border-bottom: 1px solid color-mix(in srgb, var(--border-light) 65%, transparent); background: var(--bg-app); }
.create-mission__back { justify-self: start; min-height: 28px; }
.create-mission__topbar-title { display: grid; justify-items: center; gap: 3px; }
.create-mission__topbar-title h1 { margin: 0; color: var(--text-primary); font-family: var(--font-sans); font-size: 13px; font-weight: 600; line-height: 1.15; letter-spacing: .01em; }
.create-mission__topbar-mode { justify-self: end; color: var(--text-muted); font: 9px var(--font-mono, monospace); letter-spacing: .12em; }
.create-mission__form { display: grid; grid-template-rows: minmax(0, 1fr) auto; width: 100%; height: 100%; min-height: 0; max-width: none; margin: 0; }
.create-mission__workspace-body { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(320px, .85fr); min-height: 0; overflow: hidden; }
.mission-pane { display: grid; grid-template-rows: auto minmax(0, 1fr); min-width: 0; min-height: 0; padding: clamp(24px, 4vh, 48px) clamp(24px, 5vw, 76px); border-right: 1px solid color-mix(in srgb, var(--border-light) 55%, transparent); }
.create-mission__right-column { display: grid; grid-template-rows: minmax(210px, 1fr) minmax(250px, 1fr); min-width: 0; min-height: 0; overflow: hidden; }
.context-panel, .execution-panel { min-width: 0; min-height: 0; padding: clamp(20px, 3vh, 32px) clamp(20px, 3vw, 38px); }
.context-panel { display: grid; grid-template-rows: auto minmax(0, 1fr); border-bottom: 1px solid color-mix(in srgb, var(--border-light) 55%, transparent); overflow: hidden; }
.execution-panel { display: grid; grid-template-rows: auto minmax(0, 1fr); overflow: hidden; }
.workspace-pane__heading { min-width: 0; margin-bottom: 26px; }
.workspace-pane__heading--row { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.workspace-pane__eyebrow { display: block; margin-bottom: 7px; color: var(--primary-color); font: 9px var(--font-mono, monospace); letter-spacing: .14em; }
.workspace-pane__heading h2 { margin: 0; color: var(--text-primary); font-family: var(--font-sans); font-size: 15px; font-weight: 600; line-height: 1.2; }
.workspace-pane__heading p { max-width: 420px; margin: 7px 0 0; color: var(--text-muted); font-size: 11px; line-height: 1.5; }
.mission-pane__scroll { min-height: 0; overflow-y: auto; overflow-x: hidden; padding-right: 18px; scrollbar-color: var(--scrollbar-thumb, var(--border-hover)) transparent; scrollbar-width: thin; }
.mission-fields { display: grid; gap: clamp(28px, 5vh, 54px); max-width: 720px; }
.field-block--name input { height: 42px; font-size: 14px; }
.field-block--name input:focus-visible { outline: 0; outline-offset: 0; }
.field-block--brief { min-height: 0; }
.field-block--brief textarea { height: clamp(180px, 31vh, 290px); min-height: 150px; max-height: 48vh; resize: vertical; overflow-y: auto; font-size: 13px; line-height: 1.75; }
.field-block--brief small { max-width: 640px; }
.context-panel__meta { display: grid; justify-items: end; gap: 9px; min-width: 0; }
.context-panel__meta > strong { color: var(--text-secondary); font: 10px var(--font-mono, monospace); white-space: nowrap; }
.panel-action { margin: 0 !important; color: var(--primary-color) !important; cursor: pointer; font-size: 11px !important; font-weight: 600 !important; white-space: nowrap; }
.panel-action input { display: none; }
.context-panel__body { min-height: 0; overflow: hidden; }
.context-panel .attachment-input__dropzone { height: 100%; min-height: 0; overflow-y: auto; overflow-x: hidden; padding-right: 8px; scrollbar-color: var(--scrollbar-thumb, var(--border-hover)) transparent; scrollbar-width: thin; }
.context-panel .context-empty { min-height: 150px; align-content: center; }
.context-panel .attachment-row { grid-template-columns: minmax(0, 1fr) minmax(126px, auto) 26px; }
.execution-panel .workspace-pane__heading { margin-bottom: 18px; }
.execution-panel .execution-overview { min-height: 0; overflow-y: auto; padding-right: 8px; scrollbar-color: var(--scrollbar-thumb, var(--border-hover)) transparent; scrollbar-width: thin; }
.execution-overview__content strong { white-space: normal; }
.execution-config__body { min-height: 0; }
.execution-config[open] .execution-config__body { max-height: min(430px, 55vh); overflow-y: auto; padding-right: 8px; scrollbar-color: var(--scrollbar-thumb, var(--border-hover)) transparent; scrollbar-width: thin; }
.execution-panel .config-line { grid-template-columns: minmax(130px, .7fr) minmax(0, 1.3fr); gap: 14px; }
.execution-panel .advanced-config__presets { grid-template-columns: minmax(130px, .7fr) minmax(0, 1.3fr); gap: 14px; }
.execution-panel .advanced-config__grid { grid-template-columns: repeat(2, minmax(0, 1fr)); padding-left: 0; }
.launch-bar { display: flex; align-items: center; justify-content: space-between; gap: 24px; min-height: 72px; padding: 12px clamp(18px, 3vw, 42px); border-top: 1px solid color-mix(in srgb, var(--border-light) 68%, transparent); background: color-mix(in srgb, var(--bg-app) 94%, var(--bg-sidebar)); }
.launch-bar__summary { display: grid; gap: 3px; min-width: 0; }
.launch-bar__eyebrow { color: var(--text-muted); font: 9px var(--font-mono, monospace); letter-spacing: .13em; }
.launch-bar__summary strong { overflow: hidden; color: var(--text-primary); font-size: 11px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.launch-bar__ready { color: var(--success); font-size: 10px; }
.launch-bar__notice { overflow: hidden; color: var(--warning); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.launch-bar__actions { display: flex; flex: 0 0 auto; gap: 9px; }
.launch-bar .create-mission__footer-hint { display: none; }
.launch-bar .create-mission__submit { min-width: 132px; }
.launch-bar .create-mission__error { margin: 3px 0 0; font-size: 10px; }
@media (max-width: 900px) {
  .create-mission__workspace-body { grid-template-columns: 1fr; grid-template-rows: minmax(360px, .9fr) minmax(430px, 1.1fr); overflow-y: auto; overflow-x: hidden; }
  .mission-pane { min-height: 360px; border-right: 0; border-bottom: 1px solid color-mix(in srgb, var(--border-light) 55%, transparent); }
  .create-mission__right-column { grid-template-rows: minmax(260px, .8fr) minmax(340px, 1.2fr); min-height: 600px; }
}
@media (max-width: 620px) {
  .create-mission__topbar { grid-template-columns: auto 1fr; padding: 0 16px; }
  .create-mission__topbar-title { justify-items: start; }
  .create-mission__topbar-mode { display: none; }
  .mission-pane { padding: 22px 20px; }
  .context-panel, .execution-panel { padding: 22px 20px; }
  .workspace-pane__heading--row { gap: 12px; }
  .context-panel__meta { justify-items: start; }
  .launch-bar { align-items: stretch; flex-direction: column; gap: 12px; padding: 12px 16px; }
  .launch-bar__actions { width: 100%; }
  .launch-bar__actions button { flex: 1; }
}
</style>
