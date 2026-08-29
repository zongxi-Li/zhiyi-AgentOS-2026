<template>
  <div class="mission-workspace-view">
    <WorkbenchLayout
      :show-right="true"
      :show-bottom-panel="Boolean(projection)"
      bottom-panel-storage-key="zhiyi.mission.workspace.bottom-panel.v1"
      :bottom-panel-default-collapsed="true"
      storage-key="zhiyi.mission.workspace.layout.v1"
    >
      <template #left>
        <WorkbenchContributionRenderer
          v-if="projection"
          :contribution="sidebarContribution"
          :component-props="sidebarProps"
          @open="openEntry"
          @select-run="selectRun"
          @back="returnToProjectList"
        />
        <section v-else class="workspace-loading-pane" aria-label="Workspace loading status">
          <span class="workspace-loading-pane__mark">MISSION</span>
          <strong>{{ loading ? 'Loading workspace…' : 'Workspace unavailable' }}</strong>
          <span>{{ loadError || '等待 Mission 投影。' }}</span>
          <button v-if="loadError" type="button" @click="loadWorkspace()">Retry</button>
        </section>
      </template>

      <template #main>
        <EditorGroup
          v-if="projection"
          :projection="projection"
          :open-entries="openEntries"
          :active-editor-id="activeEditorId"
          :selected-semantic-task-key="selectedSemanticTaskKey"
          :focus-node-id="focusNodeId"
          :is-historical="isHistorical"
          :registry="registry"
          :workbench-context="workbenchContext"
          @activate="activeEditorId = $event"
          @close="closeEditor"
          @select-semantic-task="selectSemanticTask"
          @open-semantic-task="openSemanticTask"
          @locate-graph="locateGraph"
        />
        <section v-else class="workspace-main-state" role="status">
          <strong>{{ loading ? 'Loading Mission Workspace…' : 'Mission Workspace unavailable' }}</strong>
          <span>{{ loadError || '请从 Mission 导航进入一个 Project Workspace。' }}</span>
          <button v-if="loadError" type="button" @click="loadWorkspace()">重新加载</button>
        </section>
      </template>

      <template #right>
        <RuntimeInspector
          :entry="inspectorEntry"
          :graph-node="inspectorGraphNode"
          :graph-nodes="projection?.graphNodes || []"
          :available="inspectorAvailable"
          :run-id="projection?.activeRun?.runId || null"
          :mission-id="missionId"
          :graph="projection?.activeGraph || null"
          :run-status="projection?.activeRun?.status || null"
          :historical="isHistorical"
          :registry="registry"
          :workbench-context="workbenchContext"
          @locate-graph="inspectorEntry && locateGraph(inspectorEntry)"
        />
      </template>

      <template #bottom="{ collapsed, setCollapsed }">
        <WorkbenchBottomPanel
          :tabs="panelTabs"
          :model-value="collapsed"
          storage-key="zhiyi.mission.workspace.bottom-panel.v1"
          @update:model-value="setCollapsed"
        >
          <template #default="{ activeTab }">
            <WorkbenchContributionRenderer
              :contribution="resolvePanel(activeTab)"
              :component-props="panelProps(activeTab)"
            />
          </template>
        </WorkbenchBottomPanel>
      </template>
    </WorkbenchLayout>

    <div v-if="loadError && projection" class="workspace-request-error" role="alert">
      <span>{{ loadError }}</span>
      <button type="button" @click="loadWorkspace()">重新加载当前 Run</button>
    </div>

    <div v-if="artifactChoices.length" class="artifact-choice" role="dialog" aria-label="选择 Artifact">
      <div class="artifact-choice__panel">
        <header>
          <div>
            <span>同一 semanticTaskKey 下有多个 Artifact</span>
            <strong>{{ selectedSemanticTaskKey }}</strong>
          </div>
          <button type="button" aria-label="关闭 Artifact 选择" @click="artifactChoices = []">×</button>
        </header>
        <button v-for="entry in artifactChoices" :key="entry.entryId" type="button" class="artifact-choice__item" @click="chooseArtifact(entry)">
          <span>{{ entry.name }}</span>
          <code>{{ entry.artifactKey }}</code>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { agentosApi, type MissionWorkspaceProjection, type WorkspaceEntry, type WorkspaceGraphNode } from '@/services/api/agentos'
