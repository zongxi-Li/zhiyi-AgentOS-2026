import type { AsyncWorkflowStartRequest } from '@/services/api/workflow'
import { buildWorkbenchStartRequest, createNativeWorkbenchDraft, type PluginUiExtension, type WorkbenchDraft } from '@/features/acg/workbench'

export interface LaunchMaterials {
  attachmentIds?: string[]
  materialRefs?: string[]
  sourceRefs?: string[]
}

export function buildWorkbenchLaunchRequest(
  draft: WorkbenchDraft,
  extensions: PluginUiExtension[],
  clientRequestId: string,
  context: LaunchMaterials & { input?: Record<string, unknown> } = {}
): AsyncWorkflowStartRequest {
  const request = buildWorkbenchStartRequest(draft, extensions, clientRequestId)
  request.input = { ...request.input, ...context.input, webSearchEnabled: draft.webSearchEnabled }
  if (context.attachmentIds) request.attachmentIds = [...context.attachmentIds]
  if (context.materialRefs) request.materialRefs = [...context.materialRefs]
  if (context.sourceRefs && request.semantics) request.semantics.sourceRefs = [...context.sourceRefs]
  return request
}

export interface ConversationLaunchContext extends LaunchMaterials {
  goal: string
  conversationId: string
  chatContextId: string | null
  chatRoleId: string | null
  messages: ReadonlyArray<{ role: string; content: string }>
  source: 'chat' | 'agent'
  title?: string
  domain?: string
  intent?: string
  workflowId?: string
  reviewMode?: string
  enabledPluginIds?: string[]
  // Only execution settings, never model credentials/connections.
  execution?: { thinkingMode?: WorkbenchDraft['thinkingMode']; reasoningEffort?: string; webSearchEnabled?: boolean }
}

export function buildConversationLaunchRequest(
  context: ConversationLaunchContext,
  clientRequestId: string
): AsyncWorkflowStartRequest {
  const draft = createNativeWorkbenchDraft()
  draft.taskGoal = context.goal
  draft.title = context.title || `${context.source === 'agent' ? 'Agent' : 'Chat'} ACG：${context.goal.slice(0, 40)}`
  draft.enabledPluginIds = [...(context.enabledPluginIds || [])]
  const request = buildWorkbenchLaunchRequest(draft, [], clientRequestId, context)
  request.domain = context.domain || 'legal'
  request.intent = context.intent || 'case_analysis'
  request.workflowId = context.workflowId
  request.reviewMode = context.reviewMode || 'human_in_loop'
  // Preserve the historical omitted-scope behavior of Conversation launches.
  request.enabledPluginIds = context.enabledPluginIds ? [...context.enabledPluginIds] : undefined
  request.input = {
    ...request.input,
    source: context.source,
    ...(context.source === 'chat' ? { caseText: context.goal, chatText: context.goal } : {}),
    conversationId: context.conversationId,
    chatContextId: context.chatContextId,
    chatRoleId: context.chatRoleId,
    chatContext: context.messages.slice(-8).filter(message => message.content)
      .map(message => ({ role: message.role, content: message.content })),
    ...context.execution
  }
  return request
}
