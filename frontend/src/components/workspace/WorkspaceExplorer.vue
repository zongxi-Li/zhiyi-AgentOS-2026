<template>
  <aside class="workspace-explorer" aria-label="Mission Project Explorer">
    <header class="workspace-explorer__header">
      <div class="workspace-explorer__title-row">
        <span class="workspace-explorer__mark" aria-hidden="true"><el-icon><FolderOpened /></el-icon></span>
        <div>
          <strong>{{ projection.mission.goal }}</strong>
          <small>Mission Project</small>
        </div>
      </div>
      <code class="workspace-explorer__mission-id" :title="projection.mission.missionId">{{ projection.mission.missionId }}</code>
    </header>

    <div v-if="projection.diagnostics.length" class="workspace-explorer__diagnostics" aria-label="Workspace diagnostics">
      <article v-for="diagnostic in projection.diagnostics" :key="`${diagnostic.code}-${diagnostic.message}`" :class="`diagnostic diagnostic--${diagnostic.severity}`">
        <el-icon><WarningFilled /></el-icon>
        <div>
          <strong>{{ diagnostic.code }}</strong>
          <span>{{ diagnostic.message }}</span>
        </div>
      </article>
    </div>

    <nav class="workspace-tree" aria-label="Project files">
      <section v-for="section in sections" :key="section.group" class="workspace-tree__section">
        <button class="workspace-tree__section-toggle" type="button" :aria-expanded="isExpanded(section.group)" @click="toggleSection(section.group)">
          <el-icon><ArrowDown v-if="isExpanded(section.group)" /><ArrowRight v-else /></el-icon>
          <span>{{ section.label }}</span>
          <small v-if="section.items.length">{{ section.items.length }}</small>
        </button>
        <div v-if="isExpanded(section.group)" class="workspace-tree__items">
          <button
            v-for="entry in section.items"
            :key="entry.entryId"
            type="button"
            class="workspace-tree__entry"
            :class="{
              'is-active': entry.entryId === activeEditorId,
              'is-current-run': entry.kind === 'run' && entry.runId === selectedRunId,
              'is-legacy': entry.identityQuality === 'legacy'
            }"
            :title="entry.name"
            @click="handleEntryClick(entry)"
          >
            <el-icon class="workspace-tree__entry-icon"><component :is="entryIcon(entry)" /></el-icon>
            <span class="workspace-tree__entry-name">{{ entry.name }}</span>
            <span v-if="entry.kind === 'run'" class="workspace-tree__run-state">{{ runLabel(entry.status) }}</span>
            <span v-else-if="entry.identityQuality === 'legacy'" class="workspace-tree__legacy">legacy</span>
          </button>
          <p v-if="!section.items.length" class="workspace-tree__empty">{{ section.empty }}</p>
        </div>
      </section>
    </nav>

    <footer class="workspace-explorer__footer">
      <span class="workspace-explorer__status-dot" :class="{ 'is-active': Boolean(projection.activeRun) }" aria-hidden="true"></span>
      <span>{{ projection.activeRun ? `Run ${projection.activeRun.runId}` : 'No active Run' }}</span>
      <span v-if="projection.activeRun" class="workspace-explorer__readonly">read-only</span>
    </footer>
  </aside>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowDown, ArrowRight, Document, Files, FolderOpened, Share, WarningFilled, Clock } from '@element-plus/icons-vue'
import type { MissionWorkspaceProjection, WorkspaceEntry, WorkspaceEntryKind, WorkspaceRunStatus } from '@/services/api/agentos'

const props = defineProps<{
  projection: MissionWorkspaceProjection
  activeEditorId: string | null
  selectedRunId: string | null
}>()

const emit = defineEmits<{
  open: [entry: WorkspaceEntry]
  selectRun: [runId: string]
}>()

const expandedSections = ref<Record<string, boolean>>({
  overview: true,
  steps: true,
  output: true,
  runs: true
})

const groupLabels: Record<string, { label: string; empty: string }> = {
  overview: { label: 'OVERVIEW', empty: '当前 Run 尚未生成概览文件' },
  steps: { label: 'STEPS', empty: '当前 Run 尚无步骤产物' },
  output: { label: 'OUTPUT', empty: '当前 Run 尚无已证明的最终产物' },
  runs: { label: 'RUNS', empty: 'Mission 尚无历史 Run' }
}

const sections = computed(() => Object.entries(groupLabels).map(([group, meta]) => ({
  group,
  ...meta,
  items: props.projection.entries
    .filter(entry => entry.group === group && entry.kind !== 'folder')
    .sort((left, right) => left.displayOrder - right.displayOrder || left.entryId.localeCompare(right.entryId))
})))

const toggleSection = (group: string) => {
  expandedSections.value[group] = !expandedSections.value[group]
}

const isExpanded = (group: string) => expandedSections.value[group] !== false

