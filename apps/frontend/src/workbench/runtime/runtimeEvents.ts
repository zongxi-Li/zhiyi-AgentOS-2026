import { localFetch } from '@/platform/api'
import { reactive } from 'vue'
import { apiUrl } from '@/platform'
import { readSseFrames } from '@/utils/sse'

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
}

export interface PlanningRuntimeState {
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
  readonly activity?: { events: RuntimeEvent[]; approvalRevision: number }
  apply(event: RuntimeEvent): void
}

const createPlanningState = (): PlanningRuntimeState => ({
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
  chunkCount: 0,
  draft: { stage: null, nodes: [], edges: [] },
  retryIndex: 0,
  profile: null,
  plan: null,
  graph: null,
  errorCode: null,
})

const PLANNER_EVENTS = new Set([
  'planner.started',
  'planner.stage.started',
  'planner.stage.retry',
  'planner.model.started',
  'planner.model.first_token',
  'planner.model.activity',
  'planner.model.output.delta',
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
  readonly activity = reactive({ events: [] as RuntimeEvent[], approvalRevision: 0 })
  private pending = new Map<string, string>()
  private frame = 0

  constructor(runId: string) { this.runId = runId }

  private node(id: string): NodeRuntimeState {
    return this.nodes[id] ||= {
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

  apply(event: RuntimeEvent) {
    if (event.runId !== this.runId || event.sequence <= this.lastSequence) return
    this.lastSequence = event.sequence
    if (['tool.approval_required', 'tool.approval_resolved', 'tool.execution_started', 'tool.execution_completed',
      'node.started', 'node.completed', 'node.failed'].includes(event.eventType)) {
      if (!this.activity.events.some(item => item.eventId === event.eventId)) {
        this.activity.events.push(event)
        if (this.activity.events.length > 100) this.activity.events.shift()
      }
      if (event.eventType.startsWith('tool.approval_')) this.activity.approvalRevision++
    }
    if (PLANNER_EVENTS.has(event.eventType) || event.eventType.startsWith('planner.')) {
      this.applyPlanner(event)
      return
    }
    if (event.eventType === 'run.completed' || event.eventType === 'run.failed' || event.eventType === 'run.cancelled') {
      this.terminal = true
      return
    }
    const id = event.nodeId || ''
    if (!id) return
    const n = this.node(id)
    const p = event.payload || {}
    if (typeof p.nodeTitle === 'string') n.title = p.nodeTitle
    const attempt = event.attemptId || n.currentAttemptId
    const attemptChanged = Boolean(attempt && n.currentAttemptId !== attempt)
    if (attempt && n.currentAttemptId !== attempt) {
      n.currentAttemptId = attempt
      n.status = 'WAITING'
      n.phase = 'WAITING'
      n.outputBuffer = ''
      n.chunkCount = 0
      this.pending.delete(id)
    }
    if (!attemptChanged && (n.status === 'COMPLETED' || n.status === 'FAILED')) return
    if (event.eventType === 'node.started') n.status = 'RUNNING'
    else if (event.eventType === 'model.started') {
      n.status = 'RUNNING'
      n.phase = 'MODEL_STARTING'
      n.outputBuffer = ''
      n.chunkCount = 0
      n.firstTokenAt = null
      this.pending.delete(id)
      n.modelStartedAt = timestampOrNow(event)
      n.modelName = String(p.model || '') || n.modelName
    } else if (event.eventType === 'model.first_token') {
      n.phase = 'STREAMING'
      n.firstTokenAt = timestampOrNow(event)
    } else if (event.eventType === 'model.activity') {
      n.phase = 'STREAMING'
      n.lastActivityAt = timestampOrNow(event)
    } else if (event.eventType === 'model.output.delta') {
      n.phase = 'STREAMING'
      n.lastActivityAt = timestampOrNow(event)
      n.chunkCount++
      const base = this.pending.get(id) ?? n.outputBuffer
      const next = base + String(p.delta || '')
      this.pending.set(id, next.slice(0, 65536))
      this.schedule()
    } else if (event.eventType === 'model.completed') {
      if (this.pending.has(id)) n.outputBuffer = this.pending.get(id)!
      this.pending.delete(id)
      n.phase = 'FINALIZING'
    }
    else if (event.eventType === 'node.completed') {
      if (this.pending.has(id)) n.outputBuffer = this.pending.get(id)!
      n.status = 'COMPLETED'
      n.phase = 'COMPLETED'
      n.completedAt = timestampOrNow(event)
      this.pending.delete(id)
    } else if (event.eventType === 'node.failed') {
      n.status = 'FAILED'
      n.phase = 'FAILED'
    }
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
      state.status = 'RUNNING'
      state.modelPhase = 'STARTING'
      state.stage = String(p.stage || '') || state.stage
      const nextCallKey = String(p.callKey || '') || state.callKey
      if (nextCallKey !== state.callKey) {
        state.outputBuffer = ''
        state.chunkCount = 0
      }
      state.callKey = nextCallKey
      state.retryIndex = numberOrNull(p.retryIndex) ?? state.retryIndex
    } else if (event.eventType === 'planner.stage.retry') {
      state.status = 'RUNNING'
      state.modelPhase = 'STARTING'
      state.stage = String(p.stage || '') || state.stage
      state.callKey = String(p.callKey || '') || state.callKey
      state.retryIndex = numberOrNull(p.retryIndex) ?? state.retryIndex + 1
      state.outputBuffer = ''
      state.chunkCount = 0
    } else if (event.eventType === 'planner.model.started') {
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
    } else if (event.eventType === 'planner.model.output.delta') {
      state.status = 'RUNNING'
      state.modelPhase = 'ACTIVE'
      state.lastActivityAt = at
      state.stage = String(p.stage || '') || state.stage
      state.callKey = String(p.callKey || '') || state.callKey
      state.chunkCount += 1
      const next = state.outputBuffer + String(p.delta || '')
      state.outputBuffer = next.length > 65536 ? next.slice(-65536) : next
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

  private schedule() {
    if (this.frame) return
    this.frame = 1
    const raf = typeof requestAnimationFrame === 'function'
      ? requestAnimationFrame
      : (cb: FrameRequestCallback) => window.setTimeout(cb, 20) as any
    raf(() => {
      for (const [id, value] of this.pending) this.node(id).outputBuffer = value
      this.pending.clear()
      this.frame = 0
    })
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
      if (response.status === 401 || response.status === 403) {
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
    this.store.apply(event)
    if (this.store.terminal) this.disconnect()
  }
}

const shared = new Map<string, { store: RunRuntimeStore; client: RuntimeEventClient; refs: number }>()
const ensureShared = (runId: string) => {
  let item = shared.get(runId)
  if (!item) {
    const store = new RunRuntimeStore(runId)
    const client = new RuntimeEventClient(store)
    item = { store, client, refs: 0 }
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

export const releaseRunRuntimeStore = (runId: string | null, store?: RuntimeEventStore | null) => {
  if (!runId) return
  const item = shared.get(runId)
  if (!item || (store && item.store !== store)) return
  item.refs = Math.max(0, item.refs - 1)
  if (item.refs === 0) {
    item.client.disconnect()
    shared.delete(runId)
  }
}
