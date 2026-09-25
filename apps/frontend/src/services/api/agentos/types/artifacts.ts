export type InputAttachmentStatus = 'UPLOADED' | 'PARSING' | 'READY' | 'FAILED'
export interface InputAttachment {
  attachmentId: string
  originalFilename: string
  filename?: string
  mimeType: string
  extension: string
  sizeBytes: number
  sha256: string
  status: InputAttachmentStatus
  extractedContentRef?: string | null
  characterCount: number
  parser?: string | null
  metadata?: Record<string, unknown>
  parseError?: string | null
  errorCode?: string | null
  createdAt: string
  updatedAt: string
}
export interface ArtifactDetail {
  manifestId: string
  artifactId?: string
  missionId?: string
  originRunId?: string
  taskId?: string
  semanticTaskKey?: string
  artifactKey?: string
  acgNodeId?: string
  producerAttemptId?: string
  name?: string
  artifactType?: string
  mediaType: string
  contentRef?: string
  checksum?: string | null
  byteLength?: number
  fragmentCount?: number
  sealed?: boolean
  createdAt?: string
  metadata?: Record<string, unknown>
}
export interface ArtifactFragment {
  fragmentId?: string
  ordinal?: number
  content: string
}
export interface ArtifactContentResponse extends ArtifactDetail {
  content: string
}
export interface RunOutputResponse {
  runId: string
  outputRef: string
  content: unknown
}
