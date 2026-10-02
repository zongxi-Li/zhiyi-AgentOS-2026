import type {
  RuntimeEventObservation,
  RuntimeObservation,
  RuntimeTraceObservation
} from './observation'
import type { RuntimeEvent } from './runtimeEvents'

export type RuntimePresentationKind = 'model' | 'tool' | 'command' | 'artifact' | 'error' | 'completion' | 'generic'
export type RuntimePresentationStatus = 'pending' | 'running' | 'success' | 'warning' | 'failed' | 'cancelled' | 'unknown'

export interface RuntimePresentationDetail {
  label: string
  value: string
  code?: boolean
}

export interface RuntimeSemanticPresentation {
  id: string
  kind: RuntimePresentationKind
  status: RuntimePresentationStatus
  title: string
  summary: string
  detail: string | null
  timestamp: string | null
  durationMs: number | null
  stepId: string | null
  semanticTaskKey: string | null
  eventIds: string[]
  eventTypes: string[]
  metrics: Record<string, number | string>
  expandable: boolean
  details: RuntimePresentationDetail[]
}

export type RuntimePresentationInput = RuntimeEvent | RuntimeTraceObservation | RuntimeEventObservation

interface SourceEvent {
  eventId: string
  eventType: string
  sequence: number | null
  timestamp: string | null
  durationMs: number | null
  stepId: string | null
  attemptId: string | null
  payload: Record<string, unknown>
  observation: string | null
}

type MutablePresentation = RuntimeSemanticPresentation & { closed?: boolean }

const MAX_TITLE_LENGTH = 160
const MAX_SUMMARY_LENGTH = 320
const MAX_DETAIL_LENGTH = 1400
const MAX_DETAILS_TOTAL = 2600
const MAX_SAFE_VALUE_LENGTH = 900
const MAX_SERIALIZE_DEPTH = 4
const MAX_ARRAY_ITEMS = 12
const MAX_OBJECT_FIELDS = 24
const MAX_DETAILS = 12

