import {
  agentosApi,
  type ProvenanceConsumption,
  type ResourceObservation,
  type RuntimeInteraction,
  type RunProvenanceProjection,
  type TraceEvent,
  type WorkflowRun,
  type WorkflowTraceExport,
  type WorkspaceDiagnostic
} from '@/services/api/agentos'
import { loadResourceObservation } from './resourceObservation'

export interface RuntimeTraceObservation {
  eventId: string
  runId: string
  stepId: string | null
  eventType: string
  observation: string | null
  timestamp: string | null
  durationMs: number | null
  status: string | null
  payload: Record<string, any>
  source: 'trace'
}

export interface RuntimeCommunicationObservation {
  id: string
  source: 'provenance' | 'trace'
  sourceEventId: string
  timestamp: string | null
  producerStepId: string | null
  consumerStepId: string | null
  artifactRef: string | null
  fields: string[]
  tokenCount: number | null
  status: string | null
  summary: string
}

export interface RuntimeEventObservation {
  eventId: string
  eventType: string
  timestamp: string | null
  stepId: string | null
  target: string | null
  summary: string
  source: 'trace'
}

export interface RuntimeToolCallObservation {
  eventId: string
  tool: string | null
  name: string | null
  stepId: string | null
  status: string | null
  startedAt: string | null
  durationMs: number | null
  latencyMs: number | null
  source: 'trace'
}

export interface RuntimeProblem extends WorkspaceDiagnostic {
  source: 'projection' | 'trace'
  targetStepId?: string | null
}

export interface RuntimeAuditObservation {
  provenanceStatus: string | null
  provenanceRecordCount: number
  evidenceCount: number
  contractViolationCount: number
  recoveryCount: number
}

export interface RuntimeSelection {
  stepId?: string | null
  semanticTaskKey?: string | null
}

export interface RuntimeObservation {
  runId: string
  runStatus: string | null
  traces: RuntimeTraceObservation[]
  events: RuntimeEventObservation[]
  communication: RuntimeCommunicationObservation[]
  toolCalls: RuntimeToolCallObservation[]
  problems: RuntimeProblem[]
  audit: RuntimeAuditObservation
  resourceObservation: ResourceObservation | null
  unavailableSources: string[]
}

export interface RuntimeObservationAdapterOptions {
  historical?: boolean
  diagnostics?: readonly WorkspaceDiagnostic[]
  pollIntervalMs?: number
  onUpdate: (observation: RuntimeObservation) => void
}

export class RuntimeObservationStaleError extends Error {
  constructor() {
    super('Runtime observation request became stale')
    this.name = 'RuntimeObservationStaleError'
  }
}

const ACTIVE_RUN_STATUSES = new Set(['pending', 'planning', 'running', 'retrying', 'waiting_review'])
const DEDICATED_TRACE_TYPES = new Set(['data_produced', 'data_consumed', 'model_called', 'tool_called'])

const asRecord = (value: unknown): Record<string, any> => (
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : {}
)

const stringOrNull = (value: unknown): string | null => typeof value === 'string' && value ? value : null
const numberOrNull = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null

const eventSummary = (event: RuntimeTraceObservation | TraceEvent) => {
  const observation = 'observation' in event ? event.observation : null
  const payload = asRecord(event.payload)
  return stringOrNull(observation) || stringOrNull(payload.message) || event.eventType
}

const normalizeTrace = (trace: WorkflowTraceExport | null): RuntimeTraceObservation[] => (
  (trace?.events || []).map(event => {
    const payload = asRecord(event.payload)
    const duration = numberOrNull(event.durationMs)
    return {
      eventId: event.eventId,
      runId: event.runId,
      stepId: stringOrNull(event.stepId),
      eventType: event.eventType,
      observation: stringOrNull(event.observation),
      timestamp: stringOrNull(event.createdAt),
      durationMs: duration != null && duration > 0 ? duration : null,
      status: stringOrNull(payload.status),
      payload,
      source: 'trace'
    }
  })
)

const fieldsFromPayload = (payload: Record<string, any>) => {
  if (Array.isArray(payload.fields)) return payload.fields.filter((value): value is string => typeof value === 'string')
  if (Array.isArray(payload.consumedFields)) return payload.consumedFields.filter((value): value is string => typeof value === 'string')
  const fieldsByProducer = asRecord(payload.fieldsByProducer)
  return Object.values(fieldsByProducer).flatMap(value => Array.isArray(value) ? value : [])
    .filter((value): value is string => typeof value === 'string')
}

