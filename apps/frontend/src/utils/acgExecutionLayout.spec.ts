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
    expect(x).toEqual([0, 420, 840, 1260])
  })

  it('handles isolated nodes, self loops and dangling edges without overlapping nodes', () => {
    const positions = executionLayout(nodes('a', 'b', 'c'), edges(['a', 'a'], ['missing', 'b']))
    expect(positions.size).toBe(3)
    expect(new Set([...positions.values()].map(p => `${p.x},${p.y}`)).size).toBe(3)
  })

  it('untangles reversed parallel branches rather than retaining input row order', () => {
    const graph = nodes('a', 'b', 'c', 'd', 'e', 'f')
    const links = edges(['a', 'b'], ['a', 'c'], ['b', 'e'], ['c', 'd'], ['d', 'f'], ['e', 'f'])
    const positions = executionLayout(graph, links)
    expect((positions.get('b')!.y - positions.get('c')!.y) * (positions.get('e')!.y - positions.get('d')!.y)).toBeGreaterThan(0)
    expect(positions.get('a')!.y).toBe(positions.get('f')!.y)
    expect(executionLayout(graph, [...links].reverse())).toEqual(positions)
  })

  it('keeps disconnected chains in separate bands without changing their dependency ranks', () => {
    const positions = executionLayout(nodes('a', 'b', 'c', 'd'), edges(['a', 'b'], ['c', 'd']))
    expect(positions.get('a')!.y).toBe(positions.get('b')!.y)
    expect(positions.get('c')!.y).toBe(positions.get('d')!.y)
    expect(positions.get('a')!.y).toBeLessThan(positions.get('c')!.y)
    expect(positions.get('a')!.x).toBe(positions.get('c')!.x)
  })

  it('keeps explicitly related siblings together without inventing serial dependencies', () => {
    const graph = nodes('root', 'a', 'b', 'c', 'end')
    const links = edges(['root', 'a'], ['root', 'b'], ['root', 'c'], ['a', 'end'], ['b', 'end'], ['c', 'end'])
    const parents = new Map([['a', 'work-package'], ['c', 'work-package']])
    const positions = executionLayout(graph, links, parents)
    expect(Math.abs(positions.get('a')!.y - positions.get('c')!.y)).toBe(160)
    expect(positions.get('a')!.x).toBe(positions.get('b')!.x)
    expect(positions.get('a')!.x).toBe(positions.get('c')!.x)
  })

  it('preserves all forward dependencies and inputs including long and duplicate edges', () => {
    const graph = nodes('a', 'b', 'c', 'd', 'e')
    const links = edges(['a', 'b'], ['b', 'c'], ['c', 'd'], ['d', 'e'], ['a', 'e'], ['a', 'e'])
    const original = JSON.stringify({ graph, links })
    const positions = executionLayout(graph, links)
    expect(positions.size).toBe(graph.length)
    for (const link of links) expect(positions.get(link.sourceId)!.x).toBeLessThan(positions.get(link.targetId)!.x)
    expect(new Set([...positions.values()].map(p => `${p.x},${p.y}`)).size).toBe(graph.length)
    expect(JSON.stringify({ graph, links })).toBe(original)
    expect(executionLayout([], [])).toEqual(new Map())
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
