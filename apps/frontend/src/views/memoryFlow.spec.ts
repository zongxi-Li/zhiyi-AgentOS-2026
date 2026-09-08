import { describe, expect, it } from 'vitest'
import type { RunMemoryEvent } from '@/services/api/agentos'
import { projectMemoryFlow, shortStepLabel, stepIdFromMemoryRef } from './memoryFlow'

const access = (stepId: string, hitRefs: string[], createdAt: string) => ({
  kind: 'memory_access' as const,
  stepId,
  retrievalMode: 'bm25_vector_rrf',
  hitRefs,
  budget: null,
  fallbackReason: null,
  createdAt
})

const write = (stepId: string, createdAt: string) => ({
  kind: 'memory_event' as const,
  stepId,
  commitId: `commit:${stepId}:0`,
  summary: 'Workset completed',
  metrics: { fieldCount: 3, modelInvocationCount: 1 },
  createdAt
})

describe('stepIdFromMemoryRef', () => {
  it('解析 memory:{run}:{step} 引用', () => {
    expect(stepIdFromMemoryRef('memory:run_abc:native_general_agent_2')).toBe('native_general_agent_2')
  })

  it('保留 stepId 内部的冒号', () => {
    expect(stepIdFromMemoryRef('memory:run_abc:step:with:colons')).toBe('step:with:colons')
  })

  it('拒绝非 memory 前缀或字段缺失的引用', () => {
    expect(stepIdFromMemoryRef('capsule:run_abc:deliver')).toBeNull()
    expect(stepIdFromMemoryRef('memory:run_abc:')).toBeNull()
    expect(stepIdFromMemoryRef('memory:only')).toBeNull()
  })
})

describe('shortStepLabel', () => {
  it('缩短 native 与 ctrl 前缀', () => {
    expect(shortStepLabel('native_general_agent_16')).toBe('agent 16')
    expect(shortStepLabel('native_general_agent')).toBe('agent')
    expect(shortStepLabel('ctrl_parallel_1')).toBe('ctrl parallel_1')
    expect(shortStepLabel('other_step')).toBe('other_step')
  })
})

describe('projectMemoryFlow', () => {
  it('空输入返回空投影', () => {
    const result = projectMemoryFlow([])
    expect(result.steps).toEqual([])
    expect(result.edges).toEqual([])
    expect(result.capsules).toEqual([])
    expect(result.stats).toEqual({ reads: 0, writes: 0, capsules: 0, hitRefs: 0, hitEdges: 0 })
  })

  it('按 stepId 聚合召回与写入，并按首次时间排序', () => {
    const items: RunMemoryEvent[] = [
      access('agent_b', ['memory:r1:agent_a'], '2026-09-08T12:01:00Z'),
      write('agent_a', '2026-09-08T12:00:00Z'),
      write('agent_b', '2026-09-08T12:02:00Z')
    ]
    const result = projectMemoryFlow(items)
    expect(result.steps.map(step => step.stepId)).toEqual(['agent_a', 'agent_b'])
    expect(result.steps[0].write?.stepId).toBe('agent_a')
    expect(result.steps[1].access?.hitRefs).toEqual(['memory:r1:agent_a'])
  })

  it('从 hitRefs 生成去重的记忆流向边，忽略自引用与非法引用', () => {
    const items: RunMemoryEvent[] = [
      write('agent_a', '2026-09-08T12:00:00Z'),
      access('agent_c', ['memory:r1:agent_a', 'memory:r1:agent_b', 'bad-ref'], '2026-09-08T12:03:00Z'),
      access('agent_c', ['memory:r1:agent_a'], '2026-09-08T12:04:00Z'),
      access('agent_x', ['memory:r1:agent_x'], '2026-09-08T12:05:00Z')
    ]
    const result = projectMemoryFlow(items)
    expect(result.edges).toEqual([
      { sourceStepId: 'agent_a', targetStepId: 'agent_c' },
      { sourceStepId: 'agent_b', targetStepId: 'agent_c' }
    ])
    expect(result.stats.hitEdges).toBe(2)
    expect(result.stats.hitRefs).toBe(5)
  })

  it('同一召回步骤多次出现时保留命中最多的一次', () => {
    const items: RunMemoryEvent[] = [
      access('agent_b', ['memory:r1:agent_a'], '2026-09-08T12:01:00Z'),
      access('agent_b', ['memory:r1:agent_a', 'memory:r1:agent_c'], '2026-09-08T12:02:00Z'),
      access('agent_b', ['memory:r1:agent_a'], '2026-09-08T12:03:00Z')
    ]
    const result = projectMemoryFlow(items)
    expect(result.steps[0].access?.hitRefs).toHaveLength(2)
    expect(result.stats.reads).toBe(3)
  })

  it('阶段胶囊单列并计入统计', () => {
    const items: RunMemoryEvent[] = [
      {
        kind: 'phase_capsule',
        phaseId: 'deliver',
        capsuleRef: 'capsule:r1:deliver',
        sourceMemoryRefs: ['memory:r1:agent_a'],
        tokenCount: 384
      }
    ]
    const result = projectMemoryFlow(items)
    expect(result.capsules).toHaveLength(1)
    expect(result.capsules[0].phaseId).toBe('deliver')
    expect(result.stats.capsules).toBe(1)
  })
})
