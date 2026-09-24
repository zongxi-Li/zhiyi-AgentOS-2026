import type { WorkspaceFileEntry } from '@/services/api/agentos'

export interface WorkspaceFileTreeItem extends WorkspaceFileEntry {
  expanded: boolean
  loaded: boolean
  loading: boolean
  error: string
  children: WorkspaceFileTreeItem[]
  visibleChildren: WorkspaceFileTreeItem[]
}

export interface WorkspaceFileVisibleTreeItem extends WorkspaceFileTreeItem {
  source: WorkspaceFileTreeItem
  visibleChildren: WorkspaceFileVisibleTreeItem[]
}
