import { getElectronBridge, type WorkspaceSearchResult } from '@/platform/electron/bridge'

export type { WorkspaceSearchMatch, WorkspaceSearchResult } from '@/platform/electron/bridge'

export interface WorkspaceSearchOptions {
  query: string
  caseSensitive?: boolean
  maxResults?: number
}

/**
 * 工作区全文搜索：只有桌面宿主提供原生搜索（ripgrep），
 * Web 构建没有本地文件系统，调用会明确失败而不是悄悄返回空结果。
 */
export async function searchWorkspace(root: string, options: WorkspaceSearchOptions): Promise<WorkspaceSearchResult> {
  const search = getElectronBridge()?.workspace?.search
  if (!search) throw new Error('全文搜索仅在桌面端可用')
  return search(root, options)
}
