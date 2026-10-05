import type { WorkspaceEntry } from '@/services/api/agentos'

export type ArtifactKind =
  | 'requirements_specification'
  | 'evidence_assessment'
  | 'comparison_report'
  | 'final_report'
  | 'unknown'

type ArtifactDocumentBlockShape =
  | { type: 'heading'; level: 2 | 3; text: string }
  | { type: 'paragraph'; label?: string; text: string }
  | { type: 'callout'; tone: 'info' | 'success' | 'warning'; label?: string; text: string }
  | { type: 'list'; items: string[]; ordered?: boolean }
  | { type: 'table'; columns: string[]; rows: string[][] }

export type ArtifactDocumentBlock = ArtifactDocumentBlockShape & {
  /** Stable semantic identity used by gutter, Inspector jumps, and future trace links. */
  blockId: string
  /** Only the first fragment of a major semantic block receives a gutter index. */
  gutter?: boolean
}

type ArtifactDocumentBlockDraft = ArtifactDocumentBlockShape & {
  blockId?: string
  gutter?: boolean
}

export interface ArtifactInspectorProjection {
  artifactKind: ArtifactKind
  artifactType: string | null
  evidenceRefs: string[]
  confidence: string | null
  upstreamInputs: string[]
  provenance: Array<{ label: string; value: string; code?: boolean }>
  traceLinks: string[]
}

export interface ArtifactDocumentModel {
  artifactKind: ArtifactKind
  kindLabel: string
  title: string
  summary: string
  blocks: ArtifactDocumentBlock[]
  inspector: ArtifactInspectorProjection
}

export interface ArtifactProjectionInput {
  entry: WorkspaceEntry
  artifacts?: WorkspaceEntry[]
  output: unknown
}

type JsonRecord = Record<string, unknown>

const KIND_LABELS: Record<ArtifactKind, string> = {
  requirements_specification: 'Requirements',
  evidence_assessment: 'Evidence assessment',
  comparison_report: 'Comparison report',
  final_report: 'Final report',
  unknown: 'Artifact'
}

const isRecord = (value: unknown): value is JsonRecord => (
  typeof value === 'object' && value !== null && !Array.isArray(value)
)

const text = (value: unknown): string => {
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return ''
}

const list = (value: unknown): string[] => {
  if (!Array.isArray(value)) return []
  return value.flatMap(item => {
    if (typeof item === 'string' || typeof item === 'number' || typeof item === 'boolean') {
      const value = text(item)
      return value ? [value] : []
    }
    return []
  })
}

const recordList = (value: unknown): JsonRecord[] => (
  Array.isArray(value) ? value.filter(isRecord) : []
)

const firstText = (record: JsonRecord, keys: string[]): string => {
  for (const key of keys) {
    const value = text(record[key])
    if (value) return value
  }
  return ''
}

const normalizeKindToken = (value: unknown) => text(value)
  .toLowerCase()
  .replace(/[\s-]+/g, '_')

const unwrapOutput = (value: unknown): unknown => {
  if (!isRecord(value)) return value
  if (isRecord(value.structuredData)) return value.structuredData
  if (isRecord(value.structured_data)) return value.structured_data
  return value
}

const parseOutput = (value: unknown): unknown => {
  if (typeof value !== 'string') return value
  const raw = value.trim()
  if (!raw) return null
  try { return JSON.parse(raw) as unknown } catch { return raw }
}

const explicitKindCandidates = (entry: WorkspaceEntry): unknown[] => [
  entry.metadata?.artifactKind,
  entry.metadata?.artifact_kind,
  entry.metadata?.schema,
  entry.metadata?.schemaName,
  entry.artifactType,
  entry.logicalRole,
  entry.semanticTaskKey
]

const kindFromToken = (token: string): ArtifactKind | null => {
  if (token.includes('requirement') || token.includes('acceptance')) return 'requirements_specification'
  if (token.includes('evidence') || token.includes('assessment') || token.includes('verification')) return 'evidence_assessment'
  if (token.includes('compar') || token.includes('alternative')) return 'comparison_report'
  if (token.includes('final') || token.includes('report') || token.includes('deliverable')) return 'final_report'
  return null
}

