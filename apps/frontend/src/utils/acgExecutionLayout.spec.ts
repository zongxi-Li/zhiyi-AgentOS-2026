import { describe, expect, it } from 'vitest'
import type { AcgEdge, AcgNode } from '@/services/api/agentos'
import { executionLayout, executionNodeLabel } from './acgExecutionLayout'

const nodes = (...ids: string[]): AcgNode[] => ids.map(nodeId => ({ nodeId, nodeType: 'step' }))
const edges = (...pairs: string[][]): AcgEdge[] => pairs.map(([sourceId, targetId], i) => ({
  sourceId: sourceId!, targetId: targetId!, edgeId: String(i), edgeType: 'dependency'
}))

describe('execution graph layout', () => {
  it('keeps dependencies left to right and parallel branches in separate rows', () => {
    const positions = executionLayout(nodes('a', 'b', 'c', 'd'), edges(['a', 'b'], ['a', 'c'], ['b', 'd'], ['c', 'd']))
    expect(positions.get('a')!.x).toBeLessThan(positions.get('b')!.x)
    expect(positions.get('b')!.x).toBe(positions.get('c')!.x)
    expect(positions.get('b')!.y).not.toBe(positions.get('c')!.y)
    expect(positions.get('c')!.x).toBeLessThan(positions.get('d')!.x)
  })

  it('unrolls a cycle in stable task order and places downstream tasks after the cycle', () => {
    const positions = executionLayout(nodes('a', 'b', 'c', 'd'), edges(['a', 'b'], ['b', 'c'], ['c', 'a'], ['c', 'd']))
    const x = ['a', 'b', 'c', 'd'].map(id => positions.get(id)!.x)
    expect(x).toEqual([0, 360, 720, 1080])
  })

  it('handles isolated nodes, self loops and dangling edges without overlapping nodes', () => {
    const positions = executionLayout(nodes('a', 'b', 'c'), edges(['a', 'a'], ['missing', 'b']))
    expect(positions.size).toBe(3)
    expect(new Set([...positions.values()].map(p => `${p.x},${p.y}`)).size).toBe(3)
  })

  it('bounds long titles to two lines without splitting Unicode characters', () => {
    const label = executionNodeLabel('产线设备与工装规划'.repeat(5))
    expect(label.split('\n')).toHaveLength(2)
    expect(label.endsWith('…')).toBe(true)
    expect(executionNodeLabel('短标题')).toBe('短标题')
  })

  it('breaks long identifiers at underscores instead of mid-word', () => {
    expect(executionNodeLabel('VERIFICATION_LOOP')).toBe('VERIFICATION_\nLOOP')
    expect(executionNodeLabel('任务理解与目标界定')).toBe('任务理解与目标界定')
  })
})
