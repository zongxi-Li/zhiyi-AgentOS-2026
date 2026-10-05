import { describe, expect, it } from 'vitest'
import type { WorkspaceEntry } from '@/services/api/agentos'
import { projectArtifactDocument, renderArtifactDocument, resolveArtifactKind } from './artifactProjection'

const entry: WorkspaceEntry = {
  entryId: 'task:requirements',
  kind: 'task',
  name: '硬约束需求',
  title: '硬约束需求',
  group: 'steps',
  displayOrder: 0,
  semanticTaskKey: 'requirement_analysis',
  objective: '将15项硬约束转化为可测试需求与验收标准。',
  dependencyKeys: ['input:constraints'],
  metadata: { outputRef: 'output:requirements' }
}

const output = {
  requirements: [{
    id: 'REQ-03',
    requirement: '试生产及爬坡周期不超过 6 周，并给出逐周产量与节拍目标。',
    priority: '高',
    source: 'constraint:03'
  }],
  acceptance_criteria: [{
    requirement_id: 'REQ-03',
    metric: '试生产 + 爬坡周数',
    target: '≤ 6 周',
    criterion: '逐周产量与节拍目标均已给出。',
    evidence_ref: 'evidence:constraint:03'
  }],
  assumptions: ['周定义采用自然周']
}

describe('artifactProjection', () => {
  it('dispatches requirements schema to a semantic document projection', () => {
    expect(resolveArtifactKind(entry, output)).toBe('requirements_specification')
    const document = projectArtifactDocument({ entry, output })
    const markdown = renderArtifactDocument(document)

    expect(markdown).toContain('### REQ-03 试生产及爬坡周期')
    expect(markdown).toContain('**验收目标**')
    expect(markdown).toContain('**验收指标**')
    expect(markdown).toContain('**验收判据**')
    expect(markdown).toContain('Requirement Acceptance Matrix')
    expect(markdown).toContain('| REQ-03 | 试生产 + 爬坡周数 | ≤ 6 周 |')
    expect(markdown).not.toContain('- metric:')
    expect(markdown).not.toContain('- requirement_id:')
    expect(markdown).not.toContain('- target:')
    expect(markdown).not.toContain('- criterion:')
    expect(document.inspector.evidenceRefs).toContain('evidence:constraint:03')
    expect(document.inspector.upstreamInputs).toContain('input:constraints')
    expect(document.blocks.every(block => block.blockId)).toBe(true)
    expect(document.blocks.filter(block => block.gutter).map(block => block.blockId)).toEqual([
      'intro',
      'req-03',
      'acceptance-matrix',
      'assumptions'
    ])
    expect(document.blocks.filter(block => block.blockId === 'req-03' && block.gutter)).toHaveLength(1)
  })

  it('uses the generic renderer only for unknown schemas', () => {
    const unknown = projectArtifactDocument({
      entry: { ...entry, semanticTaskKey: 'custom_payload' },
      output: { custom_payload: { value: 'x' } }
    })
    expect(unknown.artifactKind).toBe('unknown')
    expect(renderArtifactDocument(unknown)).toContain('custom payload')
  })

  it('preserves nested records in intermediate results instead of displaying record placeholders', () => {
    const document = projectArtifactDocument({
      entry: { ...entry, semanticTaskKey: 'solution_design' },
      output: { design: { groups: [
        { name: '第一组', count: 8, activities: [{ title: '阅读交流', duration: 30 }] },
        { name: '第二组', count: 7, activities: [{ title: '成果分享', duration: 20 }] }
      ] } }
    })
    const markdown = renderArtifactDocument(document)
    expect(markdown).toContain('第一组')
    expect(markdown).toContain('阅读交流')
    expect(markdown).toContain('30')
    expect(markdown).toContain('第二组')
    expect(markdown).toContain('成果分享')
    expect(markdown).not.toContain('记录')
    const ids = document.blocks.filter(block => block.gutter).map(block => block.blockId)
    expect(new Set(ids).size).toBe(ids.length)
  })
})
