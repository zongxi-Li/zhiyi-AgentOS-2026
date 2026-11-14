import { localFetch } from '@/platform/api'
import type { ChatApprovalMode } from '@/config/chatApproval'
import { defineStore } from 'pinia'
import { computed, nextTick, onScopeDispose, ref } from 'vue'
import { chatStreamErrorMessage, type ChatStreamEvent } from '@/utils/sse'
import { startChatExecution, followChatExecution } from '@/features/chat/executionStream'
import { apiUrl } from '@/platform'
import type { AsyncWorkflowStartResponse } from '@/services/api/workflow'
import type { ConversationLaunchContext } from '@/features/mission/request'
import { compactionFailureMessage, conversationInput, estimateContextInput } from '@/features/chat/compaction'
import { conversationLaunchCommand, matchesConversationLaunchContext } from '@/features/mission/command'
import { createMissionLaunchAttempt, MissionLaunchStateError } from '@/features/mission/launchAttempt'
import type { MissionLaunchResult } from '@/features/mission/launch'
import { chatApi, type ChatRequest } from '@/services/api/chat'
import { loadModelSettings, MODEL_SETTINGS_EVENT, toModelRequestSettings, type ModelSettings } from '@/config/modelSettings'
import { useWorkflowRunsStore } from '@/stores/workflowRuns'
import { conversationApi } from '@/services/api/conversation'
import { getConversationWorkspace, setConversationWorkspace, type ConversationWorkspaceMode } from '@/utils/conversationWorkspace'
import { conversationBindings, mergeDraftBindings, isActiveRunStatus } from '@/features/workspace/session'
import { applyTranscript, restoreTranscript, createStreamBatcher, mergeResponseTimings, workingContext, contextUsage, type ContextUsage, type WorkingContext, type TranscriptBlock, type ResponseTimings } from '../../../backend/src/shared/chat-stream/index.mjs'

export interface TerminalExecution {
  command: string
  cwd: string
  exitCode: number | null
  stdout: string
  stderr: string
  timedOut: boolean
  truncated: boolean
  durationMs?: number
}

export interface ToolExecutionActivity {
  kind: 'file_read' | 'file_list' | 'file_write' | 'file_patch' | 'terminal' | string
  capabilityId?: string
  relativePath?: string
  status?: string
  summary?: string
  addedLines?: number
  removedLines?: number
  entryCount?: number
  errorCode?: string
}

export interface ChatApproval {
  approvalId: string
  toolCallId: string
  invocationId: string
  toolName: string
  capabilityId: string
  relativePath?: string
  operationSummary: string
  createdAt: string
  status: 'pending' | 'approved' | 'denied' | 'expired' | string
  sessionId: string
  operation?: string
  command?: string
  cwd?: string
  riskNotice?: string
}

export interface ExecutionSummaryItem {
  stage: string
  status: string
  description: string
  durationMs?: number
  terminal?: TerminalExecution
  activity?: ToolExecutionActivity
  approval?: ChatApproval
}

/** Page-lifetime compaction entry rendered as an inline row in the chat timeline. */
export interface CompactionStatus {
  kind: 'running' | 'success' | 'info' | 'warning'
  title: string
  detail?: string
}

export interface Message {
  workingContext?: WorkingContext
  contextUsage?: ContextUsage
  projectionVersion?: number
  archivedItems?: number
  providerRequest?: number
  attemptId?: string
  id: number | string
  role: 'user' | 'assistant'
  content: string
  transcript?: TranscriptBlock[]
  chatExecutionId?: string
  chatExecutionState?: string
  fileUrl?: string
  createdAt?: Date
  timestamp?: number
  audioUrl?: string
  animation?: any
  confidence?: number
  tokensUsed?: number
  sources?: any[]
  reasoningPath?: any[]
  modelInfo?: string
  contextFixedTokens?: number
  contextWindowTokens?: number
  cachedTokens?: number
  cacheUsageAvailable?: boolean
  protocolSession?: boolean
  lastInputTokens?: number
  lastOutputTokens?: number
  contextInputTokens?: number
  requestBodyBytes?: number
  responseTimings?: ResponseTimings
  contextMeasurement?: string
  contextTokenMethod?: string
  thinkingState?: 'thinking' | 'complete' | 'error'
  streamError?: string
  streamActivity?: 'receiving' | 'waiting' | 'complete'
  streamPhase?: string
  phaseStartedAt?: number
  lastProviderActivityAt?: number
  lastHeartbeatAt?: number
  thinkingDurationMs?: number
  reasoningContent?: string
  reasoningTruncated?: boolean
  requestedThinkingMode?: string
  effectiveThinkingMode?: string
  effectiveReasoningEffort?: string
  inputTokens?: number
  reasoningTokens?: number
  outputTokens?: number
  latencyMs?: number
  executionSummary?: ExecutionSummaryItem[]
  skillsUsed?: string[]
  trace?: Array<Record<string, unknown>>

  agentMode?: 'default'
  acgTaskId?: string
  workflowRunId?: string
  workflowMissionId?: string
  workflowId?: string
  workflowStatus?: string
  workflowClientRequestId?: string
  runtimeEngine?: string
  implementationId?: string
}

export interface ChatWorkflowBinding {
  conversationId: string
  conversationAliases?: string[]
  messageId?: string
  missionId: string
  acgTaskId: string
  runId: string
  workflowId?: string
  source: 'agent' | 'chat'
  clientRequestId: string
  createdAt: string
  status: string
  invalidAt?: string
}

export interface ChatWorkflowStartResult {
  response: AsyncWorkflowStartResponse
  binding: ChatWorkflowBinding
  launch: MissionLaunchResult
}