import WorkbenchLayout from '@/components/workbench/WorkbenchLayout.vue'
import EditorGroup, { type OpenWorkspaceEntry } from '@/components/workspace/EditorGroup.vue'
import RuntimeInspector from '@/components/workspace/RuntimeInspector.vue'
import WorkbenchBottomPanel, { type WorkbenchBottomTab } from '@/components/workbench/WorkbenchBottomPanel.vue'
import WorkbenchContributionRenderer from '@/components/workbench/WorkbenchContributionRenderer.vue'
import { createNativeWorkbenchRegistry } from '@/workbench/composition'
import { createWorkbenchContext } from '@/workbench/context'

const route = useRoute()
const router = useRouter()
const missionId = computed(() => String(route.params.missionId || route.query.missionId || ''))
const registry = createNativeWorkbenchRegistry()

const projection = ref<MissionWorkspaceProjection | null>(null)
const loading = ref(false)
const loadError = ref('')
const selectedRunId = ref<string | null>(typeof route.query.runId === 'string' ? route.query.runId : null)
const currentRunId = ref<string | null>(null)
const openEditors = ref<string[]>([])
const activeEditorId = ref<string | null>(null)
const selectedSemanticTaskKey = ref<string | null>(null)
const focusNodeId = ref<string | null>(null)
const selectedGraphNodeId = ref<string | null>(null)
const artifactChoices = ref<WorkspaceEntry[]>([])
const entryCache = ref<Record<string, WorkspaceEntry>>({})
let controller: AbortController | null = null

const workspaceProjectionRetryDelays = [
  250, 500, 1000, 2000, 3000,
  ...Array.from({ length: 23 }, () => 5000)
]

const entriesById = computed(() => new Map((projection.value?.entries || []).map(entry => [entry.entryId, entry])))
const openEntries = computed<OpenWorkspaceEntry[]>(() => openEditors.value.flatMap(entryId => {
  const current = entriesById.value.get(entryId)
  const snapshot = entryCache.value[entryId]
  if (!current && !snapshot) return []
  return [{ entry: current || snapshot, available: Boolean(current) }]
}))
const activeOpened = computed(() => openEntries.value.find(item => item.entry.entryId === activeEditorId.value) || null)
const inspectorEntry = computed(() => activeOpened.value?.entry || null)
const inspectorAvailable = computed(() => activeOpened.value?.available ?? false)
const inspectorGraphNode = computed<WorkspaceGraphNode | null>(() => {
  if (inspectorEntry.value?.kind !== 'graph' && inspectorEntry.value?.kind !== 'artifact') {
    return projection.value?.graphNodes.find(node => node.acgNodeId === selectedGraphNodeId.value) || null
  }
  if (inspectorEntry.value.kind === 'artifact') return null
  return projection.value?.graphNodes.find(node => node.acgNodeId === selectedGraphNodeId.value) || null
})
const isHistorical = computed(() => Boolean(
  projection.value?.activeRun && currentRunId.value && projection.value.activeRun.runId !== currentRunId.value
))

const workbenchContext = computed(() => createWorkbenchContext({
  missionId: missionId.value,
  runId: projection.value?.activeRun?.runId || null,
  selectedSemanticTaskKey: selectedSemanticTaskKey.value,
  selectedArtifactId: inspectorEntry.value?.artifactId || null,
  selectedAcgNodeId: selectedGraphNodeId.value,
  activeEditorId: activeEditorId.value,
  activeEntryKind: activeOpened.value?.entry.kind || null,
  historicalMode: isHistorical.value,
  diagnostics: projection.value?.diagnostics || []
}))

const sidebarContribution = computed(() => registry.getSidebarViews(workbenchContext.value)[0] || null)
const sidebarProps = computed(() => ({
  projection: projection.value,
  activeEditorId: activeEditorId.value,
  selectedRunId: selectedRunId.value
}))
const panelTabs = computed<WorkbenchBottomTab[]>(() => registry.getPanels(workbenchContext.value).map(panel => ({
  id: panel.id,
  label: panel.label,
  count: panel.count?.(workbenchContext.value)
})))
const resolvePanel = (panelId: string) => registry.resolvePanel(panelId, workbenchContext.value)
const panelProps = (panelId: string) => resolvePanel(panelId)?.getProps?.(workbenchContext.value) || {}

const defaultRunId = (items: MissionWorkspaceProjection['runs']) => {
  const active = items.filter(item => item.status === 'pending' || item.status === 'running')
  if (active.length) return active[active.length - 1].runId
  const succeeded = items.filter(item => item.status === 'succeeded')
  if (succeeded.length) return succeeded[succeeded.length - 1].runId
  return items[items.length - 1]?.runId || null
}

const openDefaultEditor = (nextProjection: MissionWorkspaceProjection) => {
  if (openEditors.value.length) return
  const first = nextProjection.entries.find(entry => entry.entryId === 'overview:graph.acg')
    || nextProjection.entries.find(entry => entry.entryId === 'overview:mission.md')
  if (first) {
    entryCache.value[first.entryId] = first
    openEditors.value = [first.entryId]
    activeEditorId.value = first.entryId
  }
}

