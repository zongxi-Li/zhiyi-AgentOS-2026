import { reactive } from 'vue'
import { apiUrl } from '@/platform'

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
  retryIndex: number
  profile: Record<string, any> | null
  plan: Record<string, any> | null
  graph: Record<string, any> | null
  errorCode: string | null
}

export interface RuntimeEventStore {
  readonly runId: string
  lastSequence: number
  readonly nodes: Record<string, NodeRuntimeState>
  readonly planning: PlanningRuntimeState
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
  'planner.model.completed',
  'planner.stage.completed',
  'planner.profile.resolved',
  'planner.plan.parsed',
  'planner.graph.compiled',
  'planner.completed',
  'planner.failed',
])

const EVENT_TYPES = [
  ...PLANNER_EVENTS,
  'node.started',
  'node.completed',
  'node.failed',
  'model.started',
  'model.first_token',
  'model.activity',
  'model.output.delta',
  'model.completed',
]

const timestampOrNow = (event: RuntimeEvent) => event.timestamp || new Date().toISOString()
const numberOrNull = (value: unknown) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null
}

export class RunRuntimeStore {
  readonly runId: string
  lastSequence = 0
  readonly nodes = reactive<Record<string, NodeRuntimeState>>({})
  readonly planning = reactive<PlanningRuntimeState>(createPlanningState())
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
    if (PLANNER_EVENTS.has(event.eventType) || event.eventType.startsWith('planner.')) {
      this.applyPlanner(event)
      return
    }
    const id = event.nodeId || ''
    if (!id) return
    const n = this.node(id)
    const p = event.payload || {}
    const attempt = event.attemptId || n.currentAttemptId
    if (n.status === 'COMPLETED' || n.status === 'FAILED') return
    if (attempt && n.currentAttemptId !== attempt) {
      n.currentAttemptId = attempt
      n.outputBuffer = ''
      n.chunkCount = 0
    }
    if (event.eventType === 'node.started') n.status = 'RUNNING'
    else if (event.eventType === 'model.started') {
      n.phase = 'MODEL_STARTING'
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
      this.pending.set(id, n.outputBuffer + String(p.delta || ''))
      this.schedule()
    } else if (event.eventType === 'model.completed') n.phase = 'FINALIZING'
    else if (event.eventType === 'node.completed') {
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
      state.callKey = String(p.callKey || '') || state.callKey
      state.retryIndex = numberOrNull(p.retryIndex) ?? state.retryIndex
    } else if (event.eventType === 'planner.stage.retry') {
      state.status = 'RUNNING'
      state.modelPhase = 'STARTING'
      state.stage = String(p.stage || '') || state.stage
      state.callKey = String(p.callKey || '') || state.callKey
      state.retryIndex = numberOrNull(p.retryIndex) ?? state.retryIndex + 1
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
  private source: EventSource | null = null
  private listeners: Array<[string, EventListener]> = []

  constructor(private readonly store: RunRuntimeStore) {}

  connect() {
    this.disconnect()
    if (typeof EventSource === 'undefined') return
    const source = new EventSource(apiUrl(`/api/agentos/v2/runs/${this.store.runId}/events`))
    const consume: EventListener = event => {
      try {
        const message = event as MessageEvent<string>
        this.store.apply(JSON.parse(message.data))
      } catch {
        // Transient malformed events must not break the shared stream.
      }
    }
    source.onmessage = consume
    for (const eventType of EVENT_TYPES) {
      source.addEventListener(eventType, consume)
      this.listeners.push([eventType, consume])
    }
    this.source = source
  }

  disconnect() {
    if (this.source) {
      for (const [eventType, listener] of this.listeners) this.source.removeEventListener(eventType, listener)
      this.listeners = []
      this.source.close()
    }
    this.source = null
  }
}

const shared = new Map<string, { store: RunRuntimeStore; client: RuntimeEventClient }>()
export const getRunRuntimeStore = (runId: string | null) => {
  if (!runId) return null
  let item = shared.get(runId)
  if (!item) {
    const store = new RunRuntimeStore(runId)
    const client = new RuntimeEventClient(store)
    client.connect()
    item = { store, client }
    shared.set(runId, item)
  }
  return item.store
}
