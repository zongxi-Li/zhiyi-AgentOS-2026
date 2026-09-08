import {
  agentosApi,
  type ResourceBindingObservation,
  type ResourceObservation,
  type RunExecutionTree
} from '@/services/api/agentos'

const asRecord = (value: unknown): Record<string, unknown> => (
  value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
)

const asStringArray = (value: unknown): string[] => (
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
)

const asNumberRecord = (value: unknown): Record<string, number> => {
  const record = asRecord(value)
  return Object.fromEntries(
    Object.entries(record).filter(([, item]) => typeof item === 'number' && Number.isFinite(item))
  ) as Record<string, number>
}

/**
 * Read-only resource projection for the Workbench.
 *
 * The ResourceService remains the authority for profiles/snapshots and the V2
 * execution tree remains the authority for attempt bindings.  This adapter
 * only joins those two responses for Inspector consumption; it does not cache
 * or persist runtime state.
 */
export const loadResourceObservation = async (
  runId: string,
  options: { signal?: AbortSignal } = {},
  executionTreeRequest?: Promise<RunExecutionTree>
): Promise<ResourceObservation> => {
  const [resourceResponse, executionTree] = await Promise.all([
    agentosApi.listResources(options),
    executionTreeRequest || agentosApi.getExecutionTree(runId, options)
  ])

  return {
    runId,
    items: resourceResponse.items,
    bindings: collectBindings(executionTree),
    attemptCount: executionTree.nodes.reduce((count, node) => count + node.attempts.length, 0),
    source: 'ResourceService + V2 ExecutionBinding',
    failoverEvents: []
  }
}

const collectBindings = (tree: RunExecutionTree): ResourceBindingObservation[] => tree.nodes.flatMap(node => (
  node.attempts.flatMap(detail => {
    const binding = detail.executionBinding
    if (!binding) return []
    const metadata = asRecord(binding.metadata)
    return [{
      ...binding,
      taskId: detail.attempt.taskId,
      semanticTaskKey: node.task.semanticTaskKey || null,
      attemptNumber: detail.attempt.attemptNumber,
      attemptStatus: detail.attempt.status,
      startedAt: detail.attempt.startedAt || null,
      finishedAt: detail.attempt.finishedAt || null,
      deploymentTier: typeof metadata.deploymentTier === 'string' ? metadata.deploymentTier : null,
      placementReasons: asStringArray(metadata.placementReasons),
      scoreFactors: asNumberRecord(metadata.scoreFactors)
    }]
  })
))
