import { localFetch } from '@/platform/api'
import { reactive } from 'vue'
import { apiUrl } from '@/platform'
import { readSseFrames } from '@/utils/sse'
import { planningContent, streamingContent } from './streamingContent'
import { createStreamBatcher } from '../../../../backend/src/shared/chat-stream/index.mjs'
import { companionRuntimeBridge } from '@/features/companion/runtimeBridge'

export interface RuntimeEvent {
  eventId: string
  eventType: string
  runId: string
  nodeId?: string | null
  attemptId?: string | null
  sequence: number
  timestamp?: string
  payload?: Record<string, any>
}

export interface NodeRuntimeState {
  agentName?: string
  agentRegistration?: { agentId: string; instanceId: string; generation: number }
  callId?: string
  reasoningBuffer?: string
  outputId: string | null
  title?: string | null
  status: string
  phase: string
  currentAttemptId: string | null
  outputBuffer: string
  chunkCount: number
  modelName: string | null
  modelStartedAt: string | null
  firstTokenAt: string | null
  lastActivityAt: string | null
  completedAt: string | null
  queuedAt?: string | null
  queueReason?: string | null
}

export interface PlanningRuntimeState {
  outputId: string | null
  modelStartedAt: string | null
  status: 'IDLE' | 'STARTING' | 'RUNNING' | 'COMPLETED' | 'FAILED'
  stage: string | null
  callKey: string | null
  modelPhase: 'IDLE' | 'STARTING' | 'WAITING_FIRST_TOKEN' | 'ACTIVE' | 'COMPLETED'
  startedAt: string | null
  firstTokenAt: string | null
  lastActivityAt: string | null
  completedAt: string | null
  ttftMs: number | null
  idleMs: number | null
  elapsedMs: number | null
  receivedChunks: number
  receivedLength: number
  outputBuffer: string
  reasoningBuffer: string
  reasoningTruncated: boolean
  chunkCount: number
  draft: {
    stage: string | null
    nodes: Array<{ key: string; title: string; capabilityId: string; status: string; rationale: string }>
    edges: Array<{ sourceKey: string; targetKey: string; relationType: string }>
  }
  retryIndex: number
  profile: Record<string, any> | null
  plan: Record<string, any> | null
  graph: Record<string, any> | null
  errorCode: string | null
}

export interface RuntimeEventStore {
  readonly runId: string
  terminal: boolean
  lastSequence: number
  readonly nodes: Record<string, NodeRuntimeState>
  readonly planning: PlanningRuntimeState
  readonly workspaceReview?: WorkspaceReviewRuntimeState
  readonly outputHistory?: RuntimePublicOutput[]
  readonly activity?: { events: RuntimeEvent[]; approvalRevision: number }
  apply(event: RuntimeEvent): void
}

export interface WorkspaceReviewRuntimeState {
  status: 'IDLE' | 'BLOCKED' | 'RETRYING'
  errorCode: string | null
  lastActivityAt: string | null
}

export interface RuntimePublicOutput {
  id: string
  nodeId?: string
  attemptId?: string | null
  agentName?: string
  agentRegistration?: NodeRuntimeState['agentRegistration']
  modelName?: string | null
  callId?: string
  kind: 'planning' | 'node'
  title: string
  timestamp: string | null
  text: string
  failed: boolean
  stage?: string | null
  state?: 'completed' | 'interrupted' | 'retrying'
  elapsedMs?: number | null
  reasoning?: string
  reasoningTruncated?: boolean
}

const createPlanningState = (): PlanningRuntimeState => ({
  outputId: null,
  modelStartedAt: null,
  status: 'IDLE',
  stage: null,
  callKey: null,
  modelPhase: 'IDLE',
  startedAt: null,
  firstTokenAt: null,
  lastActivityAt: null,
  completedAt: null,
  ttftMs: null,
  idleMs: null,
  elapsedMs: null,
  receivedChunks: 0,
  receivedLength: 0,
  outputBuffer: '',
  reasoningBuffer: '',
  reasoningTruncated: false,
  chunkCount: 0,
  draft: { stage: null, nodes: [], edges: [] },
  retryIndex: 0,
  profile: null,
  plan: null,
  graph: null,
  errorCode: null,
})

