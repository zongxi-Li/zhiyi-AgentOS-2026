<template>
  <div class="create-mission" @dragenter.prevent="attachmentDragging = true" @dragover.prevent="attachmentDragging = true"
    @dragleave.prevent="attachmentDragging = false" @drop.prevent="handleDrop">
    <WorkbenchLayout :show-left="false" :show-right="true" shared-dock-geometry
      :right-pane-min-width="280" :right-pane-default-width="320" :right-pane-max-width="960"
      storage-key="zhiyi.mission.workspace.layout.v3">
      <template #main>
        <section class="mission-canvas" aria-label="工作台">
          <header class="mission-canvas__header">
            <button class="create-mission__back" type="button" @click="goBack">← 返回项目</button>
            <span class="mission-canvas__path">{{ workspaceState.workspaceRoot }}</span>
          </header>
          <div class="mission-canvas__empty"><img :src="activePack.mark" alt="" aria-hidden="true" /></div>
        </section>
      </template>
      <template #right>
        <WorkbenchAuxiliarySidebar :view="copilotView">
          <AcgCopilotPanel :create-task="createTask" :creation-disabled="!isReadyToRun"
            :creation-pending="submitting" :initial-draft="draft.taskGoal"
            @draft-change="draft.taskGoal = $event">
            <template #creation-status>
              <div v-if="pendingLaunch" class="pending-launch" role="status">
                上次提交的结果待确认。
                <button type="button" :disabled="submitting" @click="resumePendingLaunch">核对并恢复原提交</button>
              </div>
            </template>
            <template #composer-context>
            <div v-if="desktopWorkspaceRequired" class="mission-workspace">
              <NativeWorkspacePicker @state-change="workspaceState = $event" />
              <span class="mission-workspace__path" aria-label="当前工作区目录" :title="workspaceState.pendingPath || workspaceState.workspaceRoot">
                {{ workspaceState.pendingPath || workspaceState.workspaceRoot || '尚未选择工作区' }}
              </span>
            </div>
              <div v-if="attachments.length" class="composer-attachments">
                <article v-for="item in attachments" :key="item.localId" class="attachment-row">
                  <span class="attachment-row__name" :title="item.file.name">{{ item.file.name }}</span>
                  <small class="attachment-row__metadata">{{ fileFormat(item.file.name) }} · {{ formatBytes(item.file.size) }}</small>
                  <small :class="{ 'is-error': item.status === 'FAILED' }">{{ attachmentStatusLabel(item) }}</small>
                  <button v-if="item.status === 'FAILED'" type="button" @click="retryAttachment(item)">重试</button>
                  <button type="button" :disabled="item.status === 'UPLOADING' || item.status === 'PARSING'"
                    :aria-label="'移除 ' + item.file.name" @click="removeAttachment(item)">×</button>
                  <span v-if="item.error" class="attachment-row__error">{{ item.error }}</span>
                </article>
              </div>
            </template>
            <template #creation-tools>
              <label class="composer-tool composer-attach" for="mission-files" tabindex="0"
                @keydown.enter.prevent="attachmentInput?.click()" @keydown.space.prevent="attachmentInput?.click()"
                title="添加参考文件（TXT、Markdown、PDF、DOCX）">
                <span aria-hidden="true">＋</span><span class="sr-only">添加参考文件</span>
                <input ref="attachmentInput" id="mission-files" type="file" accept=".pdf,.docx,.txt,.md" multiple @change="handleFiles" />
              </label>
                <details class="composer-settings">
                  <summary class="composer-tool" aria-label="任务设置" title="任务设置">⚙</summary>
                  <div class="composer-settings__panel">
                    <h2>任务设置</h2>
                    <div class="execution-settings">
                      <label class="setting-field"><span>规划方式</span>
                        <select v-model="draft.planningMode" aria-label="规划方式"><option value="dynamic">动态规划</option><option value="template_preferred">模板优先</option></select>
                      </label>
                      <div class="setting-field"><span>执行审核</span>
                        <div class="config-options">
                          <button class="config-option" :class="{ 'is-selected': draft.reviewMode === 'auto' }" type="button" @click="draft.reviewMode = 'auto'">自动处理审核</button>
                          <button class="config-option" :class="{ 'is-selected': draft.reviewMode === 'human_in_loop' }" type="button" @click="draft.reviewMode = 'human_in_loop'">人工审核</button>
                        </div>
                        <small>{{ executionControlDescription }}</small>
                      </div>
                      <label class="setting-field"><span>附加能力包</span>
                        <select v-model="selectedPlugin" aria-label="附加能力包"><option value="">不添加</option><option v-for="plugin in plugins" :key="plugin.pluginId" :value="plugin.pluginId">{{ plugin.displayName }}</option></select>
                      </label>
                    </div>
                    <h3>高级运行设置</h3>
                    <div class="config-options">
                      <button v-for="preset in runtimePresetOptions" :key="preset.value" class="config-option" :class="{ 'is-selected': advancedPreset === preset.value }" type="button" @click="applyAdvancedPreset(preset.value)">{{ preset.label }}</button>
                    </div>
                    <label class="setting-field"><span>推理强度 · {{ activeModel }}</span>
                      <select v-model="thinkingSelection" aria-label="Thinking strength"><option v-for="option in reasoningOptions" :key="option.value" :value="option.value">{{ option.label }}</option></select>
                    </label>
                    <label class="setting-field"><span>规划多样性</span>
                      <select v-model="draft.planningDiversity" aria-label="Planning diversity"><option value="stable">稳定</option><option value="balanced">均衡</option><option value="exploratory">探索</option></select>
                    </label>
                    <label class="setting-field"><span>能力覆盖范围</span>
                      <select v-model="draft.capabilityProfile" aria-label="Capability profile"><option value="auto">自动选择</option><option value="standard">标准</option><option value="full">完整</option></select>
                    </label>
                    <label class="setting-field"><span>规划随机种子</span><input v-model.number="draft.planningSeed" aria-label="Planning seed" type="number" min="0" max="9007199254740991" step="1" placeholder="自动" /></label>
                    <label class="setting-toggle"><input v-model="draft.webSearchEnabled" type="checkbox" />联网检索</label>
                    <PluginExtensionHost :extensions="draftExtensions" :draft="draft" @update:plugin-data="draft.pluginData = $event" />
                  </div>
                </details>
                <span class="composer-model" :title="activeModel">{{ activeModel }}</span>
                <select v-model="thinkingSelection" class="composer-effort" aria-label="输入区推理强度">
                  <option v-for="option in reasoningOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
                </select>
            </template>
            <template #creation-notice>
              <p v-if="errorMessage" class="composer-notice is-error" role="alert">{{ errorMessage }}</p>
              <p v-else-if="workspaceIssue" class="composer-notice" role="status">{{ workspaceIssue }}</p>
              <p v-else-if="runtimeSettingsIssue" class="composer-notice is-error" role="status">{{ runtimeSettingsIssue }}</p>
            </template>
          </AcgCopilotPanel>
        </WorkbenchAuxiliarySidebar>
      </template>
    </WorkbenchLayout>
  </div>
