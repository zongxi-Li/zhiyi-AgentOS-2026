<template>
  <main class="editor-group" aria-label="Workspace editor">
    <header class="editor-group__toolbar">
      <div class="editor-group__context">
        <span class="editor-group__product">MISSION WORKSPACE</span>
        <strong>{{ projection.mission.goal }}</strong>
      </div>
      <div class="editor-group__run">
        <span v-if="projection.activeRun">Run {{ projection.activeRun.runId }}</span>
        <span v-else>No Run</span>
        <b v-if="projection.activeRun && isHistorical">Historical / Read-only</b>
        <b v-else>Read-only</b>
      </div>
    </header>

    <nav class="editor-tabs" aria-label="Open editors" role="tablist">
      <div v-for="opened in openEntries" :key="opened.entry.entryId" class="editor-tab" :class="{ 'is-active': opened.entry.entryId === activeEditorId }">
        <button class="editor-tab__main" type="button" role="tab" :aria-selected="opened.entry.entryId === activeEditorId" @click="emit('activate', opened.entry.entryId)">
          <span class="editor-tab__kind" aria-hidden="true">{{ tabMark(opened.entry.kind) }}</span>
          <span class="editor-tab__name">{{ opened.entry.name }}</span>
          <span v-if="!opened.available" class="editor-tab__missing">missing</span>
        </button>
        <button class="editor-tab__close" type="button" :aria-label="`关闭 ${opened.entry.name}`" :title="`关闭 ${opened.entry.name}`" @click="emit('close', opened.entry.entryId)">×</button>
      </div>
      <span v-if="!openEntries.length" class="editor-tabs__empty">从 Explorer 打开一个文件</span>
    </nav>

    <section class="editor-group__surface">
      <GraphEditor
        v-if="activeOpened?.entry.kind === 'graph'"
        :key="activeOpened.entry.entryId"
        :graph="projection.activeGraph || null"
        :graph-nodes="projection.graphNodes"
        :selected-semantic-task-key="selectedSemanticTaskKey"
        :focus-node-id="focusNodeId"
        @select-semantic-task="emit('selectSemanticTask', $event)"
        @open-semantic-task="emit('openSemanticTask', $event)"
      />
      <ArtifactEditor
        v-else-if="activeOpened?.entry.kind === 'artifact'"
        :key="`${activeOpened.entry.entryId}:${activeOpened.entry.artifactId || 'missing'}:${projection.activeRun?.runId || 'none'}`"
        :entry="activeOpened.entry"
        :run-id="projection.activeRun?.runId || null"
        :available="activeOpened.available"
        @locate-graph="emit('locateGraph', activeOpened.entry)"
      />
      <MissionEditor
        v-else-if="activeOpened?.entry.kind === 'virtual_document'"
        :projection="projection"
        :entry="activeOpened.entry"
      />
      <div v-else class="editor-group__empty">该 entry 类型暂不支持编辑器渲染。</div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import ArtifactEditor from './ArtifactEditor.vue'
import GraphEditor from './GraphEditor.vue'
import MissionEditor from './MissionEditor.vue'
import type { MissionWorkspaceProjection, WorkspaceEntry, WorkspaceEntryKind } from '@/services/api/agentos'

export interface OpenWorkspaceEntry {
  entry: WorkspaceEntry
  available: boolean
}

const props = defineProps<{
  projection: MissionWorkspaceProjection
  openEntries: OpenWorkspaceEntry[]
  activeEditorId: string | null
  selectedSemanticTaskKey: string | null
  focusNodeId: string | null
  isHistorical: boolean
}>()

const emit = defineEmits<{
  activate: [entryId: string]
  close: [entryId: string]
  selectSemanticTask: [semanticTaskKey: string | null]
  openSemanticTask: [semanticTaskKey: string | null]
  locateGraph: [entry: WorkspaceEntry]
}>()

const activeOpened = computed(() => props.openEntries.find(item => item.entry.entryId === props.activeEditorId))

const tabMark = (kind: WorkspaceEntryKind) => ({ graph: '◇', virtual_document: 'M', artifact: '·', folder: '▾', run: 'R' }[kind])
</script>

<style scoped>
.editor-group { display: flex; flex-direction: column; width: 100%; height: 100%; min-width: 0; min-height: 0; color: var(--text-primary); background: var(--bg-card); }
.editor-group__toolbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; min-height: 52px; padding: 8px 18px; border-bottom: 1px solid var(--border-light); }
.editor-group__context { min-width: 0; }
.editor-group__product { display: block; color: var(--primary-color); font: 10px var(--font-mono, monospace); letter-spacing: .08em; }
.editor-group__context strong { display: block; margin-top: 3px; overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.editor-group__run { display: flex; align-items: center; gap: 10px; color: var(--text-secondary); font: 10px var(--font-mono, monospace); white-space: nowrap; }
.editor-group__run b { color: var(--warning); font-weight: 500; }
.editor-group__run b:last-child { color: var(--text-muted); }
.editor-tabs { display: flex; align-items: stretch; min-height: 36px; overflow-x: auto; border-bottom: 1px solid var(--border-light); background: var(--bg-input); scrollbar-width: thin; }
.editor-tab { display: flex; align-items: stretch; flex: 0 0 auto; border-right: 1px solid var(--border-light); border-top: 2px solid transparent; }
.editor-tab.is-active { border-top-color: var(--primary-color); background: var(--bg-card); }
.editor-tab__main, .editor-tab__close { border: 0; color: var(--text-secondary); background: transparent; cursor: pointer; }
.editor-tab__main { display: flex; align-items: center; gap: 7px; min-width: 0; max-width: 230px; padding: 0 5px 0 11px; font-size: 11px; }
.editor-tab__main:hover, .editor-tab.is-active .editor-tab__main { color: var(--text-primary); }
.editor-tab__kind { color: var(--primary-color); font: 12px var(--font-mono, monospace); }
.editor-tab__name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.editor-tab__missing { color: var(--warning); font: 9px var(--font-mono, monospace); }
.editor-tab__close { width: 28px; color: var(--text-muted); font-size: 17px; }
.editor-tab__close:hover { color: var(--danger); background: var(--bg-input); }
.editor-tabs__empty { align-self: center; padding: 0 14px; color: var(--text-muted); font-size: 11px; }
.editor-group__surface { display: flex; flex: 1; min-width: 0; min-height: 0; overflow: hidden; }
.editor-group__empty { display: grid; place-items: center; height: 100%; color: var(--text-muted); font-size: 12px; }

@media (max-width: 720px) {
  .editor-group__toolbar { align-items: flex-start; flex-direction: column; gap: 4px; padding: 10px 12px; }
  .editor-group__run { width: 100%; justify-content: space-between; }
}
</style>
