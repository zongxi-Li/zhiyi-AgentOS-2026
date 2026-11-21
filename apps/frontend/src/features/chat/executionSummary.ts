/** Reconcile live tool events and legacy snapshots by their actual operation identity. */
export interface ApprovalSummaryLike {
  approvalId?: string
  sessionId?: string
  toolCallId?: string
  invocationId?: string
  toolName?: string
  status?: string
}

export interface ExecutionSummaryLike {
  stage: string
  status: string
  description: string
  durationMs?: number
  approval?: ApprovalSummaryLike
  terminal?: object
  activity?: object
}

const terminalExecutions = new Set(['completed', 'failed', 'cancelled'])
const terminalApprovals = new Set(['approved', 'denied', 'expired'])
const usable = (value: unknown): value is string => typeof value === 'string'
  && value.trim().length > 0 && !['unknown', 'undefined', 'null'].includes(value)

/** Empty/fallback stages have no identity and must never coalesce unrelated work. */
function operation(item: ExecutionSummaryLike) {
  const match = /^tool:([^:]+):(.+)$/.exec(item.stage)
  const tool = usable(item.approval?.toolName) ? item.approval.toolName : match?.[1]
  const call = usable(item.approval?.toolCallId) ? item.approval.toolCallId
    : usable(item.approval?.invocationId) ? item.approval.invocationId : match?.[2]
  return usable(tool) && usable(call) && tool !== call ? { tool, call, stage: `tool:${tool}:${call}` } : null
}

function approvalIdentity(item: ExecutionSummaryLike) {
  const approval = item.approval
  return usable(approval?.approvalId)
    ? JSON.stringify([approval.sessionId || '', approval.approvalId]) : null
}

function defined<T extends object>(before: T | undefined, after: T | undefined): T | undefined {
  if (!before && !after) return undefined
  return Object.assign({}, before, Object.fromEntries(Object.entries(after || {}).filter(([, value]) => value !== undefined))) as T
}

function merge<T extends ExecutionSummaryLike>(before: T, after: T): T {
  const priorApproval = before.approval
  const nextApproval = after.approval
  const regression = terminalApprovals.has(priorApproval?.status || '') && nextApproval?.status === 'pending'
  const approval = defined(priorApproval, nextApproval)
  if (approval && regression) approval.status = priorApproval!.status
  // Stream interruption may infer expiry before a delayed resolved event arrives.
  // A confirmed allow/deny remains more specific than that inferred expiry.
  if (approval && ['approved', 'denied'].includes(priorApproval?.status || '') && nextApproval?.status === 'expired') {
    approval.status = priorApproval!.status
  }
  const preserveExecution = terminalExecutions.has(before.status) && !terminalExecutions.has(after.status)
  const preserveStatus = preserveExecution || regression
  return {
    ...defined(before, after),
    stage: operation(after)?.stage || operation(before)?.stage || before.stage,
    ...(preserveStatus ? { status: before.status, description: before.description } : {}),
    ...(approval ? { approval } : {}),
    ...(before.terminal || after.terminal ? { terminal: defined(before.terminal, after.terminal) } : {}),
    ...(before.activity || after.activity ? { activity: defined(before.activity, after.activity) } : {})
  } as T
}

/**
 * Merge persisted duplicate approval events, retaining completed execution data.
 * An unscoped tool event can join an approval only when that call identifies one
 * approval in the supplied batch; reused call IDs across sessions remain separate.
 */
export function normalizeExecutionSummary<T extends ExecutionSummaryLike>(items: readonly T[] | null | undefined): T[] {
  if (!items?.length) return []
  const approvalsByCall = new Map<string, Set<string>>()
  for (const item of items) {
    const call = operation(item)?.stage
    const approval = approvalIdentity(item)
    if (call && approval) {
      if (!approvalsByCall.has(call)) approvalsByCall.set(call, new Set())
      approvalsByCall.get(call)!.add(approval)
    }
  }
  const positions = new Map<string, number>()
  const normalized: T[] = []
  for (const item of items) {
    const call = operation(item)
    const approval = approvalIdentity(item)
    const owners = call ? approvalsByCall.get(call.stage) : undefined
    const key = approval ? `approval:${approval}`
      : owners?.size === 1 ? `approval:${[...owners][0]}`
        : call ? `call:${call.stage}` : null
    const index = key === null ? undefined : positions.get(key)
    if (index !== undefined) normalized[index] = merge(normalized[index], item)
    else {
      if (key !== null) positions.set(key, normalized.length)
      normalized.push({
        ...item,
        ...(call ? { stage: call.stage } : {}),
        ...(item.approval ? { approval: { ...item.approval } } : {}),
        ...(item.terminal ? { terminal: { ...item.terminal } } : {}),
        ...(item.activity ? { activity: { ...item.activity } } : {})
      })
    }
  }
  return normalized
}

export function mergeExecutionSummary<T extends ExecutionSummaryLike>(items: readonly T[] | null | undefined, incoming: T): T[] {
  return normalizeExecutionSummary([...(items || []), incoming])
}