export const resolveArtifactKind = (entry: WorkspaceEntry, output: unknown): ArtifactKind => {
  for (const candidate of explicitKindCandidates(entry)) {
    const kind = kindFromToken(normalizeKindToken(candidate))
    if (kind) return kind
  }

  const value = unwrapOutput(output)
  if (isRecord(value)) {
    if (Array.isArray(value.requirements) || Array.isArray(value.acceptance_criteria) || Array.isArray(value.acceptanceCriteria)) {
      return 'requirements_specification'
    }
    if (Array.isArray(value.evidence_analysis) || Array.isArray(value.evidenceAnalysis)) return 'evidence_assessment'
    if (isRecord(value.comparison) || Array.isArray(value.alternatives)) return 'comparison_report'
    if (text(value.final_report) || text(value.final_answer) || text(value.report_markdown)) return 'final_report'
  }
  return 'unknown'
}

const shortTitle = (value: string, fallback: string) => {
  const firstSentence = value.split(/[。！？!?；;\n]/)[0].trim()
  const beforeCondition = firstSentence.split(/(?=不超过|不少于|不低于|不得|至少|至多|应当|需要|必须|并给出|并提供)/)[0].trim()
  return (beforeCondition || firstSentence || fallback).slice(0, 42)
}

const requirementId = (record: JsonRecord, index: number) => (
  firstText(record, ['id', 'requirement_id', 'requirementId']) || `REQ-${String(index + 1).padStart(2, '0')}`
)

interface RequirementRecord {
  id: string
  title: string
  objective: string
  metric: string
  target: string
  criterion: string
  priority: string
  source: string
}

const requirementRecords = (value: JsonRecord): RequirementRecord[] => {
  const requirements = recordList(value.requirements)
  const criteria = recordList(value.acceptance_criteria || value.acceptanceCriteria)
  const requirementsById = new Map(requirements.map((item, index) => [requirementId(item, index), item]))
  const byId = new Map(criteria.map((item, index) => [requirementId(item, index), item]))
  const ids = [...new Set([
    ...requirements.map((item, index) => requirementId(item, index)),
    ...criteria.map((item, index) => requirementId(item, index))
  ])]

  return ids.map((id, index) => {
    const requirement = requirementsById.get(id) || requirements[index] || {}
    const criterion = byId.get(id) || criteria[index] || {}
    const objective = firstText(requirement, ['requirement', 'description', 'objective', 'title', 'name'])
      || firstText(criterion, ['requirement', 'description', 'criterion'])
    const criterionText = firstText(criterion, ['criterion', 'acceptance_criterion', 'acceptanceCriterion', 'description'])
    return {
      id,
      title: firstText(requirement, ['title', 'name']) || shortTitle(objective || criterionText, `要求 ${id}`),
      objective: objective || '未提供验收目标。',
      metric: firstText(criterion, ['metric', 'measure', 'indicator']) || '未提供验收指标。',
      target: firstText(criterion, ['target', 'targetValue', 'target_value']) || '未提供目标值。',
      criterion: criterionText || '未提供验收判据。',
      priority: firstText(requirement, ['priority', 'mandatory', 'required']),
      source: firstText(requirement, ['source', 'sourceRef', 'source_ref'])
    }
  })
}

const tableCell = (value: string) => value.replace(/\|/g, '\\|').replace(/\r?\n/g, ' ')

const requirementsProjector = (entry: WorkspaceEntry, value: JsonRecord): ArtifactDocumentModel => {
  const requirements = requirementRecords(value)
  const summary = firstText(value, ['summary', 'overview', 'task_summary']) || entry.objective?.trim() || '已将结构化约束整理为可测试的需求与验收标准。'
  const blocks: ArtifactDocumentBlockDraft[] = [
    { type: 'heading', level: 2, text: '需求与验收标准' },
    { type: 'paragraph', text: summary }
  ]

  requirements.forEach(item => {
    blocks.push(
      { type: 'heading', level: 3, text: `${item.id} ${item.title}` },
      { type: 'paragraph', label: '验收目标', text: item.objective },
      { type: 'paragraph', label: '验收指标', text: item.metric },
      { type: 'paragraph', label: '目标值', text: item.target },
      { type: 'paragraph', label: '验收判据', text: item.criterion }
    )
    if (item.priority || item.source) {
      blocks.push({
        type: 'callout',
        tone: item.priority === '高' || item.priority === 'hard' || item.priority === 'true' ? 'warning' : 'info',
        label: item.priority ? '约束级别' : '来源',
        text: item.priority || item.source
      })
    }
  })

  blocks.push({ type: 'heading', level: 2, text: 'Requirement Acceptance Matrix' })
  blocks.push({
    type: 'table',
    columns: ['ID', '指标', '目标值', '验收判据'],
    rows: requirements.map(item => [item.id, item.metric, item.target, item.criterion].map(tableCell))
  })

  const assumptions = list(value.assumptions)
  const openQuestions = list(value.open_questions || value.openQuestions)
  if (assumptions.length) {
    blocks.push({ type: 'heading', level: 2, text: '前提假设' }, { type: 'list', items: assumptions })
  }
  if (openQuestions.length) {
    blocks.push({ type: 'heading', level: 2, text: '待确认事项' }, { type: 'list', items: openQuestions })
  }

  return documentModel(entry, 'requirements_specification', summary, blocks, value)
}