const createWorkspaceReviewState = (): WorkspaceReviewRuntimeState => ({
  status: 'IDLE',
  errorCode: null,
  lastActivityAt: null,
})

const PLANNER_EVENTS = new Set([
  'planner.started',
  'planner.stage.started',
  'planner.stage.retry',
  'planner.model.started',
  'planner.model.first_token',
  'planner.model.activity',
  'planner.model.output.delta',
  'planner.model.reasoning.delta',
  'planner.draft.updated',
  'planner.model.completed',
  'planner.stage.completed',
  'planner.profile.resolved',
  'planner.plan.parsed',
  'planner.graph.compiled',
  'planner.completed',
  'planner.failed',
])

const timestampOrNow = (event: RuntimeEvent) => event.timestamp || new Date().toISOString()
const numberOrNull = (value: unknown) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null
}

export class RunRuntimeStore {
  readonly runId: string
  terminal = false
  lastSequence = -1
  readonly nodes = reactive<Record<string, NodeRuntimeState>>({})
  readonly planning = reactive<PlanningRuntimeState>(createPlanningState())
  readonly workspaceReview = reactive<WorkspaceReviewRuntimeState>(createWorkspaceReviewState())
  readonly outputHistory = reactive<RuntimePublicOutput[]>([])
  readonly activity = reactive({ events: [] as RuntimeEvent[], approvalRevision: 0 })
  private pending = new Map<string, string>()
  private pendingNodeReasoning = new Map<string, string>()
  private pendingPlanning: string | null = null
  private pendingReasoning: string | null = null
  private retiredAttempts = new Map<string, Set<string>>()
  private batcher = createStreamBatcher(() => this.flushPending())

  constructor(runId: string) { this.runId = runId }

  private node(id: string): NodeRuntimeState {
    return this.nodes[id] ||= {
      outputId: null,
      status: 'WAITING',
      phase: 'WAITING',
      currentAttemptId: null,
      outputBuffer: '',
      chunkCount: 0,
      modelName: null,
      modelStartedAt: null,
      firstTokenAt: null,
      lastActivityAt: null,
      completedAt: null,
    }
  }