</template>

<script setup lang="ts">
import { localFetch } from '@/platform/api'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import WorkbenchLayout from '@/components/workbench/WorkbenchLayout.vue'
import AcgCopilotPanel from '@/components/workbench/AcgCopilotPanel.vue'
import WorkbenchAuxiliarySidebar from '@/components/workbench/WorkbenchAuxiliarySidebar.vue'
import { copilotContribution } from '@/workbench/contributions/copilot'
import { useBrand } from '@/features/brand/useBrand'
import NativeWorkspacePicker from '@/components/platform/NativeWorkspacePicker.vue'
import type { NativeWorkspaceState } from '@/components/platform/workspaceState'
import { presetReasoningOption, type RuntimePreset } from '@/features/mission/runtimePresets'
import PluginExtensionHost from '@/features/acg/PluginExtensionHost.vue'
import { workflowApi } from '@/services/api/workflow'
import type { InputAttachment } from '@/services/api/agentos'
import { createNativeWorkbenchDraft, restoreWorkbenchDraft, type WorkbenchDraft } from '@/features/acg/workbench'
import { workbenchLaunchCommand } from '@/features/mission/command'
import { createMissionLaunchAttempt } from '@/features/mission/launchAttempt'
import { pluginUiExtensions } from '@/plugins'
import { apiUrl, platform } from '@/platform'
import { plainMissionTitle } from '@/utils/missionTitle'
import {
  MODEL_SETTINGS_EVENT,
  capabilityFromPayload,
  defaultReasoningEffortFromCapability,
  effortValuesFromOptions,
  fetchModelCapability,
  isEffortKindOption,
  loadModelSettings,
  reasoningOptionsFromCapability,
  thinkingOptions,
  type ReasoningEffort,
  type ModelCapability,
  type ModelSettings,
  type ThinkingMode
} from '@/config/modelSettings'