const evidenceProjector = (entry: WorkspaceEntry, value: JsonRecord): ArtifactDocumentModel => {
  const records = recordList(value.evidence_analysis || value.evidenceAnalysis)
  const summary = firstText(value, ['summary', 'overview', 'description']) || entry.objective?.trim() || '对当前主张进行证据核验。'
  const blocks: ArtifactDocumentBlockDraft[] = [
    { type: 'heading', level: 2, text: '证据评估' },
    { type: 'paragraph', text: summary }
  ]
  records.forEach((item, index) => {
    const claim = firstText(item, ['claim', 'finding', 'title']) || `评估项 ${String(index + 1).padStart(2, '0')}`
    const assessment = firstText(item, ['assessment', 'criterion', 'result', 'description']) || '未提供评估结论。'
    blocks.push(
      { type: 'heading', level: 3, text: claim },
      { type: 'paragraph', label: '评估结论', text: assessment }
    )
  })
  blocks.push({ blockId: 'source-trace', type: 'callout', tone: 'info', label: '来源追踪', text: '证据引用与置信度已收纳至右侧 Inspector。' })
  return documentModel(entry, 'evidence_assessment', summary, blocks, value)
}

const comparisonProjector = (entry: WorkspaceEntry, value: JsonRecord): ArtifactDocumentModel => {
  const comparison = isRecord(value.comparison) ? value.comparison : {}
  const summary = firstText(comparison, ['recommendation', 'summary', 'overview']) || entry.objective?.trim() || '比较候选方案并形成选择依据。'
  const blocks: ArtifactDocumentBlockDraft[] = [
    { type: 'heading', level: 2, text: '方案比较' },
    { type: 'paragraph', label: '推荐结论', text: summary }
  ]
  const alternatives = recordList(value.alternatives)
  alternatives.forEach((item, index) => {
    const name = firstText(item, ['name', 'title']) || `方案 ${String(index + 1).padStart(2, '0')}`
    const advantages = list(item.advantages)
    const disadvantages = list(item.disadvantages)
    blocks.push({ type: 'heading', level: 3, text: name })
    if (advantages.length) blocks.push({ type: 'paragraph', label: '优势', text: advantages.join('；') })
    if (disadvantages.length) blocks.push({ type: 'paragraph', label: '限制', text: disadvantages.join('；') })
  })
  const scores = recordList(comparison.scores)
  if (scores.length) {
    const columns = ['方案', ...list(comparison.criteria)]
    blocks.push({
      blockId: 'comparison-matrix',
      type: 'table',
      columns: columns.length > 1 ? columns : ['方案', '评分'],
      rows: scores.map(item => [firstText(item, ['name', 'alternative', 'option']), ...Object.entries(item)
        .filter(([key]) => !['name', 'alternative', 'option'].includes(key))
        .map(([, item]) => text(item) || '—')].map(tableCell))
    })
  }
  return documentModel(entry, 'comparison_report', summary, blocks, value)
}