  apply(event: RuntimeEvent): boolean {
    if (!Number.isSafeInteger(event.sequence) || event.sequence < 0) return false
    if (event.runId === this.runId && event.eventType === 'runtime.display.snapshot') {
      const snapshot = event.payload
      if (snapshot?.schemaVersion !== 1 || !Array.isArray(snapshot.events)) return false
      this.batcher.flush()
      this.pending.clear()
      this.pendingNodeReasoning.clear()
      this.pendingPlanning = null
      this.pendingReasoning = null
      this.retiredAttempts.clear()
      for (const id of Object.keys(this.nodes)) delete this.nodes[id]
      Object.assign(this.planning, createPlanningState())
      Object.assign(this.workspaceReview, createWorkspaceReviewState())
      this.outputHistory.splice(0)
      this.activity.events.splice(0)
      this.terminal = false
      this.lastSequence = -1
      for (const item of snapshot.events) {
        if (item?.eventType !== 'runtime.display.snapshot' && item?.sequence <= event.sequence) this.apply(item)
      }
      this.batcher.flush()
      if (Array.isArray(snapshot.settledAttempts)) {
        for (const item of snapshot.settledAttempts) {
          if (typeof item?.nodeId !== 'string' || typeof item?.attemptId !== 'string') continue
          const node = this.nodes[item.nodeId]
          if (node?.currentAttemptId === item.attemptId && node.status !== 'COMPLETED' && ['failed', 'cancelled'].includes(item.status)) {
            this.settleNode(node, item.status === 'failed' ? 'FAILED' : 'CANCELLED', node.lastActivityAt)
          }
        }
      }
      // Replay historical output before retiring Attempts from the formal resume boundary.
      if (snapshot.retiredAttempts && typeof snapshot.retiredAttempts === 'object') {
        for (const [id, attempts] of Object.entries(snapshot.retiredAttempts)) {
          if (Array.isArray(attempts)) this.retiredAttempts.set(id, new Set(attempts.filter((value): value is string => typeof value === 'string')))
        }
      }
      for (const [id, node] of Object.entries(this.nodes)) {
        if (node.currentAttemptId && this.retiredAttempts.get(id)?.has(node.currentAttemptId)) {
          this.archiveNode(id, node.status === 'COMPLETED' ? 'completed' : 'interrupted')
          this.pending.delete(id)
          this.pendingNodeReasoning.delete(id)
          delete this.nodes[id]
        }
      }
      this.batcher.flush()
      this.lastSequence = event.sequence
      return true
    }
    if (event.runId !== this.runId || event.sequence <= this.lastSequence) return false
    if (this.terminal) return false
    this.lastSequence = event.sequence
    if (/^(node|model|tool)\./.test(event.eventType) && event.nodeId && event.attemptId
      && this.retiredAttempts.get(event.nodeId)?.has(event.attemptId)) return false
    if (!['model.output.delta', 'model.reasoning.delta', 'planner.model.output.delta', 'planner.model.reasoning.delta'].includes(event.eventType)) this.batcher.flush()
    if (['tool.approval_required', 'tool.approval_resolved', 'tool.capacity_waiting', 'tool.execution_started', 'tool.execution_completed',
      'node.queued', 'node.started', 'node.completed', 'node.failed', 'node.cancelled'].includes(event.eventType)) {
      if (!this.activity.events.some(item => item.eventId === event.eventId)) {
        this.activity.events.push(event)
        if (this.activity.events.length > 100) this.activity.events.shift()
      }
      if (event.eventType.startsWith('tool.approval_')) this.activity.approvalRevision++
    }
    if (['workspace.review.blocked', 'workspace.review.retry', 'workspace.review.resumed'].includes(event.eventType)) {
      const resumed = event.eventType === 'workspace.review.resumed'
      this.workspaceReview.status = resumed ? 'IDLE' : event.eventType === 'workspace.review.blocked' ? 'BLOCKED' : 'RETRYING'
      this.workspaceReview.errorCode = !resumed && typeof event.payload?.errorCode === 'string' ? event.payload.errorCode : null
      this.workspaceReview.lastActivityAt = timestampOrNow(event)
      return
    }
    if (PLANNER_EVENTS.has(event.eventType) || event.eventType.startsWith('planner.')) {
      this.applyPlanner(event)
      return true
    }
    if (['run.completed', 'run.failed', 'run.cancelled', 'run.superseded'].includes(event.eventType)) {
      // A queued node has no execution output to archive. The Run no longer
      // owns a live queue after its terminal event.
      for (const [id, node] of Object.entries(this.nodes)) {
        if (node.status === 'QUEUED') delete this.nodes[id]
      }
      this.terminal = true
      return true
    }
    const id = event.nodeId || ''
    if (!id) return true
    const n = this.node(id)
    const p = event.payload || {}
    const attempt = event.attemptId || n.currentAttemptId
    if (attempt && this.retiredAttempts.get(id)?.has(attempt)) return false
    const attemptChanged = Boolean(attempt && n.currentAttemptId !== attempt)
    if (attempt && n.currentAttemptId !== attempt) {
      this.archiveNode(id)
      if (n.currentAttemptId) {
        const retired = this.retiredAttempts.get(id) || new Set<string>()
        retired.add(n.currentAttemptId)
        this.retiredAttempts.set(id, retired)
      }
      n.currentAttemptId = attempt
      n.status = 'WAITING'
      n.phase = 'WAITING'
      n.outputBuffer = ''
      n.reasoningBuffer = ''
      n.chunkCount = 0
      n.outputId = null
      n.modelStartedAt = null
      n.firstTokenAt = null
      n.lastActivityAt = null
      n.completedAt = null
      n.queuedAt = null
      n.queueReason = null
      n.agentRegistration = undefined
      n.modelName = null
      this.pending.delete(id)
      this.pendingNodeReasoning.delete(id)
    }
    if (!attemptChanged && ['COMPLETED', 'FAILED', 'CANCELLED'].includes(n.status)) return false
    if (typeof p.nodeTitle === 'string') n.title = p.nodeTitle
    if (typeof p.agentName === 'string') n.agentName = p.agentName
    if (event.eventType !== 'node.queued' && p.agentRegistration && typeof p.agentRegistration.instanceId === 'string') n.agentRegistration = p.agentRegistration
    if (event.eventType === 'node.queued') {
      if (n.status === 'RUNNING') return false
      n.status = 'QUEUED'
      n.phase = 'WAITING_RESOURCE'
      n.queuedAt ||= typeof p.queuedAt === 'string' ? p.queuedAt : timestampOrNow(event)
      n.queueReason = typeof p.reason === 'string' ? p.reason : null
      n.lastActivityAt = timestampOrNow(event)
      n.agentRegistration = undefined
    } else if (event.eventType === 'node.started') {
      n.status = 'RUNNING'
      n.phase = 'WAITING'
      n.queuedAt = null
      n.queueReason = null
    }
    else if (event.eventType === 'model.started') {
      this.archiveNode(id)
      n.outputId = event.eventId
      n.status = 'RUNNING'
      n.queuedAt = null
      n.queueReason = null
      n.phase = 'MODEL_STARTING'
      n.outputBuffer = ''
      n.reasoningBuffer = ''
      n.chunkCount = 0
      n.firstTokenAt = null
      n.lastActivityAt = null
      this.pending.delete(id)
      this.pendingNodeReasoning.delete(id)
      n.modelStartedAt = timestampOrNow(event)
      n.callId = typeof p.callId === 'string' ? p.callId : undefined
      n.modelName = String(p.model || '') || n.modelName
    } else if (event.eventType === 'model.first_token') {
      n.phase = 'STREAMING'
      n.firstTokenAt = timestampOrNow(event)
    } else if (event.eventType === 'model.activity') {
      n.phase = 'STREAMING'
      n.lastActivityAt = timestampOrNow(event)
    } else if (event.eventType === 'model.reasoning.delta') {
      n.outputId ||= event.eventId
      n.modelStartedAt ||= timestampOrNow(event)
      n.lastActivityAt = timestampOrNow(event)
      const delta = String(p.delta || '')
      const base = this.pendingNodeReasoning.get(id) ?? n.reasoningBuffer ?? ''
      this.pendingNodeReasoning.set(id, (base + delta).slice(-65536))
      this.schedule(`node-reasoning:${id}`, delta, attempt || undefined)
    } else if (event.eventType === 'model.output.delta') {
      n.outputId ||= event.eventId
      n.modelStartedAt ||= timestampOrNow(event)
      n.phase = 'STREAMING'
      n.lastActivityAt = timestampOrNow(event)
      n.chunkCount++
      const base = this.pending.get(id) ?? n.outputBuffer
      const next = typeof p.publicText === 'string' ? JSON.stringify({ content: p.publicText }) : base + String(p.delta || '')
      this.pending.set(id, next.slice(0, 65536))
      this.schedule(`node:${id}`, String(p.delta || ''), attempt || undefined)
    } else if (event.eventType === 'model.completed') {
      if (this.pending.has(id)) n.outputBuffer = this.pending.get(id)!
      this.pending.delete(id)
      n.phase = 'FINALIZING'
    }
    else if (event.eventType === 'node.completed' || event.eventType === 'node.failed' || event.eventType === 'node.cancelled') {
      this.settleNode(n, event.eventType === 'node.completed' ? 'COMPLETED' : event.eventType === 'node.failed' ? 'FAILED' : 'CANCELLED', timestampOrNow(event))
    }
    return true
  }

