import { localFetch } from '@/platform/api'
import { agentosRequest } from '../client'
import { runPath } from '../paths'
import { apiUrl } from '@/platform'
import { readSseFrames } from '@/utils/sse'
import type { ResponseTimings } from '../../../../../../backend/src/shared/chat-stream/index.mjs'
import type { WorkspaceReviewProjection } from '../types/graph'

export type CopilotProgressPhase = 'preparing' | 'waiting_model' | 'receiving' | 'retrying' | 'validating'
export interface CopilotStreamEvent {
  type: 'content' | 'progress' | 'activity' | 'heartbeat' | 'completed' | 'error'
  content?: string; message?: string; exchange?: CopilotExchange
  phase?: CopilotProgressPhase; elapsedMs?: number; responseTimings?: ResponseTimings
  attemptId?: string; requestId?: string; providerRequest?: number
}
export interface CopilotMessageOptions { modelId?: string; permission: CopilotPermission; reasoningEffort?: string }

export interface CopilotExchange {
  sourceRunId?: string
  operationId: string; user: string; assistant: string; createdAt: string; observedRevision: number
  modelId?: string | null; permission?: CopilotPermission
  reasoningEffort?: string | null
  responseTimings?: ResponseTimings; latencyMs?: number; providerRequest?: number
  contextUsage?: import('../types/acg').ModelContextUsage
  action?: CopilotAction
  receipt?: { proposalId: string; runId: string; kind: CopilotActionKind; status: string; executeStepIds: string[]; reusedStepIds: string[] }
}
export type CopilotActionKind = 'rerun' | 'rerun_node' | 'recover' | 'user_input'
export interface CopilotAction { kind: CopilotActionKind; stepId: string | null; expectedRevision: number; executeStepIds: string[]; reusedStepIds: string[]; content: string; retryMode?: 'current_run' | 'successor_run'; planningMode?: 'fresh'; capabilityCatalogRevision?: string; executionEnvironmentChanged?: boolean }
export type CopilotPermission = 'read_only' | 'task_collaboration'
export type TaskApprovalMode = 'ask' | 'full'
export interface TaskOperatorPolicy {
  missionId: string; permission: CopilotPermission; approvalMode: TaskApprovalMode; policyRevision: number
  workspaceScope?: { workspaceId: string; grantId: string; resourceId?: string | null } | null
  updatedBy?: { userId: string; tenantId?: string | null } | null
  effectiveApprovalMode?: TaskApprovalMode; effectiveScopeMatch?: boolean
  operationId?: string | null; updatedAt?: string | null
}
export interface CopilotPermissionChange {
  approvalMode: TaskApprovalMode; expectedPolicyRevision: number; operationId: string
}
export interface CopilotPermissionReceipt {
  missionId: string; taskPermission: CopilotPermission; approvalMode: TaskApprovalMode; policyRevision: number
  approvalPolicy?: TaskOperatorPolicy | null; autoApprovedCount: number
}
export interface ToolApprovalDecision {
  source: 'policy' | 'user'; decidedAt: string; policyRevision?: number
  actor?: { userId: string; tenantId?: string | null } | null
}
export interface CopilotInitialPlan {
  planVersion: number; commitId: string | null; commitmentRevision: number | null
  objective: string; constraints: string[]; expectedArtifacts: string[]
  relations?: { sourceKey: string; targetKey: string; relationType: 'depends_on' | 'parent' }[]
  tasks: { key: string; title: string; objective: string; rationale: string; acceptanceCriteria: string[]; sourceRefs: string[]; capabilities?: string[] }[]
}
export interface CopilotToolActivity {
  target?: string; resultPreview?: string
  executionId: string; tool: string; status: string; stepId: string
  createdAt: string; attemptId?: string; receiptRef?: string
  approvalDecision?: ToolApprovalDecision | null
}
export interface CopilotReview {
  subjectId: string; subjectType: string; reason: string; reasonCode: string
  kind?: 'workspace_revision_pending' | 'workspace_revision_blocked' | 'planner_wait' | 'planner_error' | 'planner_rejected' | 'step_review'
  displayReason?: string; errorCode?: string; errorType?: string
  validationFailures?: { stage: string; code: string; fieldPath: Array<string | number>; callKey?: string }[]
  canApprove: boolean; decisionRejected: boolean; expectedRunUpdatedAt: string
}
export interface CopilotPlanningProgress {
  kind: 'repairing' | 'blocked'; status: string; message: string; observationId: string; errorCode: string
  reason?: string; errorType?: string; canApprove?: boolean
}
export interface CopilotState {
  missionId?: string; latestRunId?: string; taskPermission?: CopilotPermission
  approvalMode?: TaskApprovalMode; policyRevision?: number; approvalPolicy?: TaskOperatorPolicy | null
  runId: string; status: string; revision: number; modelAvailable: boolean
  models?: { id: string; provider: string; model: string; reasoningEfforts?: string[]; defaultReasoningEffort?: string | null }[]
  defaultModelId?: string | null; permissions?: CopilotPermission[]
  question: { questionId: string; prompt: string; choices: string[] } | null
  humanAnswers: { questionId: string; sourceRunId: string; prompt: string; answer: string; answeredAt: string }[]
  exchanges: CopilotExchange[]
  decision: { action: string; reason: string } | null
  review?: CopilotReview | null
  planningProgress?: CopilotPlanningProgress | null
  initialPlan?: CopilotInitialPlan | null
  toolActivity?: CopilotToolActivity[]
  workspaceReview?: WorkspaceReviewProjection | null
  steps: { stepId: string; name: string; status: string }[]
}
export const createCopilotApi = () => ({
  async setCopilotPermission(runId: string, permission: CopilotPermission, change?: CopilotPermissionChange): Promise<CopilotPermissionReceipt> {
    return (await agentosRequest.post(`${runPath(runId)}/copilot/permission`, { permission, ...change })).data
  },
  async previewCopilotAction(runId: string, kind: CopilotActionKind, content: string, operationId: string, permission: CopilotPermission, stepId?: string): Promise<CopilotExchange> {
    return (await agentosRequest.post(`${runPath(runId)}/copilot/actions/preview`, { kind, content, operationId, permission, ...(stepId ? { stepId } : {}) })).data
  },
  async applyCopilotAction(runId: string, proposalId: string, expectedRevision: number, permission: CopilotPermission): Promise<CopilotExchange> {
    return (await agentosRequest.post(`${runPath(runId)}/copilot/actions`, { proposalId, expectedRevision, permission })).data
  },
  async getCopilot(runId: string, signal?: AbortSignal): Promise<CopilotState> {
    return (await agentosRequest.get(`${runPath(runId)}/copilot`, { signal })).data
  },
  async streamCopilotMessage(runId: string, content: string, operationId: string, onEvent: (event: CopilotStreamEvent) => void, signal?: AbortSignal, options?: CopilotMessageOptions): Promise<CopilotExchange> {

    const response = await localFetch(apiUrl(`/api/agentos/v2${runPath(runId)}/copilot/messages/stream`), {
      method: 'POST', signal, headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ content, operationId, ...options })
    })
    if (!response.ok) {
      const error = Object.assign(new Error(`对话连接失败（${response.status}）`), { response: { status: response.status } })
      throw error
    }
    if (!response.body) throw new Error('服务未返回流式响应')
    for await (const { data } of readSseFrames(response.body, { signal, flushAtEof: true })) {
      if (!data) continue
      const event = JSON.parse(data) as CopilotStreamEvent & { event?: string }
      if (event.type === 'error' || event.event === 'error') throw new Error(event.message || '对话流中断，请重试')
      onEvent(event)
      if (event.type === 'completed' && event.exchange) return event.exchange
    }
    throw new Error('对话流提前结束，回复尚未保存，请重试')
  },
  async sendCopilotMessage(runId: string, content: string, operationId: string, signal?: AbortSignal, options?: CopilotMessageOptions): Promise<CopilotExchange> {
    return (await agentosRequest.post(`${runPath(runId)}/copilot/messages`, { content, operationId, ...options }, { signal })).data
  },
  async answerPlanner(runId: string, questionId: string, answer: string, expectedRevision: number, operationId: string, permission?: CopilotPermission): Promise<CopilotState> {
    return (await agentosRequest.post(`${runPath(runId)}/copilot/answers`, { questionId, answer, expectedRevision, operationId, ...(permission ? { permission } : {}) })).data
  }
})
