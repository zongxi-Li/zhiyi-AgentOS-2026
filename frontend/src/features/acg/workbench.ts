import type { Component } from 'vue'
import type { AsyncWorkflowStartRequest } from '@/services/api/workflow'
import type { GlmReasoningEffort } from '@/config/modelSettings'

export type WorkbenchPlanningMode = 'dynamic' | 'template_preferred'
export type PlanningDiversity = 'stable' | 'balanced' | 'exploratory'

export interface WorkbenchDraft {
  title: string
  taskGoal: string
  materialText: string
  constraints: string[]
  expectedArtifacts: string[]
  materialIds: string[]
  enabledPluginIds: string[]
  planningMode: WorkbenchPlanningMode
  planningDiversity: PlanningDiversity
  planningSeed: number | null
  webSearchEnabled: boolean
  thinkingMode: 'disabled' | 'standard' | 'deep'
  reasoningEffort?: GlmReasoningEffort
  reviewMode: 'auto' | 'human_in_loop'
  pluginData: Record<string, Record<string, unknown>>
}

export interface WorkbenchHistoryConfig {
  runId: string
  title?: string | null
  reviewMode?: string
  enabledPluginIds?: string[]
  input?: Record<string, unknown>
}

export interface PluginValidationResult {
  valid: boolean
  message?: string
}

export interface PluginArtifactRendererProps {
  deliverables: unknown[]
  finalReport: string | null
}

export interface PluginUiExtension {
  pluginId: string
  displayName: string
  createDefaults?: () => Partial<WorkbenchDraft>
  validateDraft?: (draft: WorkbenchDraft) => PluginValidationResult
  buildStartRequest?: (
    draft: WorkbenchDraft
  ) => Partial<AsyncWorkflowStartRequest>
  hydratePluginData?: (
    runInput: Record<string, unknown>,
    current: Record<string, unknown>
  ) => Record<string, unknown>
  taskInputComponent?: Component
  strategyComponent?: Component
  artifactRenderer?: Component
}

export const createNativeWorkbenchDraft = (): WorkbenchDraft => ({
  title: '',
  taskGoal: '',
  materialText: '',
  constraints: [],
  expectedArtifacts: [],
  materialIds: [],
  enabledPluginIds: [],
  planningMode: 'dynamic',
  planningDiversity: 'stable',
  planningSeed: null,
  webSearchEnabled: true,
  thinkingMode: 'disabled',
  reasoningEffort: undefined,
  reviewMode: 'auto',
  pluginData: {}
})

const stringList = (value: unknown): string[] => (
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
)

const enumValue = <T extends string>(value: unknown, allowed: readonly T[]): T | undefined => (
  typeof value === 'string' && (allowed as readonly string[]).includes(value) ? value as T : undefined
)

export const restoreWorkbenchDraft = (
  draft: WorkbenchDraft,
  config: WorkbenchHistoryConfig,
  extensions: PluginUiExtension[]
): void => {
  const input = config.input || {}
  if (typeof config.title === 'string') draft.title = config.title
  if (typeof input.taskGoal === 'string') draft.taskGoal = input.taskGoal
  else if (typeof input.userIntent === 'string') draft.taskGoal = input.userIntent
  if (typeof input.materialText === 'string') draft.materialText = input.materialText
  draft.materialIds = stringList(input.materialIds)
  draft.constraints = stringList(input.constraints)
  draft.expectedArtifacts = stringList(input.expectedArtifacts)
  draft.enabledPluginIds = stringList(config.enabledPluginIds)
  const planningMode = enumValue(input.planningMode, ['dynamic', 'template_preferred'] as const)
  if (planningMode) draft.planningMode = planningMode
  const planningDiversity = enumValue(input.planningDiversity, ['stable', 'balanced', 'exploratory'] as const)
  if (planningDiversity) draft.planningDiversity = planningDiversity
  draft.planningSeed = typeof input.planningSeed === 'number' && Number.isInteger(input.planningSeed)
    ? input.planningSeed
    : null
  if (typeof input.webSearchEnabled === 'boolean') draft.webSearchEnabled = input.webSearchEnabled
  const thinkingMode = enumValue(input.thinkingMode, ['disabled', 'standard', 'deep'] as const)
  if (thinkingMode) draft.thinkingMode = thinkingMode
  const reasoningEffort = enumValue(input.reasoningEffort, ['low', 'high', 'max'] as const)
  draft.reasoningEffort = reasoningEffort
  if (reasoningEffort) draft.thinkingMode = reasoningEffort === 'low' ? 'standard' : 'deep'
  const reviewMode = enumValue(config.reviewMode, ['auto', 'human_in_loop'] as const)
  if (reviewMode) draft.reviewMode = reviewMode
  draft.pluginData = input.pluginData && typeof input.pluginData === 'object' && !Array.isArray(input.pluginData)
    ? clonePluginData(input.pluginData as WorkbenchDraft['pluginData'])
    : {}

  for (const extension of extensions) {
    const defaults = extension.createDefaults?.().pluginData?.[extension.pluginId] || {}
    const current = { ...defaults, ...(draft.pluginData[extension.pluginId] || {}) }
    const hydrated = extension.hydratePluginData?.(input, current) || current
    draft.pluginData[extension.pluginId] = hydrated
  }
}

const mergeInput = (
  base: Record<string, unknown>,
  addition: unknown
): Record<string, unknown> => (
  addition && typeof addition === 'object'
    ? { ...base, ...(addition as Record<string, unknown>) }
    : base
)

const clonePluginData = (value: WorkbenchDraft['pluginData']) =>
  JSON.parse(JSON.stringify(value)) as WorkbenchDraft['pluginData']

export const buildWorkbenchStartRequest = (
  draft: WorkbenchDraft,
  extensions: PluginUiExtension[],
  clientRequestId: string
): AsyncWorkflowStartRequest => {
  let domain = 'general'
  let intent = 'general'
  let workflowId: string | undefined
  let reviewMode = draft.reviewMode
  let input: Record<string, unknown> = {
    source: 'acg',
    userIntent: draft.taskGoal,
    taskGoal: draft.taskGoal,
    materialText: draft.materialText,
    materialIds: [...draft.materialIds],
    constraints: [...draft.constraints],
    expectedArtifacts: [...draft.expectedArtifacts],
    planningMode: draft.planningMode,
    usePlanner: true,
    webSearchEnabled: draft.webSearchEnabled,
    thinkingMode: draft.thinkingMode,
    ...(draft.reasoningEffort ? { reasoningEffort: draft.reasoningEffort } : {}),
    planningDiversity: draft.planningDiversity,
    ...(draft.planningSeed === null ? {} : { planningSeed: draft.planningSeed }),
    pluginData: clonePluginData(draft.pluginData)
  }

  for (const extension of extensions) {
    const contribution = extension.buildStartRequest?.(draft)
    if (!contribution) continue
    if (contribution.domain) domain = contribution.domain
    if (contribution.intent) intent = contribution.intent
    if (contribution.workflowId !== undefined) workflowId = contribution.workflowId
    if (contribution.reviewMode === 'auto' || contribution.reviewMode === 'human_in_loop') {
      reviewMode = contribution.reviewMode
    }
    input = mergeInput(input, contribution.input)
  }

  // The user's privacy/network choice is authoritative across every plugin.
  input.webSearchEnabled = draft.webSearchEnabled

  return {
    title: draft.title.trim(),
    domain,
    intent,
    workflowId,
    reviewMode,
    input,
    clientRequestId,
    enabledPluginIds: [...draft.enabledPluginIds]
  }
}