  private settleNode(node: NodeRuntimeState, status: 'COMPLETED' | 'FAILED' | 'CANCELLED', at: string | null) {
    node.status = node.phase = status
    node.completedAt = at
    node.queuedAt = node.queueReason = null
  }

  private applyPlanner(event: RuntimeEvent) {
    const state = this.planning
    const p = event.payload || {}
    const at = timestampOrNow(event)
    const elapsed = numberOrNull(p.elapsedMs)
    if (!state.startedAt) state.startedAt = at
    if (event.eventType === 'planner.started') {
      state.status = 'STARTING'
      state.startedAt = at
      state.completedAt = null
      state.errorCode = null
    } else if (event.eventType === 'planner.stage.started') {
      const nextCallKey = String(p.callKey || '') || state.callKey
      if (nextCallKey !== state.callKey) {
        this.archivePlanning()
        state.outputBuffer = ''
        state.reasoningBuffer = ''
        state.reasoningTruncated = false
        state.chunkCount = 0
        state.outputId = null
        state.modelStartedAt = null
        state.elapsedMs = null
      }
      state.status = 'RUNNING'
      state.modelPhase = 'STARTING'
      state.stage = String(p.stage || '') || state.stage
      state.callKey = nextCallKey
      state.retryIndex = numberOrNull(p.retryIndex) ?? state.retryIndex
    } else if (event.eventType === 'planner.stage.retry') {
      this.archivePlanning('retrying')
      state.status = 'RUNNING'
      state.modelPhase = 'STARTING'
      state.stage = String(p.stage || '') || state.stage
      state.callKey = String(p.callKey || '') || state.callKey
      state.retryIndex = numberOrNull(p.retryIndex) ?? state.retryIndex + 1
      state.outputBuffer = ''
      state.reasoningBuffer = ''
      state.reasoningTruncated = false
      state.chunkCount = 0
      state.outputId = null
      state.modelStartedAt = null
      state.elapsedMs = null
    } else if (event.eventType === 'planner.model.started') {
      this.archivePlanning()
      state.outputBuffer = ''
      state.reasoningBuffer = ''
      state.reasoningTruncated = false
      state.chunkCount = 0
      state.outputId = event.eventId
      state.modelStartedAt = at
      state.firstTokenAt = null
      state.elapsedMs = null
      state.status = 'RUNNING'
      state.modelPhase = 'WAITING_FIRST_TOKEN'
      state.stage = String(p.stage || '') || state.stage
      state.callKey = String(p.callKey || '') || state.callKey
    } else if (event.eventType === 'planner.model.first_token') {
      state.status = 'RUNNING'
      state.modelPhase = 'ACTIVE'
      state.firstTokenAt = at
      state.ttftMs = elapsed ?? state.ttftMs
    } else if (event.eventType === 'planner.model.activity') {
      state.status = 'RUNNING'
      state.modelPhase = 'ACTIVE'
      state.lastActivityAt = at
      state.elapsedMs = elapsed ?? state.elapsedMs
      state.idleMs = numberOrNull(p.idleMs) ?? state.idleMs
      state.receivedChunks = numberOrNull(p.receivedChunks) ?? state.receivedChunks
      state.receivedLength = numberOrNull(p.receivedLength) ?? state.receivedLength
    } else if (event.eventType === 'planner.model.reasoning.delta') {
      state.outputId ||= event.eventId
      state.modelStartedAt ||= at
      state.status = 'RUNNING'
      state.modelPhase = 'ACTIVE'
      state.lastActivityAt = at
      state.stage = String(p.stage || '') || state.stage
      state.callKey = String(p.callKey || '') || state.callKey
      const delta = typeof p.delta === 'string' ? p.delta : ''
      const next = (this.pendingReasoning ?? state.reasoningBuffer) + delta
      state.reasoningTruncated ||= next.length > 65536
      this.pendingReasoning = next.slice(-65536)
      this.schedule('planner-reasoning', delta, `${state.callKey}:${state.retryIndex}`)
    } else if (event.eventType === 'planner.model.output.delta') {
      state.outputId ||= event.eventId
      state.modelStartedAt ||= at
      state.status = 'RUNNING'
      state.modelPhase = 'ACTIVE'
      state.lastActivityAt = at
      state.stage = String(p.stage || '') || state.stage
      state.callKey = String(p.callKey || '') || state.callKey
      state.chunkCount += 1
      const next = typeof p.publicText === 'string' ? JSON.stringify({ content: p.publicText })
        : (this.pendingPlanning ?? state.outputBuffer) + String(p.delta || '')
      this.pendingPlanning = next.length > 65536 ? next.slice(-65536) : next
      this.schedule('planner', String(p.delta || ''), `${state.callKey}:${state.retryIndex}`)
    } else if (event.eventType === 'planner.draft.updated') {
      const nodes = Array.isArray(p.nodes) ? p.nodes : []
      const edges = Array.isArray(p.edges) ? p.edges : []
      state.draft = {
        stage: String(p.stage || '') || state.stage,
        nodes: nodes.slice(0, 100).map(item => ({
          key: String(item?.key || ''),
          title: String(item?.title || item?.key || ''),
          capabilityId: String(item?.capabilityId || ''),
          status: String(item?.status || 'outlined'),
          rationale: String(item?.rationale || ''),
        })).filter(item => item.key),
        edges: edges.slice(0, 300).map(item => ({
          sourceKey: String(item?.sourceKey || ''),
          targetKey: String(item?.targetKey || ''),
          relationType: String(item?.relationType || 'depends_on'),
        })).filter(item => item.sourceKey && item.targetKey),
      }
    } else if (event.eventType === 'planner.model.completed') {
      state.modelPhase = 'COMPLETED'
      state.elapsedMs = elapsed ?? state.elapsedMs
    } else if (event.eventType === 'planner.stage.completed') {
      state.status = 'RUNNING'
      state.stage = String(p.stage || '') || state.stage
    } else if (event.eventType === 'planner.profile.resolved') {
      state.status = 'RUNNING'
      state.profile = { ...p }
    } else if (event.eventType === 'planner.plan.parsed') {
      state.status = 'RUNNING'
      state.plan = { ...p }
    } else if (event.eventType === 'planner.graph.compiled') {
      state.status = 'RUNNING'
      state.graph = { ...p }
    } else if (event.eventType === 'planner.completed') {
      state.status = 'COMPLETED'
      state.modelPhase = 'COMPLETED'
      state.completedAt = at
      state.elapsedMs = elapsed ?? state.elapsedMs
    } else if (event.eventType === 'planner.failed') {
      state.status = 'FAILED'
      state.completedAt = at
      state.errorCode = String(p.errorCode || '') || null
    }
  }