export const useChatStore = defineStore('chat', () => {
  const approvalMode = ref<ChatApprovalMode>('ask')
  const WORKFLOW_BINDINGS_KEY = 'chat.workflow_bindings.v1'
  const loadWorkflowBindings = (): Record<string, ChatWorkflowBinding[]> => {
    try {
      const parsed = JSON.parse(localStorage.getItem(WORKFLOW_BINDINGS_KEY) || '{}')
      if (!parsed || typeof parsed !== 'object') return {}
      return Object.fromEntries(
        Object.entries(parsed).map(([conversationId, value]) => [
          conversationId,
          (Array.isArray(value) ? value : [])
            .filter(item => item && typeof item.runId === 'string' && item.runId.trim())
            .map(item => ({
              ...item,
              conversationAliases: Array.isArray(item.conversationAliases)
                ? item.conversationAliases.filter((key: unknown) => typeof key === 'string') : undefined,
              acgTaskId: typeof item.acgTaskId === 'string' && item.acgTaskId.trim()
                ? item.acgTaskId.trim()
                : item.runId.trim(),
              source: item.source === 'agent' ? 'agent' : 'chat'
            }))
        ])
      ) as Record<string, ChatWorkflowBinding[]>
    } catch {
      return {}
    }
  }
  const messages = ref<Message[]>([])
  const loading = ref(false)
  const isStreaming = ref(false)
  const isLoadingConversation = ref(false)
  const isCompacting = ref(false)
  // Codex-style timeline entry: icon + headline with an optional muted detail line.
  const compactionStatus = ref<CompactionStatus | null>(null)
  const compactionNotice = computed(() => {
    const status = compactionStatus.value
    if (!status) return ''
    return status.detail ? `${status.title}：${status.detail}` : status.title
  })
  // Page-lifetime projections only; raw messages and stored history stay intact.
  const workflowBindings = ref<Record<string, ChatWorkflowBinding[]>>(loadWorkflowBindings())
  const workflowRunsStore = useWorkflowRunsStore()
  let activeStreamController: AbortController | null = null
  let activeRequestId: string | null = null
  let stopBeforeAcknowledgement: (() => void) | null = null
  const contextId = ref<string | null>(null)
  const currentRoleId = ref<string | null>(null)
  const historyError = ref<string | null>(null)
  const conversationWorkspaceMode = ref<ConversationWorkspaceMode | null>(null)
  let historyGeneration = 0
  let messageGeneration = 0
  // Transport cancellation is best effort; only the current owner may write UI state.
  const invalidateMessageRequest = () => {
    ++messageGeneration
    activeStreamController?.abort()
    activeStreamController = null
    activeRequestId = null
    stopBeforeAcknowledgement = null
    isStreaming.value = false
    isCompacting.value = false
    compactionStatus.value = null
    loading.value = false
  }
  // Provider usage belongs to the last execution, including its tool loop.
  // The next input estimate below measures the actual text-history projection.
  const contextUsedTokens = ref<number | null>(null)
  const contextWindowTokens = ref<number | null>(null)
  const contextMeasurement = ref('usage')
  const contextUsageState = ref<ContextUsage | null>(null)
  const contextModel = ref<string | null>(null)
  const contextModels = ref<Record<string, number>>({})
  const contextEstimateBasis = ref<{
    owner: string; roleId: string | null; modelKey: string; fixedTokens: number
  } | null>(null)
  const invalidateContextEstimate = () => { contextEstimateBasis.value = null }
  window.addEventListener(MODEL_SETTINGS_EVENT, invalidateContextEstimate)
  onScopeDispose(() => window.removeEventListener(MODEL_SETTINGS_EVENT, invalidateContextEstimate))

  const applyContextUsage = (used: number | null, model?: string | null, windowTokens?: number | null, measurement = 'usage') => {
    contextMeasurement.value = measurement
    if (model) contextModel.value = model
    if (typeof windowTokens === 'number' && windowTokens > 0) {
      contextWindowTokens.value = windowTokens
      if (model) contextModels.value = { ...contextModels.value, [model]: windowTokens }
    } else if (model && contextModels.value[model]) {
      contextWindowTokens.value = contextModels.value[model]
    }
    contextUsedTokens.value = typeof used === 'number' && used >= 0 ? used : null
  }

  const applyContextSnapshot = (value: unknown) => {
    const state = contextUsage(value)
    if (!state) return false
    contextUsageState.value = state
    applyContextUsage(state.usedTokens, undefined, state.maxTokens, state.measurement)
    invalidateContextEstimate()
    return true
  }

  const fetchContextWindows = async () => {
    try {

      const response = await localFetch(apiUrl('/ai/chat/models'), {
      })
      if (!response.ok) return
      const data = await response.json() as { context_windows?: Record<string, unknown>; default_model?: string }
      const windows = data?.context_windows && typeof data.context_windows === 'object'
        ? Object.fromEntries(
            Object.entries(data.context_windows)
              .filter(([, value]) => typeof value === 'number' && (value as number) > 0)
          )
        : {}
      if (!Object.keys(windows).length) return
      contextModels.value = { ...contextModels.value, ...windows } as Record<string, number>
      if (!contextModel.value) {
        const selected = loadModelSettings().selectedModel
        contextModel.value = selected && selected !== '系统默认' ? selected : data.default_model || null
      }
      if (!contextWindowTokens.value && contextModel.value && windows[contextModel.value]) {
        contextWindowTokens.value = windows[contextModel.value] as number
      }
    } catch {
      // The indicator simply stays hidden when the catalog is unavailable.
    }
  }

  const pushUserMessage = (text: string, fileUrl?: string) => {
    const userMessage: Message = {
      id: Date.now(),
      role: 'user',
      content: text || (fileUrl ? '[文件]' : ''),
      createdAt: new Date()
    }
    if (fileUrl) {
      userMessage.fileUrl = fileUrl
    }
    messages.value.push(userMessage)
    return userMessage
  }

  const persistWorkflowBindings = () => {
    localStorage.setItem(WORKFLOW_BINDINGS_KEY, JSON.stringify(workflowBindings.value))
  }

  const addWorkflowBinding = (binding: ChatWorkflowBinding) => {
    const associated = conversationBindings(workflowBindings.value, binding.conversationId)
      .find(item => item.runId === binding.runId)
    if (associated) binding = { ...binding, conversationId: associated.conversationId,
      conversationAliases: associated.conversationAliases }
    const existing = workflowBindings.value[binding.conversationId] || []
    workflowBindings.value = {
      ...workflowBindings.value,
      [binding.conversationId]: [...existing.filter(item => item.runId !== binding.runId), binding]
    }
    persistWorkflowBindings()
    workflowRunsStore.registerChatBinding(binding)
  }

  const getLatestWorkflowBinding = (conversationId: string) => {
    const bindings = conversationBindings(workflowBindings.value, conversationId)
    return [...bindings].reverse().find(binding => !binding.invalidAt)
  }

  const getActiveWorkflowBinding = (conversationId: string) => {
    const bindings = conversationBindings(workflowBindings.value, conversationId)
    return [...bindings].reverse().find(binding =>
      !binding.invalidAt && isActiveRunStatus(binding.status)
    )
  }

  const migrateDraftBindings = (draft: string, targetContextId: string) => {
    if (contextId.value !== targetContextId || isLoadingConversation.value) return
    const sourceRuns = (workflowBindings.value[draft] || []).map(item => item.runId)
    const next = mergeDraftBindings(workflowBindings.value, draft, targetContextId)
    if (next === workflowBindings.value) return
    workflowBindings.value = next
    persistWorkflowBindings()
    workflowRunsStore.reassociateConversation(draft, targetContextId, sourceRuns)
  }

  const updateWorkflowBindingStatus = (conversationId: string, runId: string, status: string) => {
    conversationId = conversationBindings(workflowBindings.value, conversationId).find(item => item.runId === runId)?.conversationId || conversationId
    const bindings = workflowBindings.value[conversationId] || []
    if (!bindings.some(binding => binding.runId === runId)) return
    workflowBindings.value = {
      ...workflowBindings.value,
      [conversationId]: bindings.map(binding => binding.runId === runId
        ? { ...binding, status }
        : binding)
    }
    persistWorkflowBindings()
    workflowRunsStore.updateObservedState(runId, status)
  }

  const markWorkflowBindingInvalid = (conversationId: string, runId: string) => {
    conversationId = conversationBindings(workflowBindings.value, conversationId).find(item => item.runId === runId)?.conversationId || conversationId
    const bindings = workflowBindings.value[conversationId] || []
    if (!bindings.some(binding => binding.runId === runId)) return
    workflowBindings.value = {
      ...workflowBindings.value,
      [conversationId]: bindings.map(binding => binding.runId === runId
        ? { ...binding, invalidAt: new Date().toISOString() }
        : binding)
    }
    persistWorkflowBindings()
    workflowRunsStore.markInvalid(runId)
  }

  const emitHistoryRefresh = () => {
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new Event('history-refresh'))
    }
  }

  const compactionModelKey = (settings: ModelSettings) => JSON.stringify([
    settings.provider, settings.selectedModel, settings.provider === 'system' ? '' : settings.baseUrl, currentRoleId.value
  ])

  const checkContextModel = (settings: ModelSettings) => {
    if (!contextId.value || conversationWorkspaceMode.value === 'agent') return
    if (contextEstimateBasis.value?.modelKey !== compactionModelKey(settings)) invalidateContextEstimate()
  }

  const setContextEstimate = (fixedTokens: unknown, method: unknown, settings: ModelSettings) => {
    // Older running services may omit allowance metadata. A manual projection
    // already calibrated this same conversation/model; do not replace it with
    // the execution's unrelated Provider usage on the next turn.
    const basis = contextEstimateBasis.value
    if (fixedTokens === undefined && method === undefined && basis
      && basis.owner === contextId.value && basis.roleId === currentRoleId.value
      && basis.modelKey === compactionModelKey(settings)) return
    if (!contextId.value || method !== 'utf8-upper-bound'
      || typeof fixedTokens !== 'number' || !Number.isSafeInteger(fixedTokens) || fixedTokens < 0) {
      invalidateContextEstimate()
      return
    }
    contextEstimateBasis.value = { owner: contextId.value, roleId: currentRoleId.value,
      modelKey: compactionModelKey(settings), fixedTokens }
  }

  const nextContextTokens = computed(() => {
    const basis = contextEstimateBasis.value
    if (!basis || basis.owner !== contextId.value || basis.roleId !== currentRoleId.value) return null
    const source = conversationInput(messages.value)
    return estimateContextInput(source, basis.fixedTokens)
  })

  const compactContext = async (settings: ModelSettings = loadModelSettings()) => {
    if (loading.value || isLoadingConversation.value) return
    if (historyError.value) throw new Error(historyError.value)
    if (conversationWorkspaceMode.value === 'agent') throw new Error('/compact 仅用于 OScode 对话')
    const owner = contextId.value
    const source = conversationInput(messages.value)
    if (!owner || !source.length) {
      compactionStatus.value = { kind: 'info', title: '暂无可压缩的上下文', detail: '请先开始对话。' }
      return
    }
    const generation = ++messageGeneration
    const isCurrent = () => generation === messageGeneration && contextId.value === owner
    const controller = new AbortController()
    activeStreamController = controller
    loading.value = true
    isCompacting.value = true
    compactionStatus.value = { kind: 'running', title: '正在压缩上下文' }
    try {
      const model = toModelRequestSettings(settings)
      const response = await chatApi.compactContext({
        context_id: owner, context: source,
        role_id: currentRoleId.value || undefined, model: model.model,
        base_url: settings.provider === 'system' ? undefined : settings.baseUrl,
        api_key: settings.provider === 'system' ? undefined : settings.apiKey
      }, controller.signal)
      if (!isCurrent()) return
      if (response.contextId !== owner || JSON.stringify(conversationInput(messages.value)) !== JSON.stringify(source)) {
        throw new Error('对话内容已变化，本次压缩结果未应用，请重试。')
      }
      if (response.status === 'summarized' || response.status === 'pruned') {
        const before = Number(response.metrics.inputTokens), after = Number(response.metrics.outputTokens)
        compactionStatus.value = response.durable
          ? { kind: 'success', title: '上下文已压缩', detail: `估算 ${before.toLocaleString()} → ${after.toLocaleString()} Token · 后端已保存版本 ${response.projectionVersion}，完整记录保留` }
          : { kind: 'warning', title: '压缩结果尚未持久化', detail: '请升级后端后重试，原始对话已保留。' }
      } else if (response.status === 'failed_passthrough') {
        compactionStatus.value = { kind: 'warning', title: compactionFailureMessage(response.metrics.failureCode) }
      } else if (response.metrics.reasonCode === 'INSUFFICIENT_SAVINGS') {
        compactionStatus.value = { kind: 'info', title: '无需压缩',
          detail: '当前历史较短，摘要及必要引用的开销接近原文，原上下文已保留。' }
      } else {
        compactionStatus.value = { kind: 'info', title: '暂无可安全摘要的已完成历史',
          detail: '当前请求、未完成工具组及附件内容会保留。' }
      }
      if (response.model) contextModel.value = response.model
      if (response.contextWindowTokens > 0) contextWindowTokens.value = response.contextWindowTokens
      applyContextSnapshot(response.contextUsage)
      if (response.durable) invalidateContextEstimate()
      else setContextEstimate(response.contextFixedTokens ?? response.metrics.fixedTokens,
        response.contextTokenMethod ?? response.metrics.tokenMethod, settings)
      return response
    } catch (error: any) {
      if (isCurrent()) {
        compactionStatus.value = { kind: 'warning', title: '上下文压缩未完成', detail: error.response?.data?.detail?.message
          || error.response?.data?.message || '原上下文已保留。' }
        throw error
      }
    } finally {
      if (isCurrent()) {
        isCompacting.value = false
        loading.value = false
        activeStreamController = null
      }
    }
  }

  const sendMessage = async (
    text: string,
    fileUrl?: string,
    runtimeSettings?: ModelSettings,
    workspaceMode: 'agent' | 'chat' = 'chat'
  ) => {
    if ((!text.trim() && !fileUrl) || loading.value) return
    if (historyError.value) throw new Error(historyError.value)

    const generation = ++messageGeneration
    const isCurrent = () => generation === messageGeneration
    const settings = runtimeSettings || loadModelSettings()
    if (workspaceMode === 'chat') checkContextModel(settings)
    pushUserMessage(text, fileUrl)

    loading.value = true
    try {
      const request: ChatRequest = {
        text: text || '',
        roleId: currentRoleId.value || undefined,
        contextId: contextId.value || undefined,
        workspaceMode: contextId.value ? conversationWorkspaceMode.value || workspaceMode : workspaceMode,
        fileUrl: fileUrl || undefined,
        ...toModelRequestSettings(runtimeSettings || loadModelSettings())
      }

      const response = await chatApi.sendMessage(request)
      if (!isCurrent()) return
      contextId.value = response.contextId

      const assistantMessage: Message = {
        id: Date.now() + 1,
        role: 'assistant',
        content: response.text,
        createdAt: new Date(),
        confidence: response.confidence,
        tokensUsed: response.tokensUsed,
        sources: response.sources,
        reasoningPath: response.reasoningPath,
        modelInfo: response.modelInfo,
        contextFixedTokens: response.metadata?.contextFixedTokens,
        contextTokenMethod: response.metadata?.contextTokenMethod,
        requestedThinkingMode: response.metadata?.requestedThinkingMode,
        effectiveThinkingMode: response.metadata?.effectiveThinkingMode,
        effectiveReasoningEffort: response.metadata?.effectiveReasoningEffort,
        inputTokens: response.metadata?.inputTokens,
        reasoningTokens: response.metadata?.reasoningTokens,
        outputTokens: response.metadata?.outputTokens,
        latencyMs: response.metadata?.latencyMs,
        executionSummary: response.metadata?.executionSummary,
        agentMode: 'default'
      }
      messages.value.push(assistantMessage)
      setContextEstimate(response.metadata?.contextFixedTokens, response.metadata?.contextTokenMethod, settings)
      emitHistoryRefresh()

      return response
    } catch (error) {
      if (isCurrent()) throw error
    } finally {
      if (isCurrent()) loading.value = false
    }
  }

  // ---- 流式发送（SSE）----

  const sendMessageStream = async (
    text: string,
    agentMode: 'default' = 'default',
    runtimeSettings: ModelSettings = loadModelSettings(),
    workspaceMode: 'agent' | 'chat' = 'chat',
    resumeMessage?: Message
  ) => {
    if (!resumeMessage && ((!text.trim()) || loading.value)) return
    if (historyError.value) throw new Error(historyError.value)
    const browserStartedAt = performance.now()
    let browserReceived = false, browserFrameScheduled = false

    const generation = ++messageGeneration
    const isCurrent = () => generation === messageGeneration
    const modelRequestSettings = toModelRequestSettings(runtimeSettings)
    if (workspaceMode === 'chat') checkContextModel(runtimeSettings)

    if (!resumeMessage) pushUserMessage(text)
    loading.value = true
    isStreaming.value = true

    const streamMsg: Message = {
      id: Date.now() + 1,
      role: 'assistant',
      content: '',
      createdAt: new Date(),
      modelInfo: runtimeSettings.selectedModel || '系统默认',
      thinkingState: runtimeSettings.thinkingMode === 'disabled' ? undefined : 'thinking',
      requestedThinkingMode: runtimeSettings.thinkingMode,
      reasoningContent: '',
      streamActivity: 'receiving',
      streamPhase: '等待模型响应',
      phaseStartedAt: Date.now(),
      agentMode
    }
    if (!resumeMessage) messages.value.push(streamMsg)
    const streamMessage = resumeMessage || messages.value[messages.value.length - 1]
    streamMessage.streamError = undefined
    streamMessage.streamActivity = 'waiting'
    const clientRequestId = crypto.randomUUID()
    const ownedMessage = () => isCurrent() ? streamMessage : undefined
    let thinkingStartedAt = performance.now()
    let terminal: 'done' | 'error' | 'cancelled' | null = null
    const finishThinking = (state: 'complete' | 'error', durationMs?: number) => {
      const message = ownedMessage()
      if (!message) return
      if (!message.thinkingState && message.requestedThinkingMode === 'disabled') return
      if (durationMs !== undefined || message.thinkingState === 'thinking' || message.thinkingDurationMs === undefined) {
        message.thinkingDurationMs = Math.max(0, durationMs ?? (performance.now() - thinkingStartedAt))
      }
      message.thinkingState = state
    }
    const appendStreamContent = (delta: string) => {
      const message = ownedMessage()
      if (message) {
        finishThinking('complete')
        message.content = (message.content || '') + delta
      }
    }
    const appendReasoningContent = (delta: string) => {
      const message = ownedMessage()
      if (message) message.reasoningContent = (message.reasoningContent || '') + delta
    }
    const failStream = (description: string, state: 'error' | 'cancelled' = 'error') => {
      terminal = state
      finishThinking('error')
      const message = ownedMessage()
      if (!message) return
      message.streamActivity = 'complete'
      message.streamPhase = state === 'cancelled' ? '已停止生成' : '请求未完成'
      message.streamError = description
      message.chatExecutionState = state === 'cancelled' ? 'cancelled' : 'failed'
      if (!contextUsageState.value && typeof (message.lastInputTokens ?? message.inputTokens) !== 'number') {
        applyContextUsage(null, message.modelInfo, message.contextWindowTokens)
        invalidateContextEstimate()
      }
      if (!message.content) message.content = description
    }
    const applyStreamEvent = (event: ChatStreamEvent) => {
      if (terminal) return
      const message = ownedMessage()
      if (!message) return
      message.transcript ||= []
      applyTranscript(message.transcript, event)
      const data = event.data || {}
      if (data.responseTimings) message.responseTimings = mergeResponseTimings({...message.responseTimings}, data.responseTimings)
      const budget = workingContext(data.workingContext)
      if (budget) message.workingContext = budget
      const watermark = contextUsage(data.contextUsage)
      if (watermark) {
        message.contextUsage = watermark
        applyContextSnapshot(watermark)
      }
      for (const key of ['projectionVersion', 'archivedItems', 'providerRequest', 'attemptId'] as const) {
        if (data[key] !== undefined) (message as any)[key] = data[key]
      }
      if (!resumeMessage && !browserFrameScheduled && ['reasoning_delta', 'content_delta'].includes(event.event) && data.delta) {
        browserFrameScheduled = true
        void nextTick().then(() => {
          if (typeof requestAnimationFrame === 'function') requestAnimationFrame(() => {
            const owned = ownedMessage()
            if (owned) owned.responseTimings = mergeResponseTimings({...owned.responseTimings},
              {browserFirstFrameMs: performance.now() - browserStartedAt})
          })
        })
      }
      if (event.event !== 'heartbeat' && event.event !== 'model_activity' && event.event !== 'tool_result' && event.event !== 'done' && event.event !== 'error') {
        message.streamActivity = 'receiving'
      }
      if (event.requestId && event.requestId !== 'unknown' && event.requestId !== 'legacy') {
        activeRequestId = event.requestId
      }
      const upsertToolSummary = (status: string, payload: Record<string, any> = data) => {
        if (payload.activity?.status === 'running') status = 'running'
        const approval = payload.approval && typeof payload.approval === 'object'
          ? payload.approval as ChatApproval
          : undefined
        const toolName = String(payload.toolName || approval?.toolName || 'unknown')
        const callId = String(payload.callId || approval?.toolCallId || toolName)
        const stage = `tool:${toolName}:${callId}`
        const duration = typeof payload.durationMs === 'number' ? payload.durationMs : undefined
        const description = status === 'completed'
          ? `${toolName} 调用完成${duration === undefined ? '' : `（${duration}ms）`}`
          : status === 'failed'
            ? `${toolName} 调用失败：${payload.errorCode || 'TOOL_FAILED'}`
            : `${toolName} 调用中`
        const summaries = message.executionSummary || []
        const index = summaries.findIndex(item => item.stage === stage)
        const existing = index >= 0 ? summaries[index] : undefined
        if (existing && ['completed', 'failed', 'cancelled'].includes(existing.status) && status === 'running') return
        const terminal = payload.terminal && typeof payload.terminal === 'object'
          ? payload.terminal as TerminalExecution
          : existing?.terminal
        const activity = payload.activity && typeof payload.activity === 'object'
          ? payload.activity as ToolExecutionActivity
          : existing?.activity
        const next: ExecutionSummaryItem = {
          stage,
          status,
          description,
          durationMs: duration,
          ...(terminal ? { terminal } : {}),
          ...(activity ? { activity } : {}),
          ...(approval ? { approval } : existing?.approval ? { approval: existing.approval } : {})
        }
        if (index >= 0) summaries[index] = next
        else summaries.push(next)
        message.executionSummary = [...summaries]
      }
      const phaseForTool = (toolName: string) => {
        const phases: Record<string, string> = {
          read_file: '读取工作文件',
          list_files: '浏览工作区',
          write_file: '写入目标文件',
          patch_file: '应用局部修改',
          run_command: '执行受控命令',
          terminal: '执行受控命令'
        }
        return phases[toolName] || '调用工作工具'
      }
      const mergeSources = (items: unknown) => {
        if (!Array.isArray(items)) return
        const existing = message.sources || []
        const keys = new Set(existing.map(item => item.citationId || item.url || item.title))
        for (const source of items) {
          if (!source || typeof source !== 'object') continue
          const typed = source as Record<string, any>
          const key = typed.citationId || typed.url || typed.title
          if (!keys.has(key)) {
            existing.push(typed)
            keys.add(key)
          }
        }
        message.sources = [...existing]
      }
      const setPhase = (phase: string) => {
        if (message.streamPhase !== phase) message.phaseStartedAt = Date.now()
        message.streamPhase = phase
      }
      switch (event.event) {
        case 'snapshot': {
          const saved = data.message
          if (!saved || typeof saved !== 'object') break
          const metadata = saved.metadata || {}
          message.content = saved.content || ''
          message.transcript = restoreTranscript(metadata.transcript)
          message.executionSummary = metadata.executionSummary || []
          message.reasoningContent = metadata.reasoningContent
          message.sources = metadata.sources
          message.thinkingDurationMs = metadata.reasoningPhaseMs
          message.responseTimings = mergeResponseTimings({}, metadata.responseTimings)
          message.workingContext = workingContext(metadata.workingContext)
          if (applyContextSnapshot(metadata.contextUsage)) message.contextUsage = contextUsageState.value!
          message.requestBodyBytes = metadata.requestBodyBytes ?? (metadata.contextMeasurement === 'protocol-utf8-upper-bound' ? metadata.contextInputTokens : undefined)
          message.chatExecutionId = data.chatExecutionId
          message.chatExecutionState = metadata.chatExecutionState
          message.streamActivity = metadata.chatExecutionState === 'running' ? 'waiting' : 'complete'
          message.streamPhase = metadata.streamPhase || '等待模型响应'
          for (const key of ['inputTokens', 'reasoningTokens', 'outputTokens', 'latencyMs', 'contextFixedTokens',
            'contextWindowTokens', 'contextInputTokens', 'contextMeasurement', 'contextTokenMethod', 'requestedThinkingMode',
            'effectiveThinkingMode', 'effectiveReasoningEffort', 'reasoningTruncated', 'cacheUsageAvailable', 'protocolSession'] as const) {
            if (metadata[key] !== undefined) (message as any)[key] = metadata[key]
          }
          message.projectionVersion = metadata.projectionVersion
          message.archivedItems = metadata.archivedItems
          message.providerRequest = metadata.providerRequest
          message.attemptId = metadata.attemptId
          message.tokensUsed = metadata.totalTokens
          message.modelInfo = metadata.effectiveModel || message.modelInfo
          message.cachedTokens = metadata.cached_tokens
          message.lastInputTokens = metadata.last_input_tokens
          message.lastOutputTokens = metadata.last_output_tokens
          const usedInput = message.lastInputTokens ?? message.inputTokens
          if (!contextUsageState.value) applyContextUsage(typeof usedInput === 'number' ? usedInput + (message.lastOutputTokens ?? message.outputTokens ?? 0) : null,
            message.modelInfo || null, message.contextWindowTokens)
          if (message.protocolSession) invalidateContextEstimate()
          if (typeof data.contextId === 'string') contextId.value = data.contextId
          break
        }
        case 'heartbeat':
          message.lastHeartbeatAt = Date.now()
          break
        case 'model_activity':
          message.lastProviderActivityAt = Date.now()
          break
        case 'model_context': {
          if (typeof data.requestBodyBytes === 'number') message.requestBodyBytes = data.requestBodyBytes
          else if (data.contextMeasurement === 'protocol-utf8-upper-bound') message.requestBodyBytes = data.contextInputTokens
          if (typeof data.contextWindowTokens === 'number') message.contextWindowTokens = data.contextWindowTokens
          invalidateContextEstimate()
          if (data.contextMeasurement === 'provider-usage' && typeof data.last_input_tokens === 'number') {
            message.contextInputTokens = data.last_input_tokens
            message.contextMeasurement = data.contextMeasurement
            message.lastInputTokens = data.last_input_tokens
            message.lastOutputTokens = data.last_output_tokens ?? 0
            if (typeof data.protocolSession === 'boolean') message.protocolSession = data.protocolSession
            if (message.workingContext) message.workingContext = {...message.workingContext, actualInputTokens: data.last_input_tokens}
            if (!watermark) applyContextUsage(message.lastInputTokens! + message.lastOutputTokens!, data.effectiveModel, data.contextWindowTokens)
          } else {
            // Request bytes include JSON/schema overhead, never replace measured tokens.
            if (message.contextMeasurement !== 'provider-usage') {
              message.contextInputTokens = data.contextInputTokens
              message.contextMeasurement = data.contextMeasurement
            }
            if (!contextUsageState.value) applyContextUsage(contextUsedTokens.value, data.effectiveModel, data.contextWindowTokens)
          }
          break
        }
        case 'model_phase':
          if (data.phase === 'context_journal') setPhase('读取已保存的工作上下文')
          else if (data.phase === 'context_pruning') setPhase('整理旧工具输出')
          else if (data.phase === 'context_summary') setPhase('正在生成历史摘要，可停止')
          else if (data.phase === 'context_ready') setPhase('工作上下文已准备')
          else if (data.phase === 'context_committed') setPhase('工作上下文已保存')
          else if (data.phase === 'context_stale' || data.phase === 'context_failed') setPhase('本次工作上下文未保存，完整记录仍保留')
          if (data.contextWindowTokens > 0) message.contextWindowTokens = data.contextWindowTokens
          if (data.phase === 'waiting' && !contextUsageState.value) applyContextUsage(contextModel.value && data.effectiveModel !== contextModel.value
            ? null : contextUsedTokens.value, data.effectiveModel, data.contextWindowTokens)
          if (data.phase === 'waiting') {
            message.lastProviderActivityAt = undefined
            message.streamActivity = 'waiting'
            setPhase(data.retryAttempt > 0 ? `正在重试模型，等待响应（${data.retryAttempt}/1）`
              : data.turn > 1 ? '操作已完成，等待模型处理结果' : '等待模型响应')
          } else if (data.phase === 'tool_arguments') {
            message.streamActivity = 'receiving'
            setPhase('正在准备工具调用')
          } else if (data.phase === 'retrying') {
            message.streamActivity = 'waiting'
            setPhase(`模型连接中断，正在重试当前请求（${data.retryAttempt}/1）`)
          }
          break
        case 'reasoning_start':
          thinkingStartedAt = performance.now()
          message.streamActivity = 'receiving'
          setPhase('正在思考')
          message.thinkingState = 'thinking'
          message.requestedThinkingMode = data.requestedThinkingMode || message.requestedThinkingMode
          message.effectiveThinkingMode = data.effectiveThinkingMode
          message.effectiveReasoningEffort = data.effectiveReasoningEffort
          break
        case 'reasoning_delta':
          message.streamActivity = 'receiving'
          setPhase('正在思考')
          message.thinkingState = 'thinking'
          if (typeof data.delta === 'string') appendReasoningContent(data.delta)
          break
        case 'reasoning_end':
          finishThinking('complete', typeof data.reasoningPhaseMs === 'number' ? data.reasoningPhaseMs : undefined)
          break
        case 'content_delta':
          message.streamActivity = 'receiving'
          setPhase('正在生成回复')
          if (typeof data.delta === 'string') appendStreamContent(data.delta)
          break
        case 'tool_start':
          message.streamActivity = 'receiving'
          setPhase(phaseForTool(String(data.toolName || '')))
          upsertToolSummary('running')
          break
        case 'tool_result':
          if (message.streamActivity !== 'waiting') {
            message.streamActivity = 'receiving'
            setPhase('工具已完成')
          }
          upsertToolSummary('completed', data)
          mergeSources(data.sources)
          break
        case 'tool_error':
          setPhase('处理工具异常')
          upsertToolSummary('failed', data)
          break
        case 'approval_required':
          setPhase('等待你的确认')
          upsertToolSummary('approval_required', data)
          break
        case 'approval_resolved':
          setPhase('确认已通过，继续执行')
          upsertToolSummary('approval_resolved', data)
          break
        case 'execution_started':
          setPhase('执行受控命令')
          upsertToolSummary('running', data)
          break
        case 'stdout_delta':
        case 'stderr_delta':
          setPhase('读取命令输出')
          upsertToolSummary('running', data)
          break
        case 'execution_completed':
          setPhase('整理执行结果')
          upsertToolSummary('completed', data)
          break
        case 'execution_failed':
          setPhase('处理执行异常')
          upsertToolSummary('failed', data)
          break
        case 'execution_cancelled':
          setPhase('执行已取消')
          upsertToolSummary('cancelled', data)
          break
        case 'usage':
          message.cachedTokens = data.cached_tokens
          message.cacheUsageAvailable = data.cacheUsageAvailable
          message.protocolSession = data.protocolSession
          message.lastInputTokens = data.last_input_tokens
          message.lastOutputTokens = data.last_output_tokens
          message.contextWindowTokens = data.contextWindowTokens
          message.inputTokens = data.input_tokens ?? data.inputTokens
          message.reasoningTokens = data.reasoning_tokens ?? data.reasoningTokens
          message.outputTokens = data.output_tokens ?? data.outputTokens
          message.tokensUsed = data.total_tokens ?? data.totalTokens
          message.latencyMs = data.latencyMs
          message.modelInfo = data.effectiveModel || message.modelInfo
          message.contextFixedTokens = data.contextFixedTokens
          message.contextTokenMethod = data.contextTokenMethod
          if (data.protocolSession) invalidateContextEstimate()
          else setContextEstimate(data.contextFixedTokens, data.contextTokenMethod, runtimeSettings)
          message.requestedThinkingMode = data.requestedThinkingMode || message.requestedThinkingMode
          message.effectiveThinkingMode = data.effectiveThinkingMode || message.effectiveThinkingMode
          message.effectiveReasoningEffort = data.effectiveReasoningEffort || message.effectiveReasoningEffort
          {
            const usedInput = message.lastInputTokens ?? message.inputTokens
            const usedOutput = message.lastOutputTokens ?? message.outputTokens
            const contextUsed = typeof usedInput === 'number'
              ? usedInput + (typeof usedOutput === 'number' ? usedOutput : 0)
              : (typeof message.tokensUsed === 'number' ? message.tokensUsed : null)
            if (!contextUsageState.value) applyContextUsage(
              contextUsed,
              message.modelInfo || null,
              data.contextWindowTokens ?? data.context_window_tokens
            )
          }
          break
        case 'done':
          if (data.status && data.status !== 'completed') {
            failStream(data.status === 'cancelled' ? '已停止生成' : chatStreamErrorMessage(data.code, data.message),
              data.status === 'cancelled' ? 'cancelled' : 'error')
            break
          }
          terminal = 'done'
          message.chatExecutionState = 'completed'
          message.streamActivity = 'complete'
          message.streamPhase = '已完成'
          if (typeof data.contextId === 'string' && data.contextId) contextId.value = data.contextId
          if (Array.isArray(data.toolExecutions)) {
            for (const execution of data.toolExecutions) {
              if (execution && typeof execution === 'object') {
                upsertToolSummary(
                  execution.status === 'completed' ? 'completed' : 'failed',
                  execution as Record<string, any>
                )
              }
            }
          }
          mergeSources(data.sources)
          finishThinking(message.content ? 'complete' : 'error')
          break
        case 'error':
          message.executionSummary = message.executionSummary?.map(item => ['running', 'approval_required'].includes(item.status)
            ? {...item, status: 'interrupted', ...(item.approval?.status === 'pending'
              ? {approval: {...item.approval, status: 'expired'}} : {})} : item)
          failStream(chatStreamErrorMessage(data.code, data.message),
            data.code === 'CHAT_CANCELLED' || data.status === 'cancelled' ? 'cancelled' : 'error')
          break
      }
    }

    const streamController = new AbortController()
    let batcher: ReturnType<typeof createStreamBatcher<ChatStreamEvent>> | undefined
    activeStreamController = streamController
    activeRequestId = null
    let stopRequested = false
    stopBeforeAcknowledgement = () => {
      stopRequested = true
      const message = ownedMessage()
      if (message) message.streamPhase = '正在停止生成'
    }
    try {
      let execution = resumeMessage?.chatExecutionId ? { chatExecutionId: resumeMessage.chatExecutionId, contextId: contextId.value } : null
      if (!execution) {
        execution = await startChatExecution({
          clientRequestId, text, role_id: currentRoleId.value || undefined,
          model: runtimeSettings.provider === 'system' && runtimeSettings.selectedModel === '系统默认' ? undefined : runtimeSettings.selectedModel,
          base_url: runtimeSettings.provider === 'system' ? undefined : runtimeSettings.baseUrl,
          api_key: runtimeSettings.provider === 'system' ? undefined : runtimeSettings.apiKey,
          thinking_mode: runtimeSettings.thinkingMode, reasoning_effort: modelRequestSettings.reasoningEffort,
          tool_mode: 'auto', approval_mode: approvalMode.value,
          context_id: contextId.value || undefined,
          workspace_mode: contextId.value ? conversationWorkspaceMode.value || workspaceMode : workspaceMode
        }, streamController.signal)
      }
      if (!isCurrent()) return
      stopBeforeAcknowledgement = null
      streamMessage.chatExecutionId = execution.chatExecutionId
      streamMessage.chatExecutionState = 'running'
      contextId.value = execution.contextId
      if (stopRequested) {
        const stopped = await localFetch(apiUrl(`/api/chat/executions/${encodeURIComponent(execution.chatExecutionId)}/cancel`), {method: 'POST'})
        if (!stopped.ok) throw new Error('停止请求尚未确认，请重新打开会话核对执行状态')
        if ((await stopped.json()).cancelled) {
          failStream('已停止生成', 'cancelled')
          return
        }
      }
      batcher = createStreamBatcher(applyStreamEvent)
      for await (const event of followChatExecution(execution.chatExecutionId, streamController.signal, () => {
        batcher?.flush()
        const message = ownedMessage()
        if (message) { message.streamActivity = 'waiting'; message.streamPhase = '连接已断开，正在恢复进度' }
      })) {
        if (!isCurrent()) return
        if (!resumeMessage && !browserReceived && ['reasoning_delta', 'content_delta'].includes(event.event) && event.data?.delta) {
          browserReceived = true
          streamMessage.responseTimings = mergeResponseTimings({...streamMessage.responseTimings},
            {browserFirstReceiveMs: performance.now() - browserStartedAt})
        }
        batcher.accept(event)
      }
      batcher.flush()
      if (terminal === 'done') {
        if (!streamMessage.content) {
          failStream('AI 返回了空响应，请重试')
        } else {
          finishThinking('complete')
        }
        emitHistoryRefresh()
      } else if (!terminal) {
        failStream('流式响应意外结束，请重试')
      }
    } catch (e) {
      batcher?.flush()
      if ((e as Error).name === 'AbortError') {
        failStream('已停止生成', 'cancelled')
      } else {
        failStream('流式请求失败: ' + (e as Error).message)
      }
    } finally {
      batcher?.flush()
      batcher?.dispose()
      const message = ownedMessage()
      if (message) message.streamActivity = 'complete'
      if (message?.thinkingState === 'thinking') {
        finishThinking(terminal === 'done' ? 'complete' : 'error')
      }
      if (isCurrent()) {
        if (activeStreamController === streamController) activeStreamController = null
        activeRequestId = null
        stopBeforeAcknowledgement = null
        isStreaming.value = false
        loading.value = false
      }
    }
  }

  const cancelMessageStream = async () => {
    if (stopBeforeAcknowledgement) {stopBeforeAcknowledgement(); return}
    const requestId = activeRequestId
    const controller = activeStreamController
    const execution = [...messages.value].reverse().find(message => message.chatExecutionId && message.streamActivity !== 'complete')
    if (execution?.chatExecutionId) {
      try {
        const response = await localFetch(apiUrl(`/api/chat/executions/${encodeURIComponent(execution.chatExecutionId)}/cancel`), { method: 'POST' })
        if (!response.ok) throw new Error('cancel not confirmed')
        if (!(await response.json()).cancelled) return
      } catch {
        execution.streamError = '停止请求尚未确认，服务可能仍在执行，请重试停止或重新打开会话核对'
        return
      }
    } else if (requestId) {
      try {
        await chatApi.cancelExecution(requestId)
      } catch {
        // The abort below still closes the UI stream if the control request races shutdown.
      }
    }
    controller?.abort()
  }

  interface ConversationWorkflowOptions {
    domain?: string
    intent?: string
    workflowId?: string
    reviewMode?: string
    title?: string
    conversationId: string
    clientRequestId?: string
    enabledPluginIds?: string[] | null
    execution?: ConversationLaunchContext['execution']
    policyProfile?: ConversationLaunchContext['policyProfile']
  }

  const pendingConversationStarts = new Map<string, Promise<ChatWorkflowStartResult | undefined>>()
  const pendingMissionLaunch = (conversationId: string) => createMissionLaunchAttempt({ slot: `conversation:${conversationId}` }).pending()
  const startConversationWorkflow = async (
    text: string, options: ConversationWorkflowOptions, source: 'agent' | 'chat'
  ): Promise<ChatWorkflowStartResult | undefined> => {
    if (!text.trim()) return undefined
    const attempt = createMissionLaunchAttempt({ slot: `conversation:${options.conversationId}` })
    let identity = attempt.pending()
    if (identity) {
      if ((options.clientRequestId && options.clientRequestId !== identity.operationId)
        || !matchesConversationLaunchContext(identity.commandSnapshot, { ...options, goal: text, source })) {
        throw new MissionLaunchStateError('BUSY', '会话已有另一个待确认提交，请先恢复原操作。')
      }
    } else {
      const command = conversationLaunchCommand({
        ...options, goal: text, source, chatContextId: contextId.value, chatRoleId: currentRoleId.value,
        messages: [...messages.value, { role: 'user', content: text }]
      })
      identity = attempt.begin(command, options.clientRequestId)
    }
    const operationId = identity.operationId
    const pending = pendingConversationStarts.get(operationId)
    if (pending) return pending
    const conversationOwner = historyGeneration
    const operation = Promise.resolve().then(async () => {
      const userMessage = conversationOwner === historyGeneration
        ? messages.value.find(message => message.role === 'user' && message.workflowClientRequestId === operationId) || pushUserMessage(text)
        : { id: Date.now(), role: 'user' as const, content: text, workflowClientRequestId: operationId }
      userMessage.workflowClientRequestId = operationId
      const launch = await attempt.resume(operationId)
      const response = launch.run
      const binding: ChatWorkflowBinding = {
        conversationId: options.conversationId, messageId: String(userMessage.id), missionId: response.missionId,
        acgTaskId: response.runId, runId: response.runId, workflowId: response.workflowId || options.workflowId,
        source, clientRequestId: launch.clientRequestId, createdAt: new Date().toISOString(), status: response.status
      }
      addWorkflowBinding(binding)
      if (conversationOwner === historyGeneration
        && !messages.value.some(message => message.workflowRunId === binding.runId && message.workflowClientRequestId === operationId)) {
        messages.value.push({
          id: Date.now() + 1, role: 'assistant', content: '已创建 ACG 运行任务', createdAt: new Date(),
          modelInfo: 'AgentOS Workflow', agentMode: 'default', acgTaskId: binding.acgTaskId,
          workflowMissionId: binding.missionId, workflowRunId: binding.runId, workflowId: binding.workflowId,
          workflowStatus: binding.status, workflowClientRequestId: operationId
        })
      }
      emitHistoryRefresh()
      attempt.complete(operationId)
      return { response, binding, launch }
    }).finally(() => pendingConversationStarts.delete(operationId))
    pendingConversationStarts.set(operationId, operation)
    return operation
  }

  const upgradeToWorkflow = (
    text: string,
    options: ConversationWorkflowOptions
  ) => startConversationWorkflow(text, options, 'chat')

  const startAgentRun = (
    text: string,
    options: ConversationWorkflowOptions
  ) => startConversationWorkflow(text, options, 'agent')

  const resumeMissionLaunch = (conversationId: string) => {
    const identity = pendingMissionLaunch(conversationId)
    if (!identity) throw new MissionLaunchStateError('RECONCILIATION_REQUIRED', '没有可恢复的会话提交。')
    return startConversationWorkflow(identity.commandSnapshot.semantics!.objective,
      { conversationId, clientRequestId: identity.operationId }, identity.commandSnapshot.input?.source === 'agent' ? 'agent' : 'chat')
  }

  const clearHistory = async () => {
    const generation = ++historyGeneration
    const targetContextId = contextId.value
    invalidateMessageRequest()
    const owner = messageGeneration
    if (targetContextId) await chatApi.clearHistory(targetContextId)
    if (generation === historyGeneration && owner === messageGeneration && contextId.value === targetContextId) clearMessages()
  }

  const setRole = (roleId: string | null) => {
    currentRoleId.value = roleId
  }

  const loadHistory = async (targetContextId: string) => {
    if (!targetContextId || targetContextId.startsWith('draft:')) return
    invalidateMessageRequest()
    const generation = ++historyGeneration
    loading.value = true
    isLoadingConversation.value = true
    contextId.value = targetContextId
    messages.value = []
    currentRoleId.value = null
    contextUsageState.value = null
    historyError.value = null
    conversationWorkspaceMode.value = getConversationWorkspace(targetContextId,
      new Set(conversationBindings(workflowBindings.value, targetContextId).filter(item => item.source === 'agent').map(() => targetContextId)))

    try {
      const [history, metadata] = await Promise.all([
        chatApi.getHistory(targetContextId),
        conversationApi.getConversation(targetContextId).catch(() => null)
      ])
      if (generation !== historyGeneration || contextId.value !== targetContextId) return
      if (metadata?.contextId === targetContextId) {
        currentRoleId.value = metadata.roleId || null
        if (metadata.workspaceMode === 'agent' || metadata.workspaceMode === 'chat') {
          conversationWorkspaceMode.value = metadata.workspaceMode
          setConversationWorkspace(targetContextId, metadata.workspaceMode)
        }
      } else {
        historyError.value = '会话元数据未能恢复，请重试后继续发送'
      }

      messages.value = history.map((msg: any) => ({
        id: msg.id || Date.now() + Math.random(),
        role: msg.role?.toLowerCase() === 'user' ? 'user' : 'assistant',
        content: msg.content || '',
        transcript: restoreTranscript(msg.metadata?.transcript),
        chatExecutionId: msg.metadata?.chatExecutionId,
        chatExecutionState: msg.metadata?.chatExecutionState,
        createdAt: msg.createdAt ? new Date(msg.createdAt) : new Date(),
        fileUrl: msg.fileUrl,
        confidence: msg.metadata?.confidence,
        sources: msg.metadata?.sources,
        tokensUsed: msg.metadata?.totalTokens ?? msg.metadata?.tokens_used,
        modelInfo: msg.metadata?.effectiveModel ?? msg.metadata?.model_info,
        contextFixedTokens: msg.metadata?.contextFixedTokens,
        contextWindowTokens: msg.metadata?.contextWindowTokens,
        cachedTokens: msg.metadata?.cached_tokens,
        cacheUsageAvailable: msg.metadata?.cacheUsageAvailable,
        protocolSession: msg.metadata?.protocolSession,
        lastInputTokens: msg.metadata?.last_input_tokens,
        lastOutputTokens: msg.metadata?.last_output_tokens,
        contextInputTokens: msg.metadata?.contextInputTokens,
        requestBodyBytes: msg.metadata?.requestBodyBytes ?? (msg.metadata?.contextMeasurement === 'protocol-utf8-upper-bound' ? msg.metadata?.contextInputTokens : undefined),
        responseTimings: mergeResponseTimings({}, msg.metadata?.responseTimings),
        workingContext: workingContext(msg.metadata?.workingContext),
        contextUsage: contextUsage(msg.metadata?.contextUsage),
        projectionVersion: msg.metadata?.projectionVersion,
        archivedItems: msg.metadata?.archivedItems,
        providerRequest: msg.metadata?.providerRequest,
        attemptId: msg.metadata?.attemptId,
        contextMeasurement: msg.metadata?.contextMeasurement,
        contextTokenMethod: msg.metadata?.contextTokenMethod,
        requestedThinkingMode: msg.metadata?.requestedThinkingMode,
        effectiveThinkingMode: msg.metadata?.effectiveThinkingMode,
        effectiveReasoningEffort: msg.metadata?.effectiveReasoningEffort,
        thinkingDurationMs: msg.metadata?.reasoningPhaseMs,
        reasoningContent: msg.metadata?.reasoningContent,
        reasoningTruncated: msg.metadata?.reasoningTruncated,
        inputTokens: msg.metadata?.inputTokens,
        reasoningTokens: msg.metadata?.reasoningTokens,
        outputTokens: msg.metadata?.outputTokens,
        latencyMs: msg.metadata?.latencyMs,
        executionSummary: msg.metadata?.executionSummary,
        streamError: msg.metadata?.executionSummary?.find((stage: ExecutionSummaryItem) =>
          stage.stage === 'chat_stream' && stage.status !== 'completed')?.description,
        streamActivity: msg.role?.toLowerCase() === 'user' ? undefined : 'complete',
        thinkingState: msg.metadata?.executionSummary?.some((stage: ExecutionSummaryItem) =>
          stage.stage === 'chat_stream' && stage.status !== 'completed') ? 'error'
          : msg.metadata?.thinkingEnabled ? 'complete' : undefined,
        agentMode: 'default'
      }))

      contextId.value = targetContextId


      const latestReply = [...messages.value].reverse().find(message => message.role === 'assistant')
      const lastWithUsage = [...messages.value]
        .reverse()
        .find(msg => msg.role === 'assistant' && (
          typeof msg.lastInputTokens === 'number' || typeof msg.inputTokens === 'number' ||
          typeof msg.outputTokens === 'number' ||
          typeof msg.tokensUsed === 'number'
        ))
      if (lastWithUsage && lastWithUsage === latestReply) {
        const used = typeof (lastWithUsage.lastInputTokens ?? lastWithUsage.inputTokens) === 'number'
          ? (lastWithUsage.lastInputTokens ?? lastWithUsage.inputTokens)! + (lastWithUsage.lastOutputTokens ?? lastWithUsage.outputTokens ?? 0)
          : (lastWithUsage.tokensUsed ?? null)
        applyContextUsage(used, lastWithUsage.modelInfo || null, lastWithUsage.contextWindowTokens)
        const settings = loadModelSettings()
        if (!settings.selectedModel || settings.selectedModel === '系统默认'
          || settings.selectedModel === lastWithUsage.modelInfo) {
          if (lastWithUsage.protocolSession) invalidateContextEstimate()
          else setContextEstimate(lastWithUsage.contextFixedTokens, lastWithUsage.contextTokenMethod, settings)
        } else invalidateContextEstimate()
      } else {
        // An older successful turn cannot describe a newer unmeasured/failed input.
        applyContextUsage(null, latestReply?.modelInfo || lastWithUsage?.modelInfo,
          latestReply?.contextWindowTokens ?? lastWithUsage?.contextWindowTokens)
        invalidateContextEstimate()
      }
      const lastContext = [...messages.value].reverse().find(message => typeof message.contextInputTokens === 'number')
      if (lastContext && lastContext === latestReply && typeof lastContext.inputTokens !== 'number'
        && lastContext.contextMeasurement !== 'protocol-utf8-upper-bound'
        && lastContext.contextMeasurement !== 'provider-usage') {
        applyContextUsage(lastContext.contextInputTokens!, lastContext.modelInfo, lastContext.contextWindowTokens, lastContext.contextMeasurement)
        invalidateContextEstimate()
      }
      const savedWatermark = [...messages.value].reverse().find(message => message.contextUsage)?.contextUsage
      if (savedWatermark) applyContextSnapshot(savedWatermark)
      // 投影存储才知道空闲压缩/分支边界；消息 metadata 只是同一状态的投递副本。
      if (typeof chatApi.getContextUsage === 'function') {
        const modelSettings = loadModelSettings()
        const selected = modelSettings.selectedModel === '系统默认' ? '' : modelSettings.selectedModel
        try {
          const beforeSnapshot = contextUsageState.value
          const snapshot = await chatApi.getContextUsage(targetContextId, selected,
            modelSettings.provider === 'system' ? undefined : modelSettings.baseUrl, currentRoleId.value)
          if (generation === historyGeneration && contextId.value === targetContextId && contextUsageState.value === beforeSnapshot) {
            if (!applyContextSnapshot(snapshot.contextUsage) && snapshot.contextUsage === null) {
              contextUsageState.value = null
            }
          }
        } catch { /* Preserve the last confirmed delivery if the snapshot read is unavailable. */ }
      }
    } catch (error: any) {
      if (generation !== historyGeneration || contextId.value !== targetContextId) return
      console.error('加载对话历史失败:', error)
      messages.value = []
      historyError.value = '加载对话历史失败'
    } finally {
      if (generation === historyGeneration && contextId.value === targetContextId) {
        isLoadingConversation.value = false
        loading.value = false
        const runningReply = messages.value.find(message => message.chatExecutionId && message.chatExecutionState === 'running')
        if (runningReply && !historyError.value) void sendMessageStream('', 'default', loadModelSettings(), conversationWorkspaceMode.value || 'chat', runningReply)
      }
    }
  }

  const setContextId = (id: string | null) => {
    if (id) {
      return loadHistory(id)
    } else {
      invalidateMessageRequest()
      ++historyGeneration
      contextId.value = null
      conversationWorkspaceMode.value = null
      historyError.value = null
      isLoadingConversation.value = false
      loading.value = false
      messages.value = []
      contextUsedTokens.value = null
      contextWindowTokens.value = null
      contextUsageState.value = null
    }
  }

  const addMessage = (message: Message) => {
    const completeMessage: Message = {
      ...message,
      id: message.id || Date.now().toString(),
      role: message.role || 'user',
      content: message.content || '',
      createdAt: message.createdAt || (message.timestamp ? new Date(message.timestamp) : new Date()),
      timestamp: message.timestamp || (message.createdAt ? message.createdAt.getTime() : Date.now())
    }
    messages.value.push(completeMessage)
  }

  const setMessages = (newMessages: Message[]) => {
    invalidateMessageRequest()
    messages.value = newMessages.map(msg => ({
      ...msg,
      createdAt: msg.createdAt || (msg.timestamp ? new Date(msg.timestamp) : new Date())
    }))
  }

  const clearMessages = () => {
    invalidateMessageRequest()
    ++historyGeneration
    conversationWorkspaceMode.value = null
    historyError.value = null
    isLoadingConversation.value = false
    messages.value = []
    contextId.value = null
    contextUsedTokens.value = null
    contextWindowTokens.value = null
    contextUsageState.value = null
  }

  return {
    isCompacting,
    compactionStatus,
    compactionNotice,
    compactContext,
    approvalMode,
    messages,
    loading,
    isStreaming,
    isLoadingConversation,
    workflowBindings,
    contextId,
    currentRoleId,
    conversationWorkspaceMode,
    historyError,
    migrateDraftBindings,
    contextUsedTokens,
    nextContextTokens,
    contextWindowTokens,
    contextMeasurement,
    contextUsageState,
    contextModel,
    contextModels,
    fetchContextWindows,
    sendMessage,
    sendMessageStream,
    cancelMessageStream,
    upgradeToWorkflow,
    startAgentRun,
    pendingMissionLaunch,
    resumeMissionLaunch,
    addWorkflowBinding,
    getLatestWorkflowBinding,
    getActiveWorkflowBinding,
    updateWorkflowBindingStatus,
    markWorkflowBindingInvalid,
    clearHistory,
    setRole,
    loadHistory,
    setContextId,
    addMessage,
    setMessages,
    clearMessages
  }
})

