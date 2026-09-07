<template>
  <main class="editor-group" aria-label="Workspace editor">
    <nav class="editor-tabs" aria-label="Open editors" role="tablist">
      <div class="editor-tabs__scroll">
        <button
          v-if="sidebarHidden"
          class="editor-navigator-trigger"
          type="button"
          aria-label="唤醒项目导航"
          title="唤醒项目导航（窗口放不下时会让出右侧详情的空间）"
          @click="emit('restoreSidebar')"
        >
          <span class="editor-navigator-trigger__mark" aria-hidden="true">
            <el-icon><Expand /></el-icon>
          </span>
        </button>
        <div v-for="opened in openEntries" :key="opened.entry.entryId" class="editor-tab" :class="{ 'is-active': opened.entry.entryId === activeEditorId }">
          <button class="editor-tab__main" type="button" role="tab" :aria-selected="opened.entry.entryId === activeEditorId" @click="emit('activate', opened.entry.entryId)">
            <span v-if="tabStatusMark(opened.entry)" class="editor-tab__status" :class="'is-' + tabStatus(opened.entry)" aria-hidden="true">{{ tabStatusMark(opened.entry) }}</span>
            <span class="editor-tab__kind" aria-hidden="true">
              <el-icon><component :is="workspaceEntryIcon(opened.entry.kind)" /></el-icon>
            </span>
            <span class="editor-tab__name">{{ editorTitle(opened.entry) }}</span>
            <span v-if="!opened.available" class="editor-tab__missing">missing</span>
          </button>
          <button class="editor-tab__close" type="button" :aria-label="`关闭 ${opened.entry.name}`" :title="`关闭 ${opened.entry.name}`" @click="emit('close', opened.entry.entryId)">×</button>
        </div>
        <span v-if="!openEntries.length" class="editor-tabs__empty">从 Explorer 打开一个文件</span>
      </div>
      <div class="editor-tabs__actions">
        <button
          class="editor-inspector-trigger"
          type="button"
          :class="{
            'is-active': inspectorVisible,
            'is-unavailable': inspectorAutoHidden
          }"
          :aria-pressed="inspectorVisible"
          :aria-label="inspectorVisible ? '收起 Inspector' : '唤醒 Inspector'"
          :title="inspectorVisible
            ? '收起 Inspector'
            : (inspectorAutoHidden ? '唤醒 Inspector（当前窗口空间不足时会自动隐藏）' : '唤醒 Inspector')"
          @click="toggleInspector"
        >
          <span class="editor-inspector-trigger__mark" aria-hidden="true">
            <el-icon><View /></el-icon>
          </span>
        </button>
      </div>
    </nav>

    <section class="editor-group__surface" :class="{ 'editor-group__surface--task': activeOpened?.entry.kind === 'task' }">
      <component
        v-if="activeOpened && editorContribution"
        :is="editorContribution.component"
        :key="editorKey"
        :entry="activeOpened.entry"
        :projection="projection"
        :graph="projection.activeGraph || null"
        :graph-nodes="projection.graphNodes"
        :selected-semantic-task-key="selectedSemanticTaskKey"
        :selected-symbol-id="selectedSymbolId"
        :focus-node-id="focusNodeId"
        :run-id="projection.activeRun?.runId || null"
        :run-status="projection.activeRun?.status || null"
        :cancel-pending="cancelPending"
        :available="activeOpened.available"
        :runtime-observation="workbenchContext.runtimeObservation"
        :runtime-store="props.runtimeStore"
        @select-semantic-task="emit('selectSemanticTask', $event)"
        @select-symbol="emit('selectSymbol', $event)"
        @open-semantic-task="emit('openSemanticTask', $event)"
        @locate-graph="emit('locateGraph', $event || activeOpened.entry)"
        @open-artifact="emit('openArtifact', $event)"
        @open-entry="emit('openEntry', $event)"
        @cancel-run="emit('cancelRun')"
      />
      <div v-else class="editor-group__empty">该 entry 类型暂不支持编辑器渲染。</div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Expand, View } from '@element-plus/icons-vue'
import type { MissionWorkspaceProjection, WorkspaceEntry } from '@/services/api/agentos'
import type { WorkbenchContext } from '@/workbench/types'
import type { WorkbenchContributionRegistry } from '@/workbench/registry'
import type { RuntimeEventStore } from '@/workbench/runtime/runtimeEvents'
import type { RunDocumentSymbol } from '@/workbench/runtime/runDocument'
import { workspaceEntryIcon } from './workspaceEntryIcon'