  private retainOutput(output: RuntimePublicOutput) {
    if ((!output.text && !output.reasoning) || this.outputHistory.some(item => item.id === output.id)) return
    this.outputHistory.push(output)
    const size = (item: RuntimePublicOutput) => item.text.length + (item.reasoning?.length || 0)
    let length = this.outputHistory.reduce((sum, item) => sum + size(item), 0)
    while (this.outputHistory.length > 32 || length > 262144) length -= size(this.outputHistory.shift()!)
  }

  private archiveNode(id: string, state?: RuntimePublicOutput['state']) {
    const node = this.nodes[id]
    if (!node?.outputId) return
    this.retainOutput({ id: node.outputId, kind: 'node', nodeId: id, attemptId: node.currentAttemptId,
      agentName: node.agentName, agentRegistration: node.agentRegistration, modelName: node.modelName, callId: node.callId, title: node.title || '当前步骤', timestamp: node.modelStartedAt,
      text: streamingContent(this.pending.get(id) ?? node.outputBuffer, true), reasoning: this.pendingNodeReasoning.get(id) ?? node.reasoningBuffer, failed: node.status === 'FAILED', state })
  }

  private archivePlanning(outcome?: RuntimePublicOutput['state']) {
    const state = this.planning
    if (!state.outputId) return
    this.retainOutput({ id: state.outputId, kind: 'planning', title: '规划过程', timestamp: state.modelStartedAt,
      text: planningContent(state.outputBuffer), failed: state.status === 'FAILED', stage: state.stage,
      reasoning: state.reasoningBuffer, reasoningTruncated: state.reasoningTruncated,
      state: outcome || (state.status === 'FAILED' ? 'interrupted' : state.modelPhase === 'COMPLETED' ? 'completed' : 'interrupted'), elapsedMs: state.elapsedMs })
  }