const communicationItem = (
  payload: Record<string, any>,
  source: 'provenance' | 'trace',
  sourceEventId: string,
  timestamp: string | null,
  index: number
): RuntimeCommunicationObservation | null => {
  const producerStepId = stringOrNull(payload.producerStepId)
    || (Array.isArray(payload.producerStepIds) ? stringOrNull(payload.producerStepIds[0]) : null)
  const consumerStepId = stringOrNull(payload.consumerStepId)
  const interaction = Boolean(payload.interactionId)
  const communicationShape = Boolean(producerStepId && consumerStepId && (
    payload.outputRef || payload.artifactRef || payload.channel || payload.fields || payload.consumedFields || interaction
  ))
  if (!communicationShape) return null
  const fields = fieldsFromPayload(payload)
  const tokenCount = numberOrNull(payload.tokens) ?? numberOrNull(payload.tokensDelivered)
  return {
    id: `${source}:${sourceEventId}:${index}`,
    source,
    sourceEventId,
    timestamp,
    producerStepId,
    consumerStepId,
    artifactRef: stringOrNull(payload.outputRef) || stringOrNull(payload.artifactRef),
    fields,
    tokenCount,
    status: stringOrNull(payload.contractStatus) || stringOrNull(payload.status),
    summary: `${producerStepId} → ${consumerStepId}${fields.length ? ` · ${fields.join(', ')}` : ''}`
  }
}

const provenanceCommunication = (provenance: RunProvenanceProjection | null) => {
  if (!provenance) return []
  const items: RuntimeCommunicationObservation[] = []
  for (const [index, event] of (provenance.events || []).entries()) {
    const payload = asRecord(event.payload)
    const item = communicationItem(
      payload,
      'provenance',
      stringOrNull(payload.eventId) || `event-${index}`,
      stringOrNull(event.createdAt) || stringOrNull(payload.createdAt),
      index
    )
    if (item) items.push(item)
  }
  if (items.length || provenance.events?.length) return items
  for (const [index, item] of (provenance.interactions || []).entries()) {
    const interaction = interactionPayload(item)
    const normalized = communicationItem(interaction, 'provenance', item.eventId, item.createdAt || null, index)
    if (normalized) items.push(normalized)
  }
  for (const [index, item] of (provenance.consumptions || []).entries()) {
    const consumption = consumptionPayload(item)
    const normalized = communicationItem(consumption, 'provenance', item.eventId, item.createdAt || null, index)
    if (normalized) items.push(normalized)
  }
  return items
}

const interactionPayload = (item: RuntimeInteraction): Record<string, any> => ({
  interactionId: item.interactionId,
  eventId: item.eventId,
  producerStepIds: item.producerStepIds,
  consumerStepId: item.consumerStepId,
  fieldsByProducer: item.fieldsByProducer,
  tokensDelivered: item.tokensDelivered,
  tokensAvailable: item.tokensAvailable,
  contractStatus: item.contractStatus
})

const consumptionPayload = (item: ProvenanceConsumption): Record<string, any> => ({
  eventId: item.eventId,
  producerStepIds: item.producerStepIds,
  consumerStepId: item.consumerStepId,
  consumedFields: item.consumedFields,
  fieldsByProducer: item.fieldsByProducer,
  tokensDelivered: item.tokensDelivered,
  tokensAvailable: item.tokensAvailable,
  contractStatus: item.contractStatus
})

const traceCommunication = (traces: RuntimeTraceObservation[]) => traces.flatMap((event, index) => {
  const item = communicationItem(event.payload, 'trace', event.eventId, event.timestamp, index)
  return item ? [item] : []
})

const normalizeEvents = (traces: RuntimeTraceObservation[]): RuntimeEventObservation[] => traces
  .filter(event => !DEDICATED_TRACE_TYPES.has(event.eventType))
  .map(event => ({
    eventId: event.eventId,
    eventType: event.eventType,
    timestamp: event.timestamp,
    stepId: event.stepId,
    target: event.stepId || stringOrNull(event.payload.target) || stringOrNull(event.payload.component) || null,
    summary: eventSummary(event),
    source: 'trace'
  }))

const normalizeToolCalls = (traces: RuntimeTraceObservation[]): RuntimeToolCallObservation[] => traces
  .filter(event => event.eventType === 'tool_called')
  .map(event => ({
    eventId: event.eventId,
    tool: stringOrNull(event.payload.tool),
    name: stringOrNull(event.payload.name),
    stepId: event.stepId,
    status: stringOrNull(event.payload.status),
    startedAt: event.timestamp,
    durationMs: event.durationMs,
    latencyMs: numberOrNull(event.payload.latencyMs),
    source: 'trace'
  }))

