import type { SingleStepRetryRequest, WorkflowRerunRequest, WorkflowRun } from '@/services/api/agentos'
import { canonicalLaunchJson } from '@/features/mission/command'

type RecoveryCommand = { kind: 'retry'; stepId: string; payload: SingleStepRetryRequest }
  | { kind: 'rerun'; payload: WorkflowRerunRequest }
export type RecoveryIdentity = RecoveryCommand & { missionId: string; sourceRunId: string; fingerprint: string }
export class RecoveryResponseError extends Error {}

export async function confirmCurrentRunRecovery(
  identity: RecoveryIdentity,
  admitted: WorkflowRun,
  readRun: (runId: string) => Promise<WorkflowRun>
): Promise<WorkflowRun> {
  const mismatch = () => new RecoveryResponseError('当前 Run 恢复响应身份或版本不匹配，保留原操作等待核对')
  if (identity.kind !== 'retry' || identity.payload.mode !== 'current_run') throw mismatch()
  const expected = identity.payload.expectedRuntimeRevision
  const assertSnapshot = (run: WorkflowRun, minimum: number) => {
    const revision = run.runtimeRevision
    if (run.missionId !== identity.missionId || run.runId !== identity.sourceRunId
      || typeof revision !== 'number' || !Number.isInteger(revision) || revision < minimum) throw mismatch()
    return revision
  }
  if (typeof expected !== 'number' || !Number.isInteger(expected) || expected < 0) throw mismatch()
  // The response belongs to this exact POST. A later GET cannot repair an
  // invalid response identity or an older execution snapshot.
  const admittedRevision = assertSnapshot(admitted, expected)
  if (admittedRevision > expected) return admitted

  // Admission saves RETRYING before the async executor advances its revision.
  // Read the same Run to confirm its projection, keeping the POST identity as
  // the idempotency correlation; this GET is not an operation receipt.
  const current = await readRun(identity.sourceRunId)
  const currentRevision = assertSnapshot(current, admittedRevision)
  const target = current.steps?.find(step => step.stepId === identity.stepId)
  const resumed = target && ['pending', 'retrying', 'running', 'waiting_review', 'completed',
    'skipped_by_condition'].includes(target.status)
  // A fast new failure/cancellation is an execution result after admission.
  // Confirm it so the old pending command does not hide the next recovery.
  const endedAfterAdmission = target && currentRevision > admittedRevision
    && ['failed', 'cancelled'].includes(target.status)
  if (!resumed && !endedAfterAdmission) {
    throw new RecoveryResponseError('恢复请求已接受，执行状态尚未确认，保留原操作等待核对')
  }
  return current
}

const keyFor = (missionId: string, sourceRunId: string) => {
  if (!localStorage.getItem('userId')) throw new Error('本机身份尚未就绪，禁止恢复操作')
  return `workbench.recovery.v1:${encodeURIComponent(JSON.stringify([localStorage.getItem('tenantId'), localStorage.getItem('userId'), missionId, sourceRunId]))}`
}
const fingerprint = (value: Omit<RecoveryIdentity, 'fingerprint'>) => canonicalLaunchJson(value)
function assertCommand(value: RecoveryIdentity, missionId: string, sourceRunId: string) {
  const { fingerprint: saved, ...command } = value
  if (value.missionId !== missionId || value.sourceRunId !== sourceRunId || !value.payload?.clientRequestId
    || saved !== fingerprint(command) || (value.kind !== 'retry' && value.kind !== 'rerun')
    || (value.kind === 'retry' && (!value.stepId || !['successor_run', 'current_run'].includes(value.payload.mode || '')))
    || (value.kind === 'rerun' && value.payload.sourceRunId !== sourceRunId)) throw new Error('恢复快照身份损坏，禁止生成新身份重试')
}
export function pendingRunRecovery(missionId: string, sourceRunId: string, storage: Storage): RecoveryIdentity | null {
  const raw = storage.getItem(keyFor(missionId, sourceRunId))
  if (!raw) return null
  const value = JSON.parse(raw) as RecoveryIdentity
  assertCommand(value, missionId, sourceRunId)
  return value
}
export function beginRunRecovery(missionId: string, sourceRunId: string, command: RecoveryCommand, storage: Storage): RecoveryIdentity {
  const next = { ...command, missionId, sourceRunId }
  const identity = { ...next, fingerprint: fingerprint(next) } as RecoveryIdentity
  assertCommand(identity, missionId, sourceRunId)
  const saved = pendingRunRecovery(missionId, sourceRunId, storage)
  if (saved && saved.fingerprint !== identity.fingerprint) throw new Error('原恢复结果未确认，必须重试原操作')
  storage.setItem(keyFor(missionId, sourceRunId), JSON.stringify(saved || identity))
  return saved || identity
}
export function completeRunRecovery(identity: RecoveryIdentity, storage: Storage) {
  const saved = pendingRunRecovery(identity.missionId, identity.sourceRunId, storage)
  if (saved?.fingerprint === identity.fingerprint) storage.removeItem(keyFor(identity.missionId, identity.sourceRunId))
}