  private flushPending() {
    for (const [id, value] of this.pending) this.node(id).outputBuffer = value
    this.pending.clear()
    for (const [id, value] of this.pendingNodeReasoning) this.node(id).reasoningBuffer = value
    this.pendingNodeReasoning.clear()
    if (this.pendingPlanning !== null) this.planning.outputBuffer = this.pendingPlanning
    this.pendingPlanning = null
    if (this.pendingReasoning !== null) this.planning.reasoningBuffer = this.pendingReasoning
    this.pendingReasoning = null
  }

  private schedule(partId: string, delta: string, attemptId?: string) {
    // The shared timer/size limits work in hidden views too. Metadata remains
    // immediate; only text is combined, with controls flushed before folding.
    this.batcher.accept({ event: 'content_delta', requestId: this.runId, data: { partId, attemptId, delta } })
  }

  dispose() {
    this.batcher.flush()
    this.batcher.dispose()
  }
}

export class RuntimeEventClient {
  private controller: AbortController | null = null
  private generation = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null

  constructor(private readonly store: RunRuntimeStore) {}

  connect() {
    this.disconnect()
    if (typeof fetch === 'undefined' || typeof AbortController === 'undefined') return
    if (this.store.terminal) return
    // This is a transient, non-replaying stream. The broker can restart its
    // sequence after losing its last subscriber or after a process restart.
    // Dedupe/order checks apply within this new connection, not across epochs.
    this.store.lastSequence = -1
    const controller = new AbortController()
    const generation = ++this.generation
    this.controller = controller
    void this.consume(controller, generation)
  }

