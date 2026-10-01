import {
  agentosApi,
  type ResourceBindingObservation,
  type ResourceObservation,
  type RunExecutionTree
} from '@/services/api/agentos'

/**
 * Read-only resource projection for the Workbench.
 *
 * The ResourceService remains the authority for profiles/snapshots and the V2
 * execution tree remains the source for observed resource usage.  This adapter
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
    source: 'ResourceService + Query resource usage',
    failoverEvents: []
  }
}

const collectBindings = (tree: RunExecutionTree): ResourceBindingObservation[] => tree.nodes.flatMap(node => (
  node.attempts.flatMap(detail => {
    const binding = detail.resourceUse
    if (!binding) return []
    return [{
      resourceId: binding.resourceId,
      agentId: binding.agentId,
      modelId: binding.modelId,
      acgNodeId: binding.acgNodeId,
      attemptId: detail.attempt.attemptId,
      taskId: detail.attempt.taskId,
      semanticTaskKey: node.task.semanticTaskKey || null,
      attemptNumber: detail.attempt.attemptNumber,
      attemptStatus: detail.attempt.status,
      startedAt: detail.attempt.startedAt || null,
      finishedAt: detail.attempt.finishedAt || null,
      deploymentTier: binding.deploymentTier || null
    }]
  })
))
