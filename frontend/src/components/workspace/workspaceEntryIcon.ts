import type { Component } from 'vue'
import { Clock, Document, Files, FolderOpened, Odometer, Share } from '@element-plus/icons-vue'
import type { WorkspaceEntryKind } from '@/services/api/agentos'

const WORKSPACE_ENTRY_ICONS: Record<WorkspaceEntryKind, Component> = {
  folder: FolderOpened,
  graph: Share,
  virtual_document: Document,
  task: Document,
  artifact: Files,
  run: Clock,
  progress: Odometer
}

export const workspaceEntryIcon = (kind: WorkspaceEntryKind): Component => WORKSPACE_ENTRY_ICONS[kind]