const router = useRouter()
const copilotView = copilotContribution.auxiliaryViews![0]!
const { activePack } = useBrand()
const draft = ref<WorkbenchDraft>(createNativeWorkbenchDraft())
const submitting = ref(false)
const errorMessage = ref('')
type AttachmentDraft = { localId: string; file: File; status: 'UPLOADING' | 'PARSING' | 'READY' | 'FAILED'; progress: number; attachment?: InputAttachment; error?: string }
const attachments = ref<AttachmentDraft[]>([])
const attachmentDragging = ref(false)
const attachmentInput = ref<HTMLInputElement | null>(null)
const attachmentsCommitted = ref(false)
const attachmentsPending = computed(() => attachments.value.some(item => item.status !== 'READY'))
const desktopWorkspaceRequired = platform.platform === 'desktop'
const workspaceState = ref<NativeWorkspaceState>({ loading: true, trusted: false,
  workspaceId: '', workspaceRoot: '', pendingPath: '', error: '' })
const workspaceIssue = computed(() => {
  if (!desktopWorkspaceRequired) return ''
  if (workspaceState.value.loading) return '正在确认工作区授权状态'
  if (workspaceState.value.pendingPath) return '请先信任所选工作区'
  if (!workspaceState.value.trusted) return workspaceState.value.error || '请选择并信任工作区后再创建任务'
  return ''
})
const runtimeSettingsIssue = computed(() => {
  const seed: unknown = draft.value.planningSeed
  return seed !== null && seed !== '' && (typeof seed !== 'number' || !Number.isSafeInteger(seed) || seed < 0)
    ? '规划种子需为 0 到 9007199254740991 之间的整数' : ''
})
let controller: AbortController | null = null
const modelSettings = ref<ModelSettings>(loadModelSettings())
const serverSystemModel = ref('')
let systemModelsRequest = 0
const activeModel = computed(() => (
  modelSettings.value.provider === 'system' && serverSystemModel.value
    ? serverSystemModel.value
    : modelSettings.value.selectedModel
))
const modelCapability = ref<ModelCapability | null>(null)
const reasoningOptions = computed(() => reasoningOptionsFromCapability(modelCapability.value))
const usesEffortOptions = computed(() => isEffortKindOption(reasoningOptions.value))
const effortOptions = computed(() => effortValuesFromOptions(reasoningOptions.value))
const thinkingSelection = computed<ReasoningEffort | ThinkingMode>({
  get: () => {
    if (usesEffortOptions.value) {
      const stored = draft.value.reasoningEffort
      if (stored && effortOptions.value.includes(stored)) return stored as ReasoningEffort
      if (draft.value.thinkingMode === 'disabled' && reasoningOptions.value.some(option => option.value === 'disabled')) {
        return 'disabled'
      }
      if (draft.value.thinkingMode === 'standard' && effortOptions.value.includes('low')) return 'low'
      if (draft.value.thinkingMode === 'deep' && effortOptions.value.includes('max')) return 'max'
      return defaultReasoningEffortFromCapability(modelCapability.value, reasoningOptions.value) as ReasoningEffort
    }
    return draft.value.thinkingMode
  },
  set: value => {
    const selected = reasoningOptions.value.find(option => option.value === value)
    if (selected?.kind === 'effort') {
      const effort = value as ReasoningEffort
      draft.value.reasoningEffort = effort
      draft.value.thinkingMode = effort === 'low' ? 'standard' : 'deep'
      return
    }
    draft.value.reasoningEffort = undefined
    draft.value.thinkingMode = value as ThinkingMode
  }
})

type AdvancedPreset = RuntimePreset | 'custom'
const advancedPreset = computed<AdvancedPreset>(() => {
  return (['fast', 'balanced', 'deep'] as const).find(preset =>
    thinkingSelection.value === presetReasoningOption(reasoningOptions.value, preset, modelCapability.value)?.value
    && draft.value.webSearchEnabled === (preset !== 'fast')
    && draft.value.capabilityProfile === (preset === 'fast' ? 'standard' : preset === 'deep' ? 'full' : 'auto')
    && draft.value.planningDiversity === (preset === 'fast' ? 'stable' : preset === 'balanced' ? 'balanced' : 'exploratory')) || 'custom'
})
const plugins = computed(() => pluginUiExtensions.all())
const draftExtensions = computed(() => pluginUiExtensions.resolve(draft.value.enabledPluginIds))
const executionControlDescription = computed(() => draft.value.reviewMode === 'auto'
  ? '正式任务先接受规划；签发许可后仍需明确点击执行。运行中自动处理审核。'
  : '每个执行步骤完成后暂停，等待人工审核；最终交付须经批准。')
