import type { AcgDeliverable } from '@/services/api/workflow'

type AnyRecord = Record<string, any>

export interface ContractRiskItem {
  id?: string
  title?: string
  level?: string
  clause?: string
  reason?: string
  consequence?: string
  suggestion?: string
  evidenceIds?: string[]
  [key: string]: any
}

export interface ContractEvidenceItem {
  id?: string
  riskId?: string
  stepId?: string
  sourceType?: string
  sourceName?: string
  title?: string
  content?: string
  citationText?: string
  chunkId?: string
  confidence?: number
  retrievalScore?: number
  metadata?: Record<string, any>
  [key: string]: any
}

export interface ContractReviewArtifacts {
  risks: ContractRiskItem[]
  evidences: ContractEvidenceItem[]
  reportMarkdown: string
  riskSummary: AnyRecord | null
  revisionSuggestions: AnyRecord[]
  contractInfo: AnyRecord | null
  paths: {
    risks: string
    evidences: string
    reportMarkdown: string
  }
}

const ARTIFACT_PATHS = {
  risks: 'output.artifacts.risk_detect.risks',
  evidences: 'output.artifacts.legal_evidence_match.evidences',
  reportMarkdown: 'output.artifacts.report_generate.report_markdown'
}

const asRecord = (value: unknown): AnyRecord => {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as AnyRecord : {}
}

const asArray = <T = AnyRecord>(value: unknown): T[] => {
  return Array.isArray(value) ? value as T[] : []
}

const asString = (value: unknown): string => {
  return typeof value === 'string' ? value : ''
}

const stepOutput = (deliverables: AcgDeliverable[] | undefined, stepId: string): AnyRecord => {
  return asRecord(deliverables?.find(item => item.stepId === stepId)?.output)
}

export const extractContractReviewArtifacts = (deliverables: AcgDeliverable[] = []): ContractReviewArtifacts => {
  const riskDetect = {
    ...stepOutput(deliverables, 'risk_detect')
  }
  const evidenceMatch = {
    ...stepOutput(deliverables, 'legal_evidence_match')
  }
  const revisionSuggest = {
    ...stepOutput(deliverables, 'revision_suggest'),
    ...stepOutput(deliverables, 'suggestion_generate')
  }
  const humanReview = {
    ...stepOutput(deliverables, 'human_review')
  }
  const reportGenerate = {
    ...stepOutput(deliverables, 'report_generate')
  }
  const report = asRecord(reportGenerate.report)

  const risks =
    asArray<ContractRiskItem>(riskDetect.risks).length
      ? asArray<ContractRiskItem>(riskDetect.risks)
      : asArray<ContractRiskItem>(humanReview.risks).length
        ? asArray<ContractRiskItem>(humanReview.risks)
        : asArray<ContractRiskItem>(report.riskItems)

  const evidences =
    asArray<ContractEvidenceItem>(evidenceMatch.evidences).length
      ? asArray<ContractEvidenceItem>(evidenceMatch.evidences)
      : asArray<ContractEvidenceItem>(report.evidenceAppendix)

  return {
    risks,
    evidences,
    reportMarkdown: asString(reportGenerate.report_markdown) || asString(reportGenerate.reportMarkdown),
    riskSummary: Object.keys(asRecord(riskDetect.risk_summary)).length ? asRecord(riskDetect.risk_summary) : asRecord(report.riskSummary),
    revisionSuggestions: asArray<AnyRecord>(revisionSuggest.revision_suggestions).length
      ? asArray<AnyRecord>(revisionSuggest.revision_suggestions)
      : asArray<AnyRecord>(report.revisionSuggestions),
    contractInfo: Object.keys(asRecord(report.contractInfo)).length ? asRecord(report.contractInfo) : null,
    paths: ARTIFACT_PATHS
  }
}