export interface OpenWorkspaceEntry {
  entry: WorkspaceEntry
  available: boolean
}

const props = defineProps<{
  projection: MissionWorkspaceProjection
  openEntries: OpenWorkspaceEntry[]
  activeEditorId: string | null
  selectedSemanticTaskKey: string | null
  selectedSymbolId?: string | null
  focusNodeId: string | null
  registry: WorkbenchContributionRegistry
  workbenchContext: WorkbenchContext
  inspectorVisible: boolean
  inspectorAutoHidden: boolean
  toggleInspector: () => void
  sidebarHidden?: boolean
  cancelPending?: boolean
  runtimeStore?: RuntimeEventStore | null
}>()

const emit = defineEmits<{
  activate: [entryId: string]
  close: [entryId: string]
  selectSemanticTask: [semanticTaskKey: string | null]
  selectSymbol: [symbol: RunDocumentSymbol]
  openSemanticTask: [semanticTaskKey: string | null]
  locateGraph: [entry: WorkspaceEntry]
  openArtifact: [entry: WorkspaceEntry]
  openEntry: [entry: WorkspaceEntry]
  restoreSidebar: []
  cancelRun: []
}>()

const activeOpened = computed(() => props.openEntries.find(item => item.entry.entryId === props.activeEditorId))
const editorContribution = computed(() => props.registry.resolveEditor(activeOpened.value?.entry || null, props.workbenchContext))
const editorKey = computed(() => {
  if (!activeOpened.value) return 'empty'
  return `${activeOpened.value.entry.entryId}:${activeOpened.value.entry.artifactId || 'entry'}:${props.projection.activeRun?.runId || 'none'}`
})

const editorTitle = (entry: WorkspaceEntry) => (
  props.registry.resolveEditor(entry, props.workbenchContext)?.title?.(entry, props.workbenchContext) || entry.name
)

// Run / Progress 标签的运行状态符号：● 运行中 ✓ 成功 × 失败
const TAB_RUNNING = new Set(['running', 'pending', 'planning', 'retrying'])
const TAB_OK = new Set(['completed', 'succeeded'])
const TAB_BAD = new Set(['failed', 'cancelled'])
const tabStatus = (entry: WorkspaceEntry) => {
  const status = entry.kind === 'run'
    ? entry.status
    : entry.kind === 'progress'
      ? props.workbenchContext.runtimeObservation?.runStatus
      : null
  if (!status) return 'idle'
  if (TAB_OK.has(status)) return 'success'
  if (TAB_BAD.has(status)) return 'failed'
  if (TAB_RUNNING.has(status)) return 'running'
  return 'idle'
}
const tabStatusMark = (entry: WorkspaceEntry) => {
  const state = tabStatus(entry)
  return state === 'running' ? '●' : state === 'success' ? '✓' : state === 'failed' ? '×' : null
}

</script>