const extensionValidationMessage = computed(() => {
  for (const extension of draftExtensions.value) {
    const validation = extension.validateDraft?.(draft.value)
    if (validation && !validation.valid) return validation.message || `${extension.displayName} 配置不完整`
  }
  return ''
})
const runSummaryIssues = computed(() => {
  const issues: string[] = []
  if (!draft.value.taskGoal.trim()) issues.push('请输入任务目标')
  const processingCount = attachments.value.filter(item => item.status === 'UPLOADING' || item.status === 'PARSING').length
  const failedCount = attachments.value.filter(item => item.status === 'FAILED').length
  if (processingCount) issues.push(`${processingCount} 个 Context 文件仍在处理中`)
  if (failedCount) issues.push(`${failedCount} 个 Context 文件失败，请重试或移除`)
  if (extensionValidationMessage.value) issues.push(extensionValidationMessage.value)
  if (workspaceIssue.value) issues.push(workspaceIssue.value)
  if (runtimeSettingsIssue.value) issues.push(runtimeSettingsIssue.value)
  return issues
})
const isReadyToRun = computed(() => !submitting.value && runSummaryIssues.value.length === 0)

const automaticMissionTitle = (objective: string) => plainMissionTitle(objective, 'AI Mission').slice(0, 80)

const applyAdvancedPreset = (preset: RuntimePreset) => {
  draft.value.capabilityProfile = preset === 'fast' ? 'standard' : preset === 'deep' ? 'full' : 'auto'
  const option = presetReasoningOption(reasoningOptions.value, preset, modelCapability.value)
  if (option) thinkingSelection.value = option.value
  draft.value.webSearchEnabled = preset !== 'fast'
  draft.value.planningDiversity = preset === 'fast' ? 'stable' : preset === 'balanced' ? 'balanced' : 'exploratory'
}

