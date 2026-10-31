import type { AsyncWorkflowStartRequest } from '@/services/api/workflow'
import type { WorkbenchDraft, PluginUiExtension } from '@/features/acg/workbench'
import { buildConversationLaunchRequest, buildWorkbenchLaunchRequest, type ConversationLaunchContext, type LaunchMaterials } from './request'
import type { MissionLaunchEntry } from './policy'
import { resolveMissionLaunchPolicy } from './policy'

declare const commandBrand: unique symbol
export interface MissionLaunchCommand {
  readonly [commandBrand]: true
  readonly entry: MissionLaunchEntry
  readonly request: AsyncWorkflowStartRequest
}
const commands = new WeakSet<object>()
export const cloneLaunchValue = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T

export function canonicalLaunchJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(item => canonicalLaunchJson(item ?? null)).join(',')}]`
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().filter(key => value[key] !== undefined)
    .map(key => `${JSON.stringify(key)}:${canonicalLaunchJson(value[key])}`).join(',')}}`
  return JSON.stringify(value)
}

// Full canonical serialization is collision-free; it is a versioned semantic
// fingerprint, not a hash used for authorization. The server hashes wire data.
export function missionCommandFingerprint(command: MissionLaunchCommand): string {
  const body = cloneLaunchValue(command.request)
  delete body.clientRequestId
  delete body.title // display title never authorizes a new operation
  if (body.input) {
    delete body.input.taskName
    delete body.input.debugTrace
  }
  for (const key of ['attachmentIds', 'materialRefs', 'enabledPluginIds'] as const) {
    if (Array.isArray(body[key])) body[key] = [...new Set(body[key])].sort()
  }
  return `mission-command-v1:${canonicalLaunchJson({ entry: command.entry, body })}`
}

function admit(entry: MissionLaunchEntry, request: AsyncWorkflowStartRequest): MissionLaunchCommand {
  const freeze = <T>(value: T): T => {
    if (value && typeof value === 'object') { Object.values(value).forEach(freeze); Object.freeze(value) }
    return value
  }
  const command = freeze({ entry, request: cloneLaunchValue(request) }) as MissionLaunchCommand
  commands.add(command)
  return command
}
export function assertMissionLaunchCommand(value: MissionLaunchCommand): void {
  if (!value || !commands.has(value)) throw new Error('Mission creation requires an admitted MissionLaunchCommand')
}
export function conversationLaunchCommand(context: ConversationLaunchContext): MissionLaunchCommand {
  return admit('conversation', buildConversationLaunchRequest(context, ''))
}
export function matchesConversationLaunchContext(request: AsyncWorkflowStartRequest,
  context: Pick<ConversationLaunchContext, 'goal' | 'source' | 'conversationId'> & Partial<ConversationLaunchContext>): boolean {
  if (request.semantics?.objective !== context.goal || request.input?.source !== context.source
    || request.input?.conversationId !== context.conversationId) return false
  const policy = resolveMissionLaunchPolicy({ entry: 'conversation', explicit: context, inherited: request, profile: context.policyProfile })
  for (const key of ['domain', 'intent', 'workflowId', 'reviewMode', 'enabledPluginIds'] as const) {
    const normalize = (value: unknown) => Array.isArray(value) ? [...new Set(value)].sort() : value
    if (canonicalLaunchJson(normalize(policy[key])) !== canonicalLaunchJson(normalize(request[key]))) return false
  }
  return !Object.entries(context.execution || {}).some(([key, value]) => value !== undefined && request.input?.[key] !== value)
}
export function workbenchLaunchCommand(draft: WorkbenchDraft, extensions: PluginUiExtension[], context?: LaunchMaterials & { input?: Record<string, unknown> }): MissionLaunchCommand {
  return admit('workbench', buildWorkbenchLaunchRequest(draft, extensions, '', context))
}
export function legacyAcgLaunchCommand(draft: WorkbenchDraft, extensions: PluginUiExtension[], context?: LaunchMaterials & { input?: Record<string, unknown> }): MissionLaunchCommand {
  return admit('legacy-acg', buildWorkbenchLaunchRequest(draft, extensions, '', context))
}
export function restoreMissionLaunchCommand(entry: MissionLaunchEntry, request: AsyncWorkflowStartRequest): MissionLaunchCommand {
  return admit(entry, request)
}