const normalizeProblems = (
  traces: RuntimeTraceObservation[],
  diagnostics: readonly WorkspaceDiagnostic[]
): RuntimeProblem[] => [
  ...diagnostics.map(item => ({ ...item, source: 'projection' as const })),
  ...traces
    .filter(event => event.eventType.includes('failed') || event.eventType.includes('violation') || event.eventType.includes('error'))
    .map(event => ({
      code: stringOrNull(event.payload.errorCode) || event.eventType.toUpperCase(),
      message: eventSummary(event),
      severity: 'warning' as const,
      details: event.payload,
      source: 'trace' as const,
      targetStepId: event.stepId
    }))
]

const normalizeAudit = (
  provenance: RunProvenanceProjection | null,
  traces: RuntimeTraceObservation[]
): RuntimeAuditObservation => ({
  provenanceStatus: stringOrNull(provenance?.integrityStatus),
  provenanceRecordCount: (provenance?.events?.length || 0)
    + (provenance?.productions?.length || 0)
    + (provenance?.consumptions?.length || 0)
    + (provenance?.interactions?.length || 0),
  evidenceCount: (provenance?.productions || []).reduce((count, production) => count + (production.evidenceRefs?.length || 0), 0),
  contractViolationCount: traces.filter(event => event.eventType === 'contract_violation').length,
  recoveryCount: traces.filter(event => ['run_recovered', 'run_degraded'].includes(event.eventType)).length
})

export const emptyRuntimeObservation = (runId: string, diagnostics: readonly WorkspaceDiagnostic[] = []): RuntimeObservation => ({
  runId,
  runStatus: null,
  traces: [],
  events: [],
  communication: [],
  toolCalls: [],
  problems: normalizeProblems([], diagnostics),
  audit: {
    provenanceStatus: null,
    provenanceRecordCount: 0,
    evidenceCount: 0,
    contractViolationCount: 0,
    recoveryCount: 0
  },
  resourceObservation: null,
  unavailableSources: ['run', 'trace', 'provenance', 'resource']
})

export const readRuntimeObservation = async (
  runId: string,
  diagnostics: readonly WorkspaceDiagnostic[] = [],
  options: { signal?: AbortSignal } = {}
): Promise<RuntimeObservation> => {
  const results = await Promise.allSettled([
    agentosApi.getWorkflowRun(runId, options),
    agentosApi.getWorkflowTrace(runId, options),
    agentosApi.getRunProvenance(runId, options),
    loadResourceObservation(runId, options)
  ])
  const run = results[0].status === 'fulfilled' ? results[0].value : null
  const trace = results[1].status === 'fulfilled' ? results[1].value : null
  const provenance = results[2].status === 'fulfilled' ? results[2].value : null
  const resourceObservation = results[3].status === 'fulfilled' ? results[3].value : null
  const traces = normalizeTrace(trace)
  const unavailableSources = results.flatMap((result, index) => result.status === 'rejected' ? [['run', 'trace', 'provenance', 'resource'][index]] : [])
  return {
    runId,
    runStatus: run?.status || trace?.status || null,
    traces,
    events: normalizeEvents(traces),
    communication: [...provenanceCommunication(provenance), ...traceCommunication(traces)],
    toolCalls: normalizeToolCalls(traces),
    problems: normalizeProblems(traces, diagnostics),
    audit: normalizeAudit(provenance, traces),
    resourceObservation,
    unavailableSources
  }
}

export class RuntimeObservationAdapter {
  private generation = 0
  private controller: AbortController | null = null
  private timer: ReturnType<typeof setTimeout> | null = null

  start(runId: string, options: RuntimeObservationAdapterOptions): void {
    this.stop()
    const generation = ++this.generation
    const interval = options.pollIntervalMs ?? 2000
    const refresh = async () => {
      if (generation !== this.generation) return
      this.controller?.abort()
      const controller = new AbortController()
      this.controller = controller
      try {
        const observation = await readRuntimeObservation(runId, options.diagnostics || [], { signal: controller.signal })
        if (generation !== this.generation || controller.signal.aborted) return
        options.onUpdate(observation)
        if (!options.historical && ACTIVE_RUN_STATUSES.has(observation.runStatus || '')) {
          this.timer = setTimeout(() => { void refresh() }, interval)
        }
      } finally {
        if (this.controller === controller) this.controller = null
      }
    }
    void refresh()
  }

  stop(): void {
    this.generation += 1
    this.controller?.abort()
    this.controller = null
    if (this.timer !== null) clearTimeout(this.timer)
    this.timer = null
  }
}
