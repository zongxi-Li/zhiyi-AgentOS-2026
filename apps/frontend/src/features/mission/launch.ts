import { workflowApi, type AsyncWorkflowStartRequest, type WorkflowRun } from '@/services/api/workflow'
import { WorkflowApiContractError } from '@/services/api/agentos'

// AsyncWorkflowStartRequest remains the only API wire contract.
export interface MissionLaunchOptions { signal?: AbortSignal }
export interface MissionLaunchResult {
  missionId: string
  runId: string
  run: WorkflowRun
  clientRequestId: string
}

export async function launchMission(
  request: AsyncWorkflowStartRequest,
  options?: MissionLaunchOptions
): Promise<MissionLaunchResult> {
  const run = options
    ? await workflowApi.startWorkflowAsync(request, options)
    : await workflowApi.startWorkflowAsync(request)
  if (typeof run?.missionId !== 'string' || !run.missionId.trim()
    || typeof run?.runId !== 'string' || !run.runId.trim()) {
    throw new WorkflowApiContractError('运行创建响应缺少 runId 或 missionId')
  }
  return { missionId: run.missionId, runId: run.runId, run, clientRequestId: request.clientRequestId }
}
