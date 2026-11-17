export interface GraphDifference {
  addedNodeIds: string[]
  updatedNodeIds: string[]
  removedNodeIds: string[]
  addedEdgeIds: string[]
  updatedEdgeIds: string[]
  removedEdgeIds: string[]
}

export type GraphChange = 'added' | 'updated' | 'removed'
export const graphChangeLabel: Record<GraphChange, string> = { added: '新增', updated: '调整', removed: '移除' }
export const graphChangeColor: Record<GraphChange, string> = {
  added: 'var(--sem-success, #8bcb78)', updated: 'var(--sem-waiting, #d9b86c)', removed: 'var(--sem-failed, #e06c75)'
}
export const graphDifferenceMaps = (difference?: GraphDifference | null) => {
  const nodes = new Map<string, GraphChange>()
  const edges = new Map<string, GraphChange>()
  if (difference) {
    for (const change of ['added', 'updated', 'removed'] as const) {
      for (const id of difference[`${change}NodeIds`]) nodes.set(id, change)
      for (const id of difference[`${change}EdgeIds`]) edges.set(id, change)
    }
  }
  return { nodes, edges }
}
