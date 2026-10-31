import type { AsyncWorkflowStartRequest } from '@/services/api/workflow'
import { cloneLaunchValue } from './command'

declare const preparedBrand: unique symbol
export interface PreparedMissionLaunch { readonly [preparedBrand]: true }
const admitted = new WeakMap<object, { operationId: string; request: AsyncWorkflowStartRequest }>()
// Internal capability: architecture tests restrict this import to LaunchAttempt.
export function prepareMissionLaunch(operationId: string, request: AsyncWorkflowStartRequest): PreparedMissionLaunch {
  if (!operationId.trim() || operationId !== request.clientRequestId) throw new Error('Launch operation identity does not match the wire request')
  const token = {} as PreparedMissionLaunch
  admitted.set(token, { operationId, request: cloneLaunchValue(request) })
  return token
}
export function readPreparedMissionLaunch(token: PreparedMissionLaunch) {
  const prepared = token && admitted.get(token)
  if (!prepared) throw new Error('Mission launch requires a prepared LaunchAttemptIdentity')
  return { ...prepared, request: cloneLaunchValue(prepared.request) }
}