const responseStatus = (error: unknown) => {
  const status = (error as { response?: { status?: unknown } })?.response?.status
  return typeof status === 'number' ? status : null
}

const isAbortError = (error: unknown) => {
  const name = (error as { name?: unknown })?.name
  return name === 'CanceledError' || name === 'AbortError'
}

const waitForWorkspaceRetry = (delayMs: number, signal: AbortSignal) => new Promise<void>((resolve, reject) => {
  let timer: ReturnType<typeof setTimeout> | null = setTimeout(finish, delayMs)
  const onAbort = () => {
    if (timer !== null) clearTimeout(timer)
    timer = null
    signal.removeEventListener('abort', onAbort)
    reject(new DOMException('Workspace projection request aborted', 'AbortError'))
  }
  function finish() {
    timer = null
    signal.removeEventListener('abort', onAbort)
    resolve()
  }
  if (signal.aborted) {
    onAbort()
    return
  }
  signal.addEventListener('abort', onAbort, { once: true })
})

const requestWorkspaceProjection = async (runId: string | null, signal: AbortSignal) => {
  let projectionPending = false
  let attempt = 0
  while (true) {
    try {
      return await agentosApi.getMissionWorkspace(missionId.value, {
        runId: runId || undefined,
        signal
      })
    } catch (error: unknown) {
      if (!runId || responseStatus(error) !== 404 || attempt >= workspaceProjectionRetryDelays.length) {
        throw error
      }

      if (!projectionPending) {
        try {
          const runtimeRun = await agentosApi.getWorkflowRun(runId, { signal })
          projectionPending = runtimeRun.missionId === missionId.value
        } catch (runtimeError: unknown) {
          if (isAbortError(runtimeError)) throw runtimeError
          throw error
        }
        if (!projectionPending) throw error
      }

      await waitForWorkspaceRetry(workspaceProjectionRetryDelays[attempt], signal)
      attempt += 1
    }
  }
}

const loadWorkspace = async (runId = selectedRunId.value) => {
  if (!missionId.value) {
    loadError.value = '缺少 missionId，无法加载 Mission Workspace。'
    return
  }
  controller?.abort()
  controller = new AbortController()
  const requestController = controller
  loading.value = true
  loadError.value = ''
  try {
    const nextProjection = await requestWorkspaceProjection(runId, requestController.signal)
    projection.value = nextProjection
    currentRunId.value ||= defaultRunId(nextProjection.runs)
    selectedRunId.value = nextProjection.activeRun?.runId || runId || null
    nextProjection.entries.forEach(entry => { entryCache.value[entry.entryId] = entry })
    openDefaultEditor(nextProjection)
  } catch (error: unknown) {
    if (isAbortError(error)) return
    loadError.value = '无法加载 Mission Workspace Projection，请稍后重试。'
  } finally {
    if (controller === requestController && !requestController.signal.aborted) loading.value = false
  }
}

const persistRunInUrl = async (runId: string) => {
  await router.replace({ query: { ...route.query, runId } })
}

const selectRun = async (runId: string) => {
  if (runId === projection.value?.activeRun?.runId && projection.value) return
  selectedRunId.value = runId
  await persistRunInUrl(runId)
  await loadWorkspace(runId)
}

const openEntry = (entry: WorkspaceEntry) => {
  entryCache.value[entry.entryId] = entry
  if (!openEditors.value.includes(entry.entryId)) openEditors.value.push(entry.entryId)
  activeEditorId.value = entry.entryId
  artifactChoices.value = []
}

const closeEditor = (entryId: string) => {
  const index = openEditors.value.indexOf(entryId)
  if (index < 0) return
  openEditors.value.splice(index, 1)
  if (activeEditorId.value !== entryId) return
  activeEditorId.value = openEditors.value[Math.max(0, index - 1)] || openEditors.value[0] || null
}

const selectSemanticTask = (semanticTaskKey: string | null) => {
  selectedSemanticTaskKey.value = semanticTaskKey
  selectedGraphNodeId.value = projection.value?.graphNodes.find(node => node.semanticTaskKey === semanticTaskKey)?.acgNodeId || null
  if (selectedGraphNodeId.value) focusNodeId.value = selectedGraphNodeId.value
}