  disconnect() {
    this.generation += 1
    if (this.reconnectTimer !== null) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    this.controller?.abort()
    this.controller = null
  }

  private async consume(controller: AbortController, generation: number) {

    const headers: Record<string, string> = { Accept: 'text/event-stream' }
    try {
      const response = await localFetch(apiUrl(`/api/agentos/v2/runs/${this.store.runId}/events`), {
        method: 'GET',
        headers,
        cache: 'no-store',
        signal: controller.signal
      })
      if (generation !== this.generation || controller.signal.aborted) return
      if ([401, 403, 404, 410].includes(response.status)) {
        this.disconnect() // Configuration failures require an explicit reconnect.
        return
      }
      if (!response.ok) throw new Error(`Runtime event stream failed with HTTP ${response.status}`)
      if (!response.body) throw new Error('Runtime event stream has no response body')
      // Reconcile approvals created while disconnected, even without a Run revision change.
      this.store.activity.approvalRevision++

      for await (const { data } of readSseFrames(response.body, { signal: controller.signal, flushAtEof: true })) {
        if (generation !== this.generation || controller.signal.aborted) return
        this.consumeData(data)
        if (this.store.terminal) break
      }
    } catch (error) {
      if ((error as { name?: string })?.name === 'AbortError') return
    } finally {
      // A proxy timeout/clean EOF can end a still-active Run as well as throw.
      // Reconnect observes events only; it never resubmits execution commands.
      if (generation === this.generation && !controller.signal.aborted && !this.store.terminal) {
        this.reconnectTimer = setTimeout(() => {
          if (generation === this.generation && !this.store.terminal) this.connect()
        }, 1000)
      }
    }
  }

  private consumeData(data: string) {
    if (!data || data === '[DONE]') return
    let event: RuntimeEvent
    try { event = JSON.parse(data) as RuntimeEvent }
    catch { return /* A malformed frame must not terminate the runtime stream. */ }
    if (!event || typeof event.eventType !== 'string') return
    const accepted = this.store.apply(event)
    if (accepted && event.eventType !== 'runtime.display.snapshot') companionRuntimeBridge.publishAccepted(event)
    if (this.store.terminal) this.disconnect()
  }
}

const shared = new Map<string, { store: RunRuntimeStore; client: RuntimeEventClient; refs: number; observedRevision: number }>()
const ensureShared = (runId: string) => {
  let item = shared.get(runId)
  if (!item) {
    const store = new RunRuntimeStore(runId)
    const client = new RuntimeEventClient(store)
    item = { store, client, refs: 0, observedRevision: -1 }
    shared.set(runId, item)
    client.connect()
  }
  return item
}

export const getRunRuntimeStore = (runId: string | null) => {
  if (!runId) return null
  return ensureShared(runId).store
}

export const acquireRunRuntimeStore = (runId: string | null) => {
  if (!runId) return null
  const item = ensureShared(runId)
  item.refs += 1
  return item.store
}

/** A fresh authenticated Run snapshot may reopen observation after same-Run recovery. */
export const reconcileRunRuntimeStore = (run: { runId: string; status: string; runtimeRevision?: number }) => {
  const item = shared.get(run.runId)
  const revision = run.runtimeRevision
  if (!item || !Number.isSafeInteger(revision) || revision! <= item.observedRevision) return
  item.observedRevision = revision!
  if (item.store.terminal && ['pending', 'planning', 'running', 'retrying', 'waiting_review'].includes(run.status)) {
    item.store.terminal = false
    item.client.connect()
  }
}

export const releaseRunRuntimeStore = (runId: string | null, store?: RuntimeEventStore | null) => {
  if (!runId) return
  const item = shared.get(runId)
  if (!item || (store && item.store !== store)) return
  item.refs = Math.max(0, item.refs - 1)
  if (item.refs === 0) {
    item.client.disconnect()
    item.store.dispose()
    shared.delete(runId)
  }
}
