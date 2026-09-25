import { agentosRequest } from '../client'
import type { ArtifactContentResponse, ArtifactDetail, RunOutputResponse } from '../types'
import { runPath } from '../paths'
import type { ArtifactApiDependencies } from '../dependencies'

const readBlobText = async (blob: Blob): Promise<string> => {
  if (typeof blob.text === 'function') return blob.text()
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(reader.error || new Error('Unable to read artifact response'))
    reader.readAsText(blob)
  })
}

export const createArtifactsApi = (getApi: () => ArtifactApiDependencies) => ({
  async getRunOutput(
    runId: string,
    outputRef: string,
    options: { signal?: AbortSignal } = {}
  ): Promise<RunOutputResponse> {
    const response = await agentosRequest.get<RunOutputResponse>(
      `${runPath(runId)}/outputs/${encodeURIComponent(outputRef)}`,
      { signal: options.signal }
    )
    return response.data
  },

  async getArtifactDetail(
    runId: string,
    contentRef: string,
    options: { signal?: AbortSignal } = {}
  ): Promise<ArtifactDetail> {
    const response = await agentosRequest.get<ArtifactDetail>(
      `${runPath(runId)}/artifacts/${encodeURIComponent(contentRef)}`,
      { signal: options.signal }
    )
    return response.data
  },

  async getArtifactContent(
    runId: string,
    contentRef: string,
    options: { signal?: AbortSignal } = {}
  ): Promise<ArtifactContentResponse> {
    // Sealed artifacts already expose a verified streaming assembly endpoint.
    // Reading that stream avoids one JSON request per fragment page and keeps
    // large documents from being copied into several intermediate arrays.
    const blob = await getApi().downloadArtifact(runId, contentRef, options)
    return {
      manifestId: contentRef,
      mediaType: blob.type || 'application/octet-stream',
      byteLength: blob.size,
      content: await readBlobText(blob)
    }
  },

  async downloadArtifact(
    runId: string,
    contentRef: string,
    options: { signal?: AbortSignal } = {}
  ): Promise<Blob> {
    const response = await agentosRequest.get<Blob>(
      `${runPath(runId)}/artifacts/${encodeURIComponent(contentRef)}/download`,
      { responseType: 'blob', signal: options.signal }
    )
    return response.data
  }
})