const openSemanticTask = (semanticTaskKey: string | null) => {
  selectSemanticTask(semanticTaskKey)
  if (!semanticTaskKey || !projection.value) return
  const artifacts = projection.value.entries.filter(entry => entry.kind === 'artifact' && entry.semanticTaskKey === semanticTaskKey)
  if (artifacts.length === 1) {
    openEntry(artifacts[0])
  } else if (artifacts.length > 1) {
    artifactChoices.value = artifacts
  }
}

const chooseArtifact = (entry: WorkspaceEntry) => {
  artifactChoices.value = []
  openEntry(entry)
}

const returnToProjectList = () => {
  void router.push({ name: 'AcgVisualization' })
}

const locateGraph = (entry: WorkspaceEntry) => {
  if (entry.identityQuality === 'legacy' || !entry.semanticTaskKey || !projection.value) return
  const graphEntry = projection.value.entries.find(item => item.kind === 'graph')
  const graphNode = projection.value.graphNodes.find(item => item.semanticTaskKey === entry.semanticTaskKey)
  if (!graphEntry || !graphNode) return
  selectedSemanticTaskKey.value = entry.semanticTaskKey
  selectedGraphNodeId.value = graphNode.acgNodeId
  focusNodeId.value = graphNode.acgNodeId
  openEntry(graphEntry)
}

void loadWorkspace()
onBeforeUnmount(() => controller?.abort())
</script>

<style scoped>
.mission-workspace-view { width: 100%; height: 100%; min-width: 0; min-height: 0; overflow: hidden; background: var(--bg-app); }
.workspace-loading-pane { display: grid; align-content: center; gap: 8px; height: 100%; padding: 22px; color: var(--text-secondary); font-size: 12px; }
.workspace-loading-pane strong { color: var(--text-primary); font-size: 13px; }
.workspace-loading-pane span:not(.workspace-loading-pane__mark) { line-height: 1.6; }
.workspace-loading-pane__mark { color: var(--primary-color); font: 10px var(--font-mono, monospace); letter-spacing: .08em; }
.workspace-loading-pane button, .workspace-main-state button { width: max-content; min-height: 29px; padding: 0 10px; border: 1px solid var(--border-light); border-radius: 5px; color: var(--text-secondary); background: transparent; cursor: pointer; font-size: 11px; }
.workspace-loading-pane button:hover, .workspace-main-state button:hover { color: var(--primary-color); border-color: var(--primary-line); background: var(--primary-fade); }
.workspace-main-state { display: grid; place-items: center; align-content: center; gap: 8px; height: 100%; color: var(--text-secondary); font-size: 12px; text-align: center; }
.workspace-main-state strong { color: var(--text-primary); font-size: 14px; }
.workspace-request-error { position: fixed; top: 14px; right: 18px; z-index: 12; display: flex; align-items: center; gap: 12px; max-width: min(520px, calc(100vw - 36px)); padding: 9px 11px; border: 1px solid color-mix(in srgb, var(--danger) 45%, var(--border-light)); color: var(--danger); background: var(--bg-card); box-shadow: var(--shadow-sm); font-size: 11px; }
.workspace-request-error button { flex: 0 0 auto; padding: 4px 7px; border: 1px solid var(--border-light); border-radius: 4px; color: var(--text-secondary); background: transparent; cursor: pointer; font-size: 10px; }
.workspace-request-error button:hover { color: var(--primary-color); border-color: var(--primary-line); }
.artifact-choice { position: fixed; inset: 0; z-index: 20; display: grid; place-items: center; padding: 18px; background: color-mix(in srgb, var(--bg-app) 55%, transparent); }
.artifact-choice__panel { width: min(420px, 100%); border: 1px solid var(--border-light); background: var(--bg-card); box-shadow: var(--shadow-md); }
.artifact-choice__panel header { display: flex; justify-content: space-between; gap: 18px; padding: 14px 16px; border-bottom: 1px solid var(--border-light); }
.artifact-choice__panel header span, .artifact-choice__panel header strong { display: block; }
.artifact-choice__panel header span { color: var(--text-secondary); font-size: 12px; }
.artifact-choice__panel header strong { margin-top: 5px; color: var(--primary-color); font: 11px var(--font-mono, monospace); }
.artifact-choice__panel header button { width: 26px; height: 26px; border: 0; color: var(--text-muted); background: transparent; cursor: pointer; font-size: 18px; }
.artifact-choice__item { display: flex; justify-content: space-between; width: 100%; padding: 11px 16px; border: 0; border-bottom: 1px solid var(--border-light); color: var(--text-primary); background: transparent; cursor: pointer; text-align: left; }
.artifact-choice__item:hover { background: var(--primary-fade); }
.artifact-choice__item code { color: var(--text-muted); font: 10px var(--font-mono, monospace); }
</style>