const finalReportProjector = (entry: WorkspaceEntry, value: JsonRecord): ArtifactDocumentModel => {
  const summary = firstText(value, ['summary', 'overview', 'final_answer', 'finalAnswer', 'report', 'report_markdown', 'content']) || entry.objective?.trim() || '最终成果已生成。'
  const blocks: ArtifactDocumentBlockDraft[] = [
    { type: 'heading', level: 2, text: '执行摘要' },
    { type: 'paragraph', text: summary }
  ]
  const sections = recordList(value.sections)
  sections.forEach(section => {
    const title = firstText(section, ['title', 'name']) || '结果章节'
    const content = firstText(section, ['content', 'summary', 'description'])
    if (content) blocks.push({ type: 'heading', level: 3, text: title }, { type: 'paragraph', text: content })
  })
  return documentModel(entry, 'final_report', summary, blocks, value)
}

const genericValue = (value: unknown, depth = 0, path = 'output'): ArtifactDocumentBlockDraft[] => {
  // Fallback only: known schemas must be handled by a dedicated projector above.
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return [{ type: 'paragraph', text: text(value) }]
  }
  if (Array.isArray(value)) {
    if (value.every(item => item == null || ['string', 'number', 'boolean'].includes(typeof item))) {
      return [{ type: 'list', items: value.map(item => item == null ? 'null' : text(item)).filter(Boolean) }]
    }
    return value.flatMap((item, index) => {
      const blockId = `${path}-${index + 1}`
      const title = isRecord(item) ? firstText(item, ['title', 'name', 'id']) : ''
      return [
        { blockId, type: 'heading' as const, level: 3 as const, text: title || `条目 ${index + 1}` },
        ...genericValue(item, depth + 1, blockId)
      ]
    })
  }
  if (!isRecord(value)) return []
  return Object.entries(value).flatMap(([key, item]) => {
    const blockId = `${path}-${key}`
    const heading = { blockId, type: 'heading' as const, level: depth > 0 ? 3 as const : 2 as const, text: key.replace(/[_-]+/g, ' ') }
    const nested = genericValue(item, depth + 1, blockId)
    return [heading, ...nested]
  })
}

const genericProjector = (entry: WorkspaceEntry, value: unknown): ArtifactDocumentModel => {
  const blocks = genericValue(value)
  const summary = entry.objective?.trim() || '当前 Artifact 没有已知 schema，以下内容为受限 fallback 投影。'
  return documentModel(entry, 'unknown', summary, blocks.length ? blocks : [{ type: 'paragraph', text: summary }], isRecord(value) ? value : {})
}

const unique = (values: string[]) => [...new Set(values.map(item => item.trim()).filter(Boolean))]

const inspectorFrom = (entry: WorkspaceEntry, artifacts: WorkspaceEntry[], value: unknown, artifactKind: ArtifactKind): ArtifactInspectorProjection => {
  const output = isRecord(value) ? value : {}
  const nestedRecords = Object.values(output).flatMap(item => recordList(item))
  const metadata = entry.metadata || {}
  const artifactMetadata = artifacts.flatMap(item => isRecord(item.metadata) ? [item.metadata] : [])
  const refs = [
    ...list(output.evidence_refs), ...list(output.evidenceRefs), text(output.evidence_ref), text(output.evidenceRef),
    ...nestedRecords.flatMap(item => [text(item.evidence_ref), text(item.evidenceRef), ...list(item.evidence_refs), ...list(item.evidenceRefs)]),
    ...list(metadata.evidenceRefs), ...list(metadata.evidence_refs),
    ...artifactMetadata.flatMap(item => [...list(item.evidenceRefs), ...list(item.evidence_refs)])
  ]
  const upstreamInputs = [
    ...(entry.dependencyKeys || []), ...list(metadata.upstreamInputs), ...list(metadata.sourceStepIds),
    ...artifactMetadata.flatMap(item => [...list(item.upstreamInputs), ...list(item.sourceStepIds)])
  ]
  const traceLinks = [
    text(metadata.outputRef), ...list(metadata.traceLinks), ...list(metadata.traceRefs),
    ...artifactMetadata.flatMap(item => [...list(item.traceLinks), ...list(item.traceRefs)])
  ]
  const provenanceCandidates: Array<[string, string | null | undefined, boolean]> = [
    [ 'Artifact ID', entry.artifactId || artifacts[0]?.artifactId, true ],
    [ 'Content ref', entry.contentRef || artifacts[0]?.contentRef, true ],
    [ 'Attempt ID', entry.latestAttemptId || entry.attemptId || artifacts[0]?.attemptId, true ],
    [ 'Source Run', entry.sourceRunId || artifacts[0]?.sourceRunId, true ],
    [ 'Checksum', entry.checksum || artifacts[0]?.checksum, true ]
  ]
  const provenance: Array<{ label: string; value: string; code?: boolean }> = provenanceCandidates
    .flatMap(([label, value, code]) => value ? [{ label, value: String(value), code }] : [])
  return {
    artifactKind,
    artifactType: entry.artifactType || artifacts[0]?.artifactType || null,
    evidenceRefs: unique(refs),
    confidence: firstText(output, ['confidence', 'confidenceScore'])
      || firstText(nestedRecords[0] || {}, ['confidence', 'confidenceScore'])
      || text(metadata.confidence) || null,
    upstreamInputs: unique(upstreamInputs),
    provenance,
    traceLinks: unique(traceLinks)
  }
}

