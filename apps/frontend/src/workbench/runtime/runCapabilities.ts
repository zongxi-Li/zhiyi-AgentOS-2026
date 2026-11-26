import type { RunActionCapabilities, WorkflowRun } from '@/services/api/agentos'

export const runCapabilityActions = ['canInspect', 'canDiscuss', 'canCancel', 'canReview', 'canExecuteFormalAction',
  'canResolveToolApproval', 'canAnswerPlanner', 'canCollaborate', 'canSetPermission', 'canRetrySuccessor', 'canRecoverCurrentRun', 'canRerunSuccessor',
  'canDecideRevision', 'canApplyRevision', 'canDelete'] as const
export type RunCapabilityAction = typeof runCapabilityActions[number]
export const recoveryCheckPending = (value: RunActionCapabilities | null | undefined) =>
  value?.unavailableReasons.some(({ action, code }) => code === 'RECOVERY_CHECK_PENDING'
    && (action === 'canRecoverCurrentRun' || action === 'canRetrySuccessor')) === true
const active = new Set(['pending', 'planning', 'running', 'retrying', 'waiting_review'])
const terminal = new Set(['completed', 'failed', 'cancelled', 'superseded'])

/** Validate scope and comparison revision; selected/latest never grant offers. */
export function readRunCapabilities(value: RunActionCapabilities | null | undefined, missionId: string,
  runId: string | null, revision?: number, status?: string): RunActionCapabilities | null {
  if (value && value.canSetPermission == null) value = { ...value, canSetPermission: value.canCollaborate }
  // Earlier schema-v1 projections omit the additive current-run recovery fields.
  // Missing recovery metadata must not revoke unrelated explicit offers, and it
  // cannot authorize either recovery path without the matching mode and target.
  if (value?.canRetrySuccessor === false && value.canRecoverCurrentRun !== true
    && (value.canRecoverCurrentRun === undefined || value.retryMode === undefined)) {
    value = { ...value,
      canRecoverCurrentRun: value.canRecoverCurrentRun === undefined ? false : value.canRecoverCurrentRun,
      retryMode: value.retryMode === undefined ? null : value.retryMode }
  }
  if (!value || value.schemaVersion !== 1 || value.missionId !== missionId || value.runId !== runId
    || !Number.isInteger(value.runtimeRevision) || value.runtimeRevision < 0
    || (revision !== undefined && revision !== value.runtimeRevision) || (status !== undefined && status !== value.status)
    || !runCapabilityActions.every(action => typeof value[action] === 'boolean')
    || !active.has(value.status) && !terminal.has(value.status)
    || value.isExecutionActive !== active.has(value.status)
    || typeof value.isSuperseded !== 'boolean' || !value.lineage || typeof value.lineage !== 'object' || Array.isArray(value.lineage)
    || ((value.status === 'superseded' || value.lineage.supersededByRunId) && !value.isSuperseded)
    || !Array.isArray(value.formalActions) || !value.formalActions.every(action =>
      ['materialize', 'activate', 'handoff', 'permit', 'dispatch'].includes(action))
    || !Array.isArray(value.unavailableReasons) || !value.unavailableReasons.every(reason => reason
      && typeof reason.action === 'string' && typeof reason.code === 'string')) return null
  if (value.isSuperseded && runCapabilityActions.some(action => !['canInspect', 'canDiscuss', 'canDelete'].includes(action) && value[action])) return null
  if (value.canCancel && !value.isExecutionActive || value.canReview && value.status !== 'waiting_review'
    || value.canExecuteFormalAction && !['pending', 'planning'].includes(value.status)
    || value.canExecuteFormalAction !== (value.formalActions.length > 0)
    || value.canResolveToolApproval && value.status !== 'running'
    || value.canAnswerPlanner && value.status !== 'waiting_review'
    || value.canRetrySuccessor && (value.status !== 'failed' || !value.retryStepId || value.retryMode !== 'successor_run')
    || value.canRecoverCurrentRun && (!['failed', 'waiting_review'].includes(value.status) || !value.retryStepId || value.retryMode !== 'current_run')
    || !value.canRetrySuccessor && !value.canRecoverCurrentRun && (value.retryMode !== null || value.retryStepId !== null)
    || value.canDecideRevision && !value.isExecutionActive || value.canApplyRevision && value.status !== 'cancelled'
    || value.canDelete && !terminal.has(value.status)) return null
  return value
}

export const runCapabilities = (run: WorkflowRun | null | undefined) => run && Number.isInteger(run.runtimeRevision)
  ? readRunCapabilities(run.actionCapabilities, run.missionId, run.runId, run.runtimeRevision, run.status) : null