const handleEntryClick = (entry: WorkspaceEntry) => {
  if (entry.kind === 'run' && entry.runId) {
    emit('selectRun', entry.runId)
    return
  }
  emit('open', entry)
}

const entryIcon = (entry: WorkspaceEntry) => {
  const icons: Record<WorkspaceEntryKind, typeof Document> = {
    folder: FolderOpened,
    graph: Share,
    virtual_document: Document,
    artifact: Files,
    run: Clock
  }
  return icons[entry.kind]
}

const runLabel = (status?: WorkspaceRunStatus | null) => ({
  pending: 'pending',
  running: 'running',
  succeeded: 'succeeded',
  failed: 'failed',
  cancelled: 'cancelled',
  superseded: 'superseded'
}[status || ''] || status || '')
</script>

<style scoped>
.workspace-explorer {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  height: 100%;
  color: var(--text-primary);
  background: var(--bg-card);
}

.workspace-explorer__header {
  padding: 16px 16px 13px;
  border-bottom: 1px solid var(--border-light);
}

.workspace-explorer__title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.workspace-explorer__mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  border: 1px solid var(--primary-line);
  border-radius: 6px;
  color: var(--primary-color);
  background: var(--primary-fade);
}

.workspace-explorer__title-row div {
  min-width: 0;
}

.workspace-explorer__title-row strong,
.workspace-explorer__title-row small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workspace-explorer__title-row strong {
  font-size: 13px;
  font-weight: 700;
}

.workspace-explorer__title-row small {
  margin-top: 2px;
  color: var(--text-secondary);
  font-size: 11px;
}

.workspace-explorer__mission-id {
  display: block;
  margin-top: 11px;
  overflow: hidden;
  color: var(--text-muted);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workspace-explorer__diagnostics {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border-light);
  background: color-mix(in srgb, var(--warning) 5%, transparent);
}

.diagnostic {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 6px;
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.4;
}

.diagnostic .el-icon { flex: 0 0 auto; color: var(--warning); }
.diagnostic--info .el-icon { color: var(--info); }
.diagnostic strong,
.diagnostic span { display: block; }
.diagnostic strong { color: var(--text-primary); font: 10px var(--font-mono, monospace); }

.workspace-tree {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px 6px;
  scrollbar-gutter: stable;
}

.workspace-tree__section { margin-bottom: 5px; }

.workspace-tree__section-toggle,
.workspace-tree__entry {
  display: flex;
  align-items: center;
  width: 100%;
  border: 0;
  color: var(--text-secondary);
  background: transparent;
  text-align: left;
}

.workspace-tree__section-toggle {
  gap: 4px;
  min-height: 28px;
  padding: 0 7px;
  cursor: pointer;
  font-size: 10px;
  font-weight: 750;
  letter-spacing: .08em;
}

.workspace-tree__section-toggle:hover { color: var(--text-primary); }
.workspace-tree__section-toggle small { margin-left: auto; color: var(--text-muted); font: 10px var(--font-mono, monospace); }

.workspace-tree__items { padding: 1px 0 4px; }

.workspace-tree__entry {
  gap: 8px;
  min-height: 31px;
  padding: 0 9px 0 17px;
  border-left: 2px solid transparent;
  cursor: pointer;
  font-size: 12px;
  transition: background 160ms var(--ease-out), color 160ms var(--ease-out), border-color 160ms var(--ease-out);
}

.workspace-tree__entry:hover { color: var(--text-primary); background: var(--bg-input); }
.workspace-tree__entry.is-active { border-left-color: var(--primary-color); color: var(--text-primary); background: var(--primary-fade); }
.workspace-tree__entry.is-current-run { color: var(--primary-color); }
.workspace-tree__entry.is-legacy { color: var(--warning); }
.workspace-tree__entry-icon { flex: 0 0 auto; color: var(--text-muted); }
.workspace-tree__entry.is-active .workspace-tree__entry-icon { color: var(--primary-color); }
.workspace-tree__entry-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workspace-tree__run-state { margin-left: auto; color: var(--text-muted); font: 10px var(--font-mono, monospace); }
.workspace-tree__legacy { margin-left: auto; color: var(--warning); font: 10px var(--font-mono, monospace); }
.workspace-tree__empty { margin: 4px 10px 8px 31px; color: var(--text-muted); font-size: 11px; line-height: 1.5; }

.workspace-explorer__footer {
  display: flex;
  align-items: center;
  gap: 7px;
  min-height: 34px;
  padding: 0 13px;
  border-top: 1px solid var(--border-light);
  color: var(--text-muted);
  font-size: 10px;
}

.workspace-explorer__status-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--text-disabled); }
.workspace-explorer__status-dot.is-active { background: var(--success); }
.workspace-explorer__readonly { margin-left: auto; color: var(--text-muted); font: 10px var(--font-mono, monospace); }

@media (prefers-reduced-motion: reduce) {
  .workspace-tree__entry { transition-duration: 1ms; }
}
</style>
