import type { AcgStepState } from '@/services/api/agentos'

export const normalizeNodeStatus = (value?: string) => {
  const status = String(value || '').toLowerCase()
  return ['model_starting', 'streaming', 'finalizing'].includes(status) ? 'running'
    : status === 'waiting' ? 'pending' : status
}

const SETTLED_NODE_STATUSES = new Set(['completed', 'committed', 'skipped_by_condition', 'cancelled'])
const ACTIVE_NODE_STATUSES = new Set(['running', 'retrying', 'waiting_review'])

/** Unversioned stream phases add activity; persisted facts own the execution outcome. */
export const resolveNodeStatus = (step?: Pick<AcgStepState, 'status'>, runtimePhase?: string, completed = false) => {
  const durable = normalizeNodeStatus(step?.status)
  const live = normalizeNodeStatus(runtimePhase)
  if (SETTLED_NODE_STATUSES.has(durable)) return durable
  if (completed) return 'completed'
  if (ACTIVE_NODE_STATUSES.has(durable) || durable === 'failed') return durable
  if (durable && (SETTLED_NODE_STATUSES.has(live) || live === 'failed')) return durable
  return live || durable || 'pending'
}

export const mapNodeVisualState = (step?: AcgStepState) => ({
  status: step?.status || 'pending',
  runtimeAdded: (step?.createdGraphVersion ?? 1) > 1,
  bindingSwitched: (step?.bindingHistory?.length ?? 0) > 1,
  conditionalSkipped: step?.status === 'skipped_by_condition',
  targetRetried: (step?.attempt ?? 0) > 1
})

export const mapEdgeVisualState = (activation?: string) => {
  const normalized = String(activation || 'active').toLowerCase()
  return ['inactive', 'terminated', 'superseded'].includes(normalized) ? normalized : 'active'
}