const headingBlockId = (heading: Extract<ArtifactDocumentBlockShape, { type: 'heading' }>, index: number): string => {
  const requirement = heading.text.match(/^(REQ-[A-Za-z0-9_-]+)/i)
  if (requirement) return requirement[1].toLowerCase()

  const knownIds: Record<string, string> = {
    '需求与验收标准': 'intro',
    '证据评估': 'intro',
    '方案比较': 'intro',
    '执行摘要': 'intro',
    'Requirement Acceptance Matrix': 'acceptance-matrix',
    '前提假设': 'assumptions',
    '待确认事项': 'open-questions'
  }
  if (knownIds[heading.text]) return knownIds[heading.text]

  const slug = heading.text
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\u0080-\uffff]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return `${heading.level === 2 ? 'section' : 'block'}-${slug || String(index + 1).padStart(2, '0')}`
}

const normalizeBlocks = (blocks: ArtifactDocumentBlockDraft[]): ArtifactDocumentBlock[] => {
  let previousBlockId: string | null = null
  return blocks.map((block, index) => {
    const blockId = block.blockId
      || (block.type === 'heading' ? headingBlockId(block, index) : previousBlockId)
      || `block-${String(index + 1).padStart(2, '0')}`
    const normalized = {
      ...block,
      blockId,
      gutter: block.gutter ?? blockId !== previousBlockId
    } as ArtifactDocumentBlock
    previousBlockId = blockId
    return normalized
  })
}

const documentModel = (entry: WorkspaceEntry, artifactKind: ArtifactKind, summary: string, blocks: ArtifactDocumentBlockDraft[], value: JsonRecord): ArtifactDocumentModel => ({
  artifactKind,
  kindLabel: KIND_LABELS[artifactKind],
  title: entry.title || entry.name,
  summary,
  blocks: normalizeBlocks(blocks),
  inspector: inspectorFrom(entry, [], value, artifactKind)
})

export const renderArtifactDocument = (model: ArtifactDocumentModel): string => model.blocks.map(block => {
  if (block.type === 'heading') return `${'#'.repeat(block.level)} ${block.text}`
  if (block.type === 'paragraph') return block.label ? `**${block.label}**\n\n${block.text}` : block.text
  if (block.type === 'callout') return `> **${block.label || '提示'}** ${block.text}`
  if (block.type === 'list') return block.items.map((item, index) => `${block.ordered ? `${index + 1}.` : '-'} ${item}`).join('\n')
  return [
    `| ${block.columns.join(' | ')} |`,
    `| ${block.columns.map(() => '---').join(' | ')} |`,
    ...block.rows.map(row => `| ${block.columns.map((_, index) => row[index] || '—').join(' | ')} |`)
  ].join('\n')
}).join('\n\n')

export const projectArtifactDocument = (input: ArtifactProjectionInput): ArtifactDocumentModel => {
  const value = unwrapOutput(parseOutput(input.output))
  const kind = resolveArtifactKind(input.entry, value)
  const base = isRecord(value) ? value : {}
  const model = kind === 'requirements_specification'
    ? requirementsProjector(input.entry, base)
    : kind === 'evidence_assessment'
      ? evidenceProjector(input.entry, base)
      : kind === 'comparison_report'
        ? comparisonProjector(input.entry, base)
        : kind === 'final_report'
          ? finalReportProjector(input.entry, base)
          : genericProjector(input.entry, value)
  return {
    ...model,
    inspector: inspectorFrom(input.entry, input.artifacts || [], base, kind)
  }
}