const syncDraftRuntimeSelection = () => {
  if (usesEffortOptions.value) {
    const hasDisabledOption = reasoningOptions.value.some(option => option.value === 'disabled')
    const storedEffort = draft.value.reasoningEffort || modelSettings.value.reasoningEffort
    if (!storedEffort && hasDisabledOption && draft.value.thinkingMode === 'disabled') {
      draft.value.reasoningEffort = undefined
      return
    }
    const effort = (storedEffort && effortOptions.value.includes(storedEffort) ? storedEffort
      : defaultReasoningEffortFromCapability(modelCapability.value, reasoningOptions.value)) as ReasoningEffort
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

    const response = await localFetch(apiUrl('/ai/chat/models'), {
    })
    if (!response.ok || requestId !== systemModelsRequest || modelSettings.value.provider !== 'system') return
    const data = await response.json() as { models?: unknown; default_model?: unknown; capabilities?: unknown }
    const models = Array.isArray(data.models)
      ? data.models.filter((model): model is string => typeof model === 'string' && Boolean(model.trim()))
      : []
    const defaultModel = typeof data.default_model === 'string' && models.includes(data.default_model)
      ? data.default_model
      : models[0]
    if (defaultModel && requestId === systemModelsRequest && modelSettings.value.provider === 'system') {
      serverSystemModel.value = defaultModel
      const entry = data.capabilities && typeof data.capabilities === 'object'
        ? (data.capabilities as Record<string, unknown>)[defaultModel]
        : undefined
      modelCapability.value = capabilityFromPayload(entry)
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
  modelCapability.value = null
  syncDraftRuntimeSelection()
  if (modelSettings.value.provider === 'system') void loadSystemModel()
}

let capabilityRequest = 0
watch([activeModel, () => modelSettings.value.provider, () => modelSettings.value.baseUrl], ([model, provider, baseUrl]) => {
  const requestId = ++capabilityRequest
  if (provider !== 'system') modelCapability.value = null
  syncDraftRuntimeSelection()
  if (model && provider !== 'system') {
    // 非系统供应商：按需单查模型能力（system 由 loadSystemModel 的目录带回）。
    void fetchModelCapability(model, baseUrl).then(capability => {
      if (requestId === capabilityRequest) {
        modelCapability.value = capability
        syncDraftRuntimeSelection()
      }
    })
  }
}, { immediate: true })
onMounted(() => {
  window.addEventListener(MODEL_SETTINGS_EVENT, syncModelSettings)
  void loadSystemModel()
})

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

const selectedPlugin = computed({
  get: () => draft.value.enabledPluginIds[0] || '',
  set: (id: string) => { if (id) togglePlugin(id); else clearPlugin() }
})
const runtimePresetOptions: { value: RuntimePreset; label: string }[] = [
  { value: 'fast', label: '快速' }, { value: 'balanced', label: '均衡' }, { value: 'deep', label: '深入' }
]
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

const launchAttempt = createMissionLaunchAttempt({ slot: 'workbench' })
const restoredLaunch = launchAttempt.pending()
const pendingLaunch = ref(restoredLaunch)
if (restoredLaunch) restoreWorkbenchDraft(draft.value, {
  runId: '', title: restoredLaunch.commandSnapshot.title,
  reviewMode: restoredLaunch.commandSnapshot.reviewMode,
  enabledPluginIds: restoredLaunch.commandSnapshot.enabledPluginIds || [],
  input: restoredLaunch.commandSnapshot.input
}, [])
const resumePendingLaunch = async () => {
  if (submitting.value || !pendingLaunch.value) return
  submitting.value = true
  try {
    const result = await launchAttempt.resume(pendingLaunch.value.operationId)
    await router.replace({ name: 'MissionWorkspace', params: { missionId: result.missionId }, query: { runId: result.runId, inspector: 'copilot' } })
    launchAttempt.complete(result.clientRequestId)
    pendingLaunch.value = null
  } catch (error: any) { errorMessage.value = error?.message || '原提交核对失败，身份已保留。' }
  finally { submitting.value = false }
}
const submit = async () => {
  if (submitting.value) return
  if (!draft.value.taskGoal.trim()) { errorMessage.value = '请输入任务目标'; return }
  if (workspaceIssue.value || runtimeSettingsIssue.value) {
    errorMessage.value = workspaceIssue.value || runtimeSettingsIssue.value
    return
  }
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
    if (desktopWorkspaceRequired) {
      const expected = { ...workspaceState.value }
      const response = await localFetch(apiUrl('/api/agentos/v2/workspaces/current'), {
        signal: controller.signal, cache: 'no-store'
      })
      if (!response.ok) throw new Error('无法复核工作区授权，请重新选择并信任工作区。')
      const current = await response.json()
      if (current.revoked || current.selected === false || !current.workspaceId
        || current.workspaceId !== expected.workspaceId || current.workspaceRoot !== expected.workspaceRoot) {
        window.dispatchEvent(new Event('workspace-authorization-changed'))
        throw new Error('工作区授权已变化，请确认当前目录后重新创建任务。')
      }
    }
    const command = workbenchLaunchCommand(
      { ...draft.value, title: draft.value.title.trim() || automaticMissionTitle(draft.value.taskGoal) },
      draftExtensions.value,
      {
        attachmentIds: [...(restoredLaunch?.commandSnapshot.attachmentIds || []), ...attachments.value.map(item => item.attachment?.attachmentId).filter((item): item is string => Boolean(item))],
      }
    )
    // Once sent, a failed response can still mean the Mission owns these files.
    attachmentsCommitted.value = true
    const run = await launchAttempt.launch(command, { signal: controller.signal })
    await router.replace({ name: 'MissionWorkspace', params: { missionId: run.missionId }, query: { runId: run.runId, inspector: 'copilot' } })
    launchAttempt.complete(run.clientRequestId)
  } catch (error: any) {
    if (error?.name === 'CanceledError' || error?.name === 'AbortError') return
    const detail = error?.response?.data?.detail
    pendingLaunch.value = launchAttempt.pending()
    errorMessage.value = (typeof detail === 'string' ? detail : error?.response?.data?.message) || error?.message || 'Mission 创建失败，请稍后重试。'
    ElMessage.error(errorMessage.value)
  } finally {
    submitting.value = false
  }
}

const createTask = async (message: string) => {
  draft.value.taskGoal = message
  await submit()
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
.create-mission { display: block; height: 100%; min-height: 0; color: var(--wb-text); background: var(--wb-surface-shell); }
.mission-canvas { height: 100%; display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.mission-canvas__header { display: flex; align-items: center; gap: 20px; height: var(--editor-rail-height, var(--wb-tab-height, 36px)); flex-shrink: 0; padding: 0 12px; }
.create-mission__back { padding: 6px 0; border: 0; background: transparent; color: var(--text-secondary); font: inherit; font-size: 12px; cursor: pointer; white-space: nowrap; }
.mission-canvas__path { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-muted); font-size: 11px; }
.mission-canvas__empty { display: grid; flex: 1; min-height: 0; padding: 42px 24px; place-items: center; }
.mission-canvas__empty img { width: min(440px, 58vw); max-width: 100%; opacity: .12; filter: grayscale(.55) contrast(.82) brightness(1.12); user-select: none; }
.pending-launch { display: grid; gap: 10px; font-size: 12px; }
.pending-launch button { padding: 8px; border: 1px solid var(--border-light); background: var(--bg-app); color: var(--text-primary); border-radius: 6px; cursor: pointer; }
.mission-workspace { display: flex; align-items: center; gap: 8px; margin-bottom: 9px; min-width: 0; }
.mission-workspace__path { font-size: 11px; color: var(--text-muted); white-space: nowrap; text-overflow: ellipsis; overflow: hidden; }
.mission-workspace :deep(.workspace-trust__trigger) { font-size: 11px; }
.composer-tool { display: grid; place-items: center; width: 28px; height: 28px; color: var(--text-secondary); border: 0; border-radius: 5px; cursor: pointer; font-size: 20px; list-style: none; }
.composer-tool:hover { background: var(--bg-hover); color: var(--text-primary); }
.composer-attach input { display: none; }
.composer-model { margin-left: auto; min-width: 0; max-width: 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-muted); font-size: 11px; }
.composer-effort { min-width: 0; max-width: 88px; padding: 5px 3px; border-radius: 6px; color: var(--wb-text-secondary); font: inherit; font-size: 11px; background: transparent; border: 0; cursor: pointer; }
.composer-notice { margin: 8px 2px 0; color: var(--text-muted); font-size: 11px; line-height: 1.5; }
.is-error, .attachment-row__error { color: var(--danger-color, #df7d7d); }
.composer-settings { position: relative; }
.composer-settings__panel { position: absolute; bottom: 36px; left: -32px; z-index: 20; box-sizing: border-box; width: min(350px, calc(var(--workbench-right-width, 320px) - 80px), calc(100vw - 110px)); max-height: min(560px, 65vh); overflow: auto; padding: 16px; border: 1px solid var(--border-light); border-radius: 8px; background: var(--bg-sidebar); box-shadow: 0 8px 24px #0003; }
.composer-settings__panel h2 { margin: 0 0 16px; font-size: 13px; }
.composer-settings__panel h3 { margin: 20px 0 10px; font-size: 12px; }
.setting-field { display: grid; gap: 8px; margin: 14px 0; font-size: 12px; }
.setting-field small { color: var(--text-muted); font-size: 11px; line-height: 1.5; }
.setting-field select, .setting-field input { box-sizing: border-box; width: 100%; padding: 7px; border: 1px solid var(--border-light); border-radius: 5px; color: var(--text-primary); background: var(--bg-app); }
.setting-toggle { display: flex; align-items: center; gap: 8px; margin-top: 14px; font-size: 12px; }
.config-options { display: flex; flex-wrap: wrap; gap: 6px; }
.config-option { padding: 6px 9px; border: 1px solid var(--border-light); border-radius: 5px; color: var(--text-secondary); background: transparent; font: inherit; font-size: 11px; cursor: pointer; }
.config-option.is-selected { border-color: var(--primary-color); color: var(--primary-color); }
.composer-attachments { padding: 8px 8px 0; max-height: 180px; overflow: auto; }
.attachment-row { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; padding: 7px; border-bottom: 1px solid var(--border-light); font-size: 11px; }
.attachment-row__name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.attachment-row small { color: var(--text-muted); }
.attachment-row button { border: 0; color: var(--text-secondary); background: transparent; cursor: pointer; }
.attachment-row__error { flex-basis: 100%; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; }
button:focus-visible, summary:focus-visible, select:focus-visible, .composer-attach:focus-within { outline: 2px solid var(--primary-color); outline-offset: 2px; }
.composer-notice { margin-inline: 14px; }
</style>
