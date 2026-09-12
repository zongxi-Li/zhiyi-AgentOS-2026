<template>
  <WorkbenchLayout :show-left="false" :show-right="false" storage-key="zhiyi.create-mission.layout.v1">
    <template #main>
      <main class="create-mission" aria-label="Create Mission">
        <div class="create-mission__topbar">
          <button class="create-mission__back" type="button" @click="goBack">
            <span class="create-mission__back-icon" aria-hidden="true">←</span>
            <span>返回项目</span>
          </button>
        </div>
        <div class="create-mission__scroll-region" role="region" aria-label="新建工程内容">
          <header class="create-mission__header">
            <span class="create-mission__eyebrow">CREATE MISSION</span>
            <h1>新建工程</h1>
            <p>创建一个长期稳定的 Mission，并立即启动首个 Run。</p>
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
          <section class="create-section">
            <label for="mission-title">项目名称</label>
            <input id="mission-title" v-model="draft.title" class="create-mission__title" type="text" placeholder="例如：IC-200 智能装配生产线实施方案" autocomplete="off" />
          </section>

          <section class="create-section create-section--split">
            <div v-if="false">
              <label for="mission-material">任务材料</label>
              <textarea v-if="false" id="mission-material" v-model="draft.materialText" rows="7"></textarea>
            </div>
            <div>
              <label for="mission-goal">项目目标</label>
              <textarea id="mission-goal" v-model="draft.taskGoal" rows="7" placeholder="描述目标、范围和成功标准"></textarea>
            </div>
          </section>

          <section class="create-section attachment-input" aria-labelledby="attachment-input-title">
            <div class="attachment-input__heading">
              <div><label id="attachment-input-title">Attachments</label><small>TXT、Markdown、PDF、DOCX</small></div>
              <label class="attachment-input__add" for="mission-files">+ Add files<input id="mission-files" type="file" accept=".pdf,.docx,.txt,.md" multiple @change="handleFiles" /></label>
            </div>
            <div class="attachment-input__dropzone" :class="{ 'is-dragging': attachmentDragging }" @dragenter.prevent="attachmentDragging = true" @dragover.prevent="attachmentDragging = true" @dragleave.prevent="attachmentDragging = false" @drop.prevent="handleDrop">
              <p v-if="!attachments.length">拖拽文件到此处，或点击 Add files。文件会先上传并解析，再随 Mission 提交。</p>
              <article v-for="item in attachments" :key="item.localId" class="attachment-row">
                <div class="attachment-row__file"><span aria-hidden="true">▤</span><div><strong>{{ item.file.name }}</strong><small>{{ formatBytes(item.file.size) }} · {{ item.file.type || extensionOf(item.file.name) }}</small></div></div>
                <div class="attachment-row__state" :class="`is-${item.status.toLowerCase()}`"><span>{{ item.status === 'UPLOADING' ? (item.progress > 0 ? `${item.progress}%` : '上传中…') : item.status === 'PARSING' ? '解析中…' : item.status }}</span><small v-if="item.error">{{ item.error }}</small></div>
                <div class="attachment-row__actions"><button v-if="item.status === 'FAILED'" type="button" @click="retryAttachment(item)">重试</button><button type="button" :disabled="item.status === 'UPLOADING' || item.status === 'PARSING'" @click="removeAttachment(item)">删除</button></div>
              </article>
            </div>
          </section>

          <section v-if="false" class="create-section create-section--split create-section--task-options">
            <div>
              <label for="mission-constraints">执行约束</label>
              <textarea v-if="false" id="mission-constraints" v-model="constraintsText" rows="3"></textarea>
            </div>
            <div>
              <label for="mission-artifacts">预期交付物</label>
              <textarea v-if="false" id="mission-artifacts" v-model="expectedArtifactsText" rows="3"></textarea>
            </div>
          </section>

          <section class="create-section create-section--config">
            <div class="create-section__heading">
              <div><strong>Runtime Configuration</strong><span>能力包与本次 Run 的规划、审核策略</span></div>
            </div>
            <div class="config-line config-line--top">
              <span class="config-line__label">Capabilities</span>
              <div class="config-options">
                <button class="config-option" :class="{ 'is-selected': !draft.enabledPluginIds.length }" type="button" @click="clearPlugin">Native Core <b>✓</b></button>
                <button v-for="plugin in plugins" :key="plugin.pluginId" class="config-option" :class="{ 'is-selected': draft.enabledPluginIds.includes(plugin.pluginId) }" type="button" @click="togglePlugin(plugin.pluginId)">{{ plugin.displayName }} <b>{{ draft.enabledPluginIds.includes(plugin.pluginId) ? '✓' : '○' }}</b></button>
              </div>
            </div>
            <div class="config-line">
              <span class="config-line__label">Planning</span>
              <div class="planning-choice">
                <div class="config-options" role="radiogroup" aria-label="规划方式">
                  <button class="config-option" :class="{ 'is-selected': draft.planningMode === 'dynamic' }" type="button" role="radio" :aria-checked="draft.planningMode === 'dynamic'" @click="draft.planningMode = 'dynamic'">Dynamic</button>
                  <button class="config-option" :class="{ 'is-selected': draft.planningMode === 'template_preferred' }" type="button" role="radio" :aria-checked="draft.planningMode === 'template_preferred'" @click="draft.planningMode = 'template_preferred'">Template preferred</button>
                </div>
                <p class="planning-choice__hint"><strong>{{ planningModeLabel }}</strong><span>{{ planningModeDescription }}</span></p>
              </div>
            </div>
            <div class="config-line">
              <span class="config-line__label">Review</span>
              <div class="config-options">
                <button class="config-option" :class="{ 'is-selected': draft.reviewMode === 'auto' }" type="button" @click="draft.reviewMode = 'auto'">Auto</button>
                <button class="config-option" :class="{ 'is-selected': draft.reviewMode === 'human_in_loop' }" type="button" @click="draft.reviewMode = 'human_in_loop'">Human review</button>
              </div>
            </div>

            <details class="advanced-config" @toggle="syncAdvancedConfigState">
              <summary>
                <span><strong>更多规划设置</strong><small>{{ advancedSettingsSummary }}</small></span>
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
          </section>

          <p v-if="errorMessage" class="create-mission__error" role="alert">{{ errorMessage }}</p>
          <footer class="create-mission__footer">
            <!-- <span class="create-mission__footer-hint">创建 Mission 后立即启动首个 Run</span> -->
            <div class="create-mission__footer-actions">
              <button class="create-mission__cancel" type="button" @click="goBack">取消</button>
              <button class="create-mission__submit" type="submit" :disabled="submitting || attachmentsPending" :aria-busy="submitting">
                <span>{{ submitting ? '正在启动…' : '启动任务' }}</span>
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
  if (!draft.value.title.trim()) { errorMessage.value = '请输入项目名称'; return }
  if (!draft.value.taskGoal.trim()) { errorMessage.value = '请输入项目目标'; return }
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
</style>