const SECRET_TEXT_PATTERNS: Array<{ pattern: RegExp; replacement: string }> = [
  { pattern: /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/gi, replacement: '[redacted private key]' },
  { pattern: /\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+/gi, replacement: '[redacted authorization]' },
  { pattern: /((?:api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|token|auth(?:orization)?|client[_-]?secret|password|passwd|secret|private[_-]?key)\s*[:=]\s*["']?)[^\s"'&,;]+/gi, replacement: '$1[redacted]' },
  { pattern: /\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})\b/gi, replacement: '[redacted token]' },
  { pattern: /\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b/g, replacement: '[redacted token]' }
]

const MODEL_TYPES = new Set([
  'model_called',
  'model.started',
  'model.first_token',
  'model.activity',
  'model.output.delta',
  'model.completed',
  'planner.model.started',
  'planner.model.first_token',
  'planner.model.activity',
  'planner.model.output.delta',
  'planner.model.completed'
])

const COMPLETION_TYPES = new Set([
  'run.completed',
  'run.cancelled',
  'node.completed',
  'step.completed',
  'planner.completed',
  'execution.completed',
  'completion.completed'
])

const text = (value: unknown): string | null => {
  if (typeof value !== 'string') return null
  const normalized = value.trim()
  return normalized ? normalized : null
}

const number = (value: unknown): number | null => {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null
}

const record = (value: unknown): Record<string, unknown> => (
  value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
)

const normalizedFieldName = (field: string): string => field.replace(/[^a-z0-9]/gi, '').toLowerCase()

const isSensitiveField = (field: string): boolean => {
  const normalized = normalizedFieldName(field)
  if (!normalized) return false
  return /reason|thought|deliberation|analysis|prompt|credential|auth|cookie|password|passwd|secret|token|internal|key/.test(normalized)
}

const safeText = (value: unknown, maxLength = MAX_SAFE_VALUE_LENGTH): string => {
  if (typeof value !== 'string') return ''
  const inputLimit = Math.max(maxLength * 4, 4096)
  const wasTruncated = value.length > inputLimit
  let output = wasTruncated ? value.slice(0, inputLimit) : value
  for (const { pattern, replacement } of SECRET_TEXT_PATTERNS) {
    output = output.replace(pattern, replacement)
  }
  const normalized = output.trim()
  if (normalized.length > maxLength || wasTruncated) {
    return `${normalized.slice(0, Math.max(0, maxLength - 1))}…`
  }
  return normalized
}

const safeSerialize = (value: unknown, maxLength = MAX_SAFE_VALUE_LENGTH): string => {
  const limit = Math.max(0, maxLength)
  const seen = new WeakSet<object>()
  const bounded = (output: string, budget: number): string => {
    if (output.length <= budget) return output
    return budget > 0 ? `${output.slice(0, budget - 1)}…` : ''
  }

  const visit = (current: unknown, depth: number, budget: number): string => {
    if (budget <= 0) return ''
    if (depth > MAX_SERIALIZE_DEPTH) return bounded('[depth limit]', budget)
    if (current == null) return bounded(String(current), budget)
    if (typeof current === 'string') {
      const candidate = current.trim()
      if (depth < MAX_SERIALIZE_DEPTH && candidate.length <= 12000 && (candidate.startsWith('{') || candidate.startsWith('['))) {
        try {
          return visit(JSON.parse(candidate) as unknown, depth + 1, budget)
        } catch {
          // Partial or non-JSON text is still displayed only after redaction and truncation.
        }
      }
      return bounded(safeText(current, Math.min(budget, MAX_SAFE_VALUE_LENGTH)), budget)
    }
    if (typeof current === 'number' || typeof current === 'boolean') return bounded(String(current), budget)
    if (typeof current !== 'object') return bounded(`[${typeof current}]`, budget)
    if (depth >= MAX_SERIALIZE_DEPTH) return bounded('[depth limit]', budget)
    if (seen.has(current)) return bounded('[circular]', budget)
    seen.add(current)

    let output = ''
    if (Array.isArray(current)) {
      output = '['
      const count = Math.min(current.length, MAX_ARRAY_ITEMS)
      for (let index = 0; index < count; index += 1) {
        const prefix = index > 0 ? ', ' : ''
        const childBudget = budget - output.length - prefix.length - 2
        if (childBudget <= 0) break
        const child = visit(current[index], depth + 1, childBudget)
        if (!child) continue
        output += `${prefix}${child}`
      }
      if (current.length > count && output.length + 5 <= budget) output += `${output.length > 1 ? ', ' : ''}…`
      output += ']'
    } else {
      output = '{'
      let inspected = 0
      try {
        for (const field in current) {
          if (inspected >= MAX_OBJECT_FIELDS || output.length + 4 >= budget) break
          if (!Object.prototype.hasOwnProperty.call(current, field)) continue
          inspected += 1
          if (isSensitiveField(field)) continue
          const safeField = safeText(field, 72)
          const prefix = output.length > 1 ? ', ' : ''
          const entryBudget = budget - output.length - prefix.length - safeField.length - 4
          const safeValue = visit((current as Record<string, unknown>)[field], depth + 1, entryBudget)
          if (!safeField || !safeValue) continue
          const entry = `${prefix}${safeField}: ${safeValue}`
          if (output.length + entry.length + 1 > budget) break
          output += entry
        }
      } catch {
        const marker = output.length > 1 ? ', [unavailable]' : '[unavailable]'
        if (output.length + marker.length + 1 <= budget) output += marker
      }
      output += '}'
    }
    seen.delete(current)
    return bounded(output, budget)
  }

  return visit(value, 0, limit)
}

const safeDisplayText = (value: unknown, maxLength: number): string => {
  if (typeof value !== 'string') return ''
  const candidate = value.trim()
  if (candidate.length <= 12000 && (candidate.startsWith('{') || candidate.startsWith('['))) {
    try {
      return safeSerialize(JSON.parse(candidate) as unknown, maxLength)
    } catch {
      // Incomplete JSON is treated as text, then redacted and truncated.
    }
  }
  return safeText(value, maxLength)
}

const pickText = (payload: Record<string, unknown>, ...keys: string[]): string | null => {
  for (const key of keys) {
    const value = text(payload[key])
    if (value) return value
  }
  return null
}

const normalize = (event: RuntimePresentationInput): SourceEvent => {
  const isRuntimeEvent = 'sequence' in event
  const payload = 'payload' in event ? record(event.payload) : {}
  const stepId = 'stepId' in event ? text(event.stepId) : text(event.nodeId) || text(payload.stepId)
  return {
    eventId: event.eventId,
    eventType: event.eventType,
    sequence: isRuntimeEvent && typeof event.sequence === 'number' ? event.sequence : null,
    timestamp: text(event.timestamp),
    durationMs: 'durationMs' in event
      ? number(event.durationMs)
      : number(payload.durationMs),
    stepId,
    attemptId: isRuntimeEvent ? text(event.attemptId) : text(payload.attemptId),
    payload,
    observation: 'observation' in event
      ? text(event.observation)
      : 'summary' in event ? text(event.summary) : null
  }
}

const orderedEvents = (events: readonly RuntimePresentationInput[]): SourceEvent[] => events
  .map((event, index) => ({ event: normalize(event), index }))
  .sort((left, right) => {
    if (left.event.sequence != null && right.event.sequence != null && left.event.sequence !== right.event.sequence) {
      return left.event.sequence - right.event.sequence
    }
    return left.index - right.index
  })
  .map(item => item.event)

const normalizedType = (event: SourceEvent): string => event.eventType.trim().toLowerCase()

const isModelEvent = (event: SourceEvent): boolean => {
  const type = normalizedType(event)
  return MODEL_TYPES.has(type) || type.startsWith('model.') || type.startsWith('planner.model.')
}

const isToolEvent = (event: SourceEvent): boolean => {
  const type = normalizedType(event)
  return type === 'tool_called' || type.startsWith('tool.') || type.includes('tool_call')
}

const isCommandEvent = (event: SourceEvent): boolean => {
  const type = normalizedType(event)
  const kind = pickText(event.payload, 'kind', 'type')?.toLowerCase()
  return type.startsWith('command.')
    || type.startsWith('terminal.')
    || type.startsWith('shell.')
    || type.includes('command')
    || kind === 'command'
}

const isArtifactEvent = (event: SourceEvent): boolean => {
  const type = normalizedType(event)
  return type === 'data_produced'
    || type === 'data_consumed'
    || type === 'output.produced'
    || type === 'output.created'
    || type.startsWith('artifact.')
    || /(^|[._])artifact([._]|$)/.test(type)
}

const isErrorEvent = (event: SourceEvent): boolean => {
  const type = normalizedType(event)
  const status = pickText(event.payload, 'status', 'state', 'outcome')?.toLowerCase()
  return status === 'failed'
    || status === 'error'
    || type.includes('failed')
    || type.includes('error')
    || type.includes('violation')
    || type.includes('exception')
    || type.includes('timeout')
}

const isCompletionEvent = (event: SourceEvent): boolean => COMPLETION_TYPES.has(normalizedType(event))

const presentationKind = (event: SourceEvent): RuntimePresentationKind => {
  if (isModelEvent(event)) return 'model'
  if (isToolEvent(event)) return 'tool'
  if (isCommandEvent(event)) return 'command'
  if (isArtifactEvent(event)) return 'artifact'
  if (isErrorEvent(event)) return 'error'
  if (isCompletionEvent(event)) return 'completion'
  return 'generic'
}

const statusFrom = (event: SourceEvent, kind: RuntimePresentationKind): RuntimePresentationStatus => {
  const rawStatus = pickText(event.payload, 'status', 'state', 'outcome')?.toLowerCase()
  if (rawStatus === 'pending' || rawStatus === 'queued') return 'pending'
  if (rawStatus === 'running' || rawStatus === 'started' || rawStatus === 'in_progress') return 'running'
  if (rawStatus === 'failed' || rawStatus === 'error') return 'failed'
  if (rawStatus === 'cancelled' || rawStatus === 'canceled') return 'cancelled'
  if (['success', 'succeeded', 'completed', 'complete', 'produced', 'resolved'].includes(rawStatus || '')) return 'success'

  const type = normalizedType(event)
  if (type.includes('failed') || type.includes('error') || type.includes('violation') || type.includes('exception')) return 'failed'
  if (type.includes('cancel')) return 'cancelled'
  if (type.includes('start') || type.includes('activity') || type.includes('delta') || type.includes('progress') || type.includes('first_token')) return 'running'
  if (type.includes('completed') || type.includes('produced') || type.includes('resolved') || type.includes('compiled')) return 'success'
  if (kind === 'completion') return 'success'
  return 'unknown'
}

const statusMerge = (
  current: RuntimePresentationStatus,
  next: RuntimePresentationStatus
): RuntimePresentationStatus => {
  if (current === 'failed' || current === 'cancelled') return current
  if (next === 'failed' || next === 'cancelled') return next
  if (next === 'success') return 'success'
  if (current === 'success') return current
  if (next === 'running') return 'running'
  if (next === 'pending') return current === 'unknown' ? 'pending' : current
  return current === 'unknown' ? next : current
}

const modelName = (event: SourceEvent): string | null => pickText(
  event.payload,
  'model',
  'modelName',
  'deployment',
  'providerModel'
)

const eventSummary = (event: SourceEvent, kind: RuntimePresentationKind): string => {
  const direct = event.observation || pickText(event.payload, 'summary', 'message', 'description')
  if (direct) return direct

  if (kind === 'model') {
    return [modelName(event) || '模型响应', pickText(event.payload, 'stage', 'phase')].filter(Boolean).join(' · ')
  }
  if (kind === 'tool') {
    return [
      pickText(event.payload, 'tool', 'name', 'toolName') || '工具调用',
      pickText(event.payload, 'path', 'target', 'resource', 'query')
    ].filter(Boolean).join(' · ')
  }
  if (kind === 'command') return pickText(event.payload, 'command', 'cmd', 'shell') || '命令执行'
  if (kind === 'artifact') {
    return [
      pickText(event.payload, 'name', 'artifactName', 'artifactRef', 'outputRef') || '运行产物',
      pickText(event.payload, 'mediaType', 'artifactType')
    ].filter(Boolean).join(' · ')
  }
  if (kind === 'error') {
    return [pickText(event.payload, 'errorCode', 'code'), direct || '运行事件失败'].filter(Boolean).join(' · ')
  }
  if (kind === 'completion') return direct || '运行阶段已完成'
  return direct || event.eventType || '未识别 RuntimeEvent'
}

const titleFor = (event: SourceEvent, kind: RuntimePresentationKind): string => {
  if (kind === 'model') return modelName(event) ? `模型 · ${modelName(event)}` : '模型响应'
  if (kind === 'tool') return pickText(event.payload, 'tool', 'name', 'toolName') || '工具调用'
  if (kind === 'command') return '执行命令'
  if (kind === 'artifact') return pickText(event.payload, 'name', 'artifactName') || '产物'
  if (kind === 'error') return pickText(event.payload, 'errorCode', 'code') || '运行错误'
  if (kind === 'completion') return normalizedType(event) === 'run.cancelled' ? '运行已取消' : '运行完成'
  return event.eventType || '未识别事件'
}

const detailEntries = (event: SourceEvent, kind: RuntimePresentationKind): RuntimePresentationDetail[] => {
  const details: RuntimePresentationDetail[] = [
    { label: 'Event', value: safeText(event.eventType, 100), code: true },
    ...(event.stepId ? [{ label: 'Step', value: safeText(event.stepId, 120), code: true }] : [])
  ]
  const seen = new Set<string>()
  let total = details.reduce((sum, detail) => sum + detail.label.length + detail.value.length, 0)
  let hasRows = false
  if (kind === 'generic') {
    const detailRows = event.payload.details
    if (Array.isArray(detailRows)) {
      // Server-projected trace events: each whitelisted payload key arrives as a
      // bounded public detail row (key/value/kind); unknown keys, internal policy
      // and mistyped values never become rows.
      for (const row of detailRows) {
        if (details.length >= MAX_DETAILS || total >= MAX_DETAILS_TOTAL) break
        const entry = record(row)
        const key = text(entry.key)
        if (!key || seen.has(key) || isSensitiveField(key) || key === 'delta') continue
        const valueKind = typeof entry.kind === 'string' ? entry.kind : 'string'
        if (valueKind === 'null') continue
        const value = safeText(entry.value, Math.min(MAX_SAFE_VALUE_LENGTH, MAX_DETAILS_TOTAL - total - key.length - 4))
        if (!value) continue
        seen.add(key)
        hasRows = true
        details.push({ label: key, value, code: valueKind !== 'string' })
        total += key.length + value.length
      }
    } else {
      // Live SSE runtime events keep their raw payload display until Phase 4
      // projects their wire the same way (trace wire always carries details rows).
      const keys: string[] = []
      for (const key in event.payload) {
        if (keys.length >= MAX_OBJECT_FIELDS) break
        if (Object.prototype.hasOwnProperty.call(event.payload, key)) keys.push(key)
      }
      for (const key of keys) {
        if (details.length >= MAX_DETAILS || total >= MAX_DETAILS_TOTAL) break
        if (seen.has(key) || isSensitiveField(key) || event.payload[key] == null || key === 'delta') continue
        seen.add(key)
        hasRows = true
        const label = safeText(key, 72)
        const value = safeSerialize(event.payload[key], Math.min(MAX_SAFE_VALUE_LENGTH, MAX_DETAILS_TOTAL - total - label.length - 4))
        if (!label || !value) continue
        details.push({ label, value, code: typeof event.payload[key] !== 'string' })
        total += label.length + value.length
      }
    }
  } else {
    const keys = kind === 'model'
      ? ['model', 'provider', 'status', 'finishReason', 'latencyMs', 'receivedLength']
      : ['model', 'tool', 'name', 'command', 'path', 'artifactRef', 'outputRef', 'status', 'errorCode', 'message']
    for (const key of keys) {
      if (details.length >= MAX_DETAILS || total >= MAX_DETAILS_TOTAL) break
      if (seen.has(key) || isSensitiveField(key) || event.payload[key] == null || key === 'delta') continue
      seen.add(key)
      hasRows = true
      const label = safeText(key, 72)
      const value = safeSerialize(event.payload[key], Math.min(MAX_SAFE_VALUE_LENGTH, MAX_DETAILS_TOTAL - total - label.length - 4))
      if (!label || !value) continue
      details.push({ label, value, code: typeof event.payload[key] !== 'string' })
      total += label.length + value.length
    }
  }
  if (kind === 'generic' && !hasRows && event.observation) {
    details.push({ label: 'Summary', value: safeText(event.observation, 320) })
  }
  return details
}

const durationFrom = (event: SourceEvent): number | null => number(
  event.durationMs
  ?? event.payload.durationMs
  ?? event.payload.latencyMs
  ?? event.payload.elapsedMs
)

const basePresentation = (event: SourceEvent, kind: RuntimePresentationKind): MutablePresentation => ({
  id: `runtime:${event.eventId}`,
  kind,
  status: statusFrom(event, kind),
  title: titleFor(event, kind),
  summary: eventSummary(event, kind),
  detail: null,
  timestamp: event.timestamp,
  durationMs: durationFrom(event),
  stepId: event.stepId,
  semanticTaskKey: pickText(event.payload, 'semanticTaskKey', 'taskKey'),
  eventIds: [event.eventId],
  eventTypes: [event.eventType],
  metrics: { events: 1 },
  expandable: true,
  details: detailEntries(event, kind)
})

const appendEvent = (item: MutablePresentation, event: SourceEvent, kind: RuntimePresentationKind): void => {
  if (!item.eventIds.includes(event.eventId)) item.eventIds.push(event.eventId)
  if (!item.eventTypes.includes(event.eventType)) item.eventTypes.push(event.eventType)
  item.status = statusMerge(item.status, statusFrom(event, kind))
  item.durationMs = durationFrom(event) ?? item.durationMs
  item.timestamp ||= event.timestamp
  item.stepId ||= event.stepId
  item.semanticTaskKey ||= pickText(event.payload, 'semanticTaskKey', 'taskKey')
  item.metrics.events = item.eventIds.length
}

const groupValue = (event: SourceEvent, ...keys: string[]): string | null => (
  pickText(event.payload, ...keys)
  || pickText(event.payload, 'executionId', 'execution_id')
  || null
)

const modelIdentity = (event: SourceEvent): string | null => (
  pickText(event.payload, 'callKey', 'modelCallId', 'callId')
  || event.attemptId
  || pickText(event.payload, 'attemptId', 'executionId', 'execution_id', 'requestId')
  || null
)

const lifecycleStarts = (event: SourceEvent): boolean => {
  const type = normalizedType(event)
  return type.endsWith('.started') || type.endsWith('.called') || type.endsWith('.requested') || type.endsWith('.queued')
}

const lifecycleTerminal = (event: SourceEvent): boolean => {
  const status = statusFrom(event, 'generic')
  return ['success', 'failed', 'cancelled'].includes(status)
    || /\.(completed|failed|cancelled|canceled|succeeded)$/.test(normalizedType(event))
}

const updateModel = (item: MutablePresentation, event: SourceEvent): void => {
  appendEvent(item, event, 'model')
  const delta = typeof event.payload.delta === 'string' ? event.payload.delta : null
  if (delta != null) {
    item.metrics.chunks = Number(item.metrics.chunks || 0) + 1
  } else if (item.detail == null && event.payload.data != null) {
    item.detail = safeSerialize(event.payload.data, MAX_DETAIL_LENGTH)
  }
  const ttft = number(event.payload.ttftMs ?? event.payload.timeToFirstTokenMs)
  if (ttft != null) item.metrics.ttftMs = ttft
  const name = modelName(event)
  if (name) item.title = `模型 · ${name}`
  const chunks = item.metrics.chunks ? ` · ${item.metrics.chunks} 个片段` : ''
  item.summary = `${name || '模型响应'}${chunks}`
  item.details = [
    { label: 'Events', value: item.eventTypes.join(' · '), code: true },
    ...(item.metrics.ttftMs != null ? [{ label: 'TTFT', value: `${item.metrics.ttftMs} ms` }] : []),
    ...(item.detail ? [{ label: 'Output', value: item.detail }] : [])
  ]
}

const updateGrouped = (item: MutablePresentation, event: SourceEvent, kind: 'tool' | 'command'): void => {
  appendEvent(item, event, kind)
  item.title = titleFor(event, kind)
  item.summary = eventSummary(event, kind)
  item.details = detailEntries(event, kind)
  item.details.unshift({ label: 'Events', value: item.eventTypes.join(' · '), code: true })
}

const finalize = (item: MutablePresentation): RuntimeSemanticPresentation => {
  const { closed: _closed, ...presentation } = item
  presentation.id = `runtime:${safeText(presentation.id.slice('runtime:'.length), 160)}`
  presentation.title = safeDisplayText(presentation.title, MAX_TITLE_LENGTH)
  presentation.summary = safeDisplayText(presentation.summary, MAX_SUMMARY_LENGTH)
  presentation.detail = presentation.detail == null ? null : safeDisplayText(presentation.detail, MAX_DETAIL_LENGTH)
  presentation.timestamp = presentation.timestamp == null ? null : safeText(presentation.timestamp, 80)
  presentation.stepId = presentation.stepId == null ? null : safeDisplayText(presentation.stepId, 120)
  presentation.semanticTaskKey = presentation.semanticTaskKey == null
    ? null
    : safeDisplayText(presentation.semanticTaskKey, 160)
  presentation.eventIds = presentation.eventIds.slice(0, 64).map(eventId => safeText(eventId, 160))
  presentation.eventTypes = presentation.eventTypes.slice(0, 32).map(eventType => safeText(eventType, 100))
  let detailBudget = MAX_DETAILS_TOTAL
  presentation.details = presentation.details.slice(0, MAX_DETAILS).flatMap(detail => {
    if (detailBudget <= 0) return []
    const label = safeText(detail.label, 72)
    const value = safeDisplayText(detail.value, Math.min(MAX_SAFE_VALUE_LENGTH, detailBudget - label.length - 4))
    if (!label || !value) return []
    detailBudget -= label.length + value.length
    return [{ label, value, ...(detail.code ? { code: true } : {}) }]
  })
  presentation.expandable = presentation.details.length > 0
  return presentation
}

export const projectRuntimePresentations = (
  events: readonly RuntimePresentationInput[]
): RuntimeSemanticPresentation[] => {
  const output: MutablePresentation[] = []
  const modelGroups = new Map<string, MutablePresentation>()
  const toolGroups = new Map<string, MutablePresentation>()
  const commandGroups = new Map<string, MutablePresentation>()
  const activeUnidentifiedModels = new Map<string, MutablePresentation>()
  const ambiguousUnidentifiedModelSteps = new Set<string>()

  for (const event of orderedEvents(events)) {
    const kind = presentationKind(event)
    if (kind === 'model') {
      const stepKey = event.stepId || 'run'
      const identity = modelIdentity(event)
      let item: MutablePresentation | undefined
      let created = false
      if (identity) {
        const key = `${stepKey}:${identity}`
        item = modelGroups.get(key)
        if (!item || lifecycleStarts(event)) {
          item = basePresentation(event, kind)
          output.push(item)
          modelGroups.set(key, item)
          created = true
        } else {
          updateModel(item, event)
        }
      } else {
        const active = activeUnidentifiedModels.get(stepKey)
        const starts = lifecycleStarts(event)
        if (starts && active && !active.closed) {
          active.closed = true
          activeUnidentifiedModels.delete(stepKey)
          ambiguousUnidentifiedModelSteps.add(stepKey)
        }

        if (ambiguousUnidentifiedModelSteps.has(stepKey)) {
          item = basePresentation(event, kind)
          output.push(item)
          item.closed = lifecycleTerminal(event)
          created = true
        } else if (starts) {
          item = basePresentation(event, kind)
          output.push(item)
          activeUnidentifiedModels.set(stepKey, item)
          created = true
        } else if (active && !active.closed) {
          item = active
          updateModel(item, event)
        } else {
          item = basePresentation(event, kind)
          output.push(item)
          created = true
        }
      }
      if (item && created) updateModel(item, event)
      if (item && lifecycleTerminal(event)) {
        item.closed = true
        if (!identity && activeUnidentifiedModels.get(stepKey) === item) activeUnidentifiedModels.delete(stepKey)
      }
      continue
    }

    if (kind === 'tool' || kind === 'command') {
      const groups = kind === 'tool' ? toolGroups : commandGroups
      const keyValue = kind === 'tool'
        ? groupValue(event, 'toolCallId', 'callId')
        : groupValue(event, 'commandId', 'commandKey', 'callId')
      const key = `${event.stepId || 'run'}:${keyValue || event.eventId}`
      let item = groups.get(key)
      if (!item || lifecycleStarts(event)) {
        item = basePresentation(event, kind)
        output.push(item)
        groups.set(key, item)
      } else {
        updateGrouped(item, event, kind)
      }
      if (item.eventIds.length === 1) updateGrouped(item, event, kind)
      if (lifecycleTerminal(event)) item.closed = true
      continue
    }

    output.push(basePresentation(event, kind))
  }

  return output.map(finalize)
}

export const projectRuntimeObservation = (
  observation: Pick<RuntimeObservation, 'traces' | 'events'> | null | undefined
): RuntimeSemanticPresentation[] => {
  if (!observation) return []
  return projectRuntimePresentations(observation.traces.length ? observation.traces : observation.events)
}