<style scoped>
.editor-group { display: flex; flex-direction: column; width: 100%; height: 100%; min-width: 0; min-height: 0; color: var(--wb-text); background: var(--wb-surface-shell); }
.editor-tabs { display: flex; align-items: stretch; min-height: var(--wb-tab-height); overflow: hidden; border-bottom: 1px solid var(--wb-border); background: var(--wb-surface-inset); }
.editor-tabs__scroll { display: flex; flex: 1 1 auto; align-items: stretch; min-width: 0; overflow-x: auto; scrollbar-width: thin; scrollbar-color: var(--wb-border-strong) transparent; }
.editor-tabs__actions { display: flex; flex: 0 0 38px; align-items: stretch; min-width: 38px; border-left: 1px solid var(--wb-border-soft); background: var(--wb-surface-inset); }
.editor-tab { display: flex; align-items: stretch; width: 220px; min-width: 180px; flex: 0 1 220px; box-sizing: border-box; border-top: 2px solid transparent; border-radius: 7px 7px 0 0; transition: background-color 140ms var(--ease-out), border-color 140ms var(--ease-out); }
.editor-tab.is-active { border-top-color: var(--wb-accent); background: color-mix(in srgb, var(--wb-surface-2) 82%, var(--wb-accent)); }
.editor-tab__main, .editor-tab__close { border: 0; color: var(--wb-text-secondary); background: transparent; cursor: pointer; }
.editor-tab__main { display: flex; flex: 1 1 auto; align-items: center; gap: 7px; min-width: 0; width: 0; max-width: none; padding: 0 5px 0 11px; font-size: 11px; }
.editor-tab__main:hover, .editor-tab.is-active .editor-tab__main { color: var(--wb-text); }
.editor-tab__main:focus-visible, .editor-tab__close:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: -2px; }
.editor-tab__kind { display: inline-flex; align-items: center; justify-content: center; width: 15px; min-width: 15px; color: var(--wb-accent); font: 12px var(--font-mono, monospace); }
.editor-tab__kind .el-icon { font-size: 14px; }
.editor-tab__status { flex: 0 0 auto; color: var(--wb-accent); font-size: 10px; }
.editor-tab__status.is-success { color: var(--wb-success); }
.editor-tab__status.is-failed { color: var(--wb-danger); }
.editor-tab__name { min-width: 0; flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.editor-tab__missing { color: var(--wb-warning); font: 9px var(--font-mono, monospace); }
.editor-tab__close { width: 28px; min-width: 28px; flex: 0 0 28px; color: var(--wb-text-muted); font-size: 15px; opacity: 0; transition: opacity 140ms var(--ease-out), color 140ms var(--ease-out), background-color 140ms var(--ease-out); }
.editor-tab:hover .editor-tab__close, .editor-tab.is-active .editor-tab__close, .editor-tab__close:focus-visible { opacity: 1; }
.editor-tab__close:hover { color: var(--wb-danger); background: var(--wb-hover); }
.editor-tabs__empty { align-self: center; padding: 0 14px; color: var(--wb-text-muted); font-size: 11px; }
.editor-tabs__scroll::-webkit-scrollbar { height: 4px; }
.editor-tabs__scroll::-webkit-scrollbar-thumb { background: var(--wb-border-strong); }
.editor-navigator-trigger {
  position: sticky;
  left: 0;
  z-index: 1;
  display: grid;
  flex: 0 0 38px;
  place-items: center;
  width: 38px;
  min-width: 38px;
  min-height: var(--wb-tab-height);
  padding: 0 6px;
  border: 0;
  border-right: 1px solid var(--wb-border-soft);
  color: var(--wb-text-muted);
  background: var(--wb-surface-inset);
  cursor: pointer;
}
.editor-navigator-trigger__mark {
  display: grid;
  width: 23px;
  height: 23px;
  place-items: center;
  border: 1px solid transparent;
  border-radius: 6px;
  font-size: 15px;
  transition: background-color 140ms var(--ease-out), border-color 140ms var(--ease-out), color 140ms var(--ease-out);
}
.editor-navigator-trigger:hover .editor-navigator-trigger__mark,
.editor-navigator-trigger:focus-visible .editor-navigator-trigger__mark {
  border-color: color-mix(in srgb, var(--wb-accent) 24%, var(--wb-border));
  color: var(--wb-accent);
  background: var(--wb-hover);
}
.editor-navigator-trigger:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: -2px; }
.editor-inspector-trigger {
  z-index: 1;
  display: grid;
  flex: 1 1 auto;
  place-items: center;
  width: 38px;
  min-height: var(--wb-tab-height);
  padding: 0 6px;
  border: 0;
  color: var(--wb-text-muted);
  background: var(--wb-surface-inset);
  cursor: pointer;
}
.editor-inspector-trigger__mark {
  display: grid;
  width: 23px;
  height: 23px;
  place-items: center;
  border: 1px solid transparent;
  border-radius: 6px;
  font-size: 15px;
  transition: background-color 140ms var(--ease-out), border-color 140ms var(--ease-out), color 140ms var(--ease-out), box-shadow 140ms var(--ease-out);
}
.editor-inspector-trigger:hover .editor-inspector-trigger__mark,
.editor-inspector-trigger:focus-visible .editor-inspector-trigger__mark {
  border-color: color-mix(in srgb, var(--wb-accent) 24%, var(--wb-border));
  color: var(--wb-accent);
  background: var(--wb-hover);
}
.editor-inspector-trigger.is-active .editor-inspector-trigger__mark {
  border-color: color-mix(in srgb, var(--wb-accent) 28%, var(--wb-border));
  color: var(--wb-accent);
  background: var(--wb-active);
  box-shadow: 0 1px 2px color-mix(in srgb, var(--wb-accent) 10%, transparent);
}
.editor-inspector-trigger.is-unavailable .editor-inspector-trigger__mark { opacity: .72; }
.editor-inspector-trigger:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: -2px; }
.editor-group__surface { display: flex; flex: 1; min-width: 0; min-height: 0; overflow: hidden; padding: 10px 12px 12px; background: var(--wb-surface-shell); }
.editor-group__surface--task { padding: 0; }
.editor-group__empty { display: grid; place-items: center; height: 100%; color: var(--wb-text-muted); font-size: 12px; }

</style>
