<template>
  <div class="mission-workspace-view">
    <WorkbenchLayout
      :show-right="true"
      :show-bottom-panel="Boolean(projection)"
      bottom-panel-storage-key="zhiyi.mission.workspace.bottom-panel.v1"
      :bottom-panel-default-collapsed="false"
      storage-key="zhiyi.mission.workspace.layout.v1"
    >
      <template #left>
        <WorkbenchContributionRenderer
          v-if="projection"
          :contribution="sidebarContribution"
          :component-props="sidebarProps"
          @open="openEntry"
          @select-run="selectRun"
          @rerun="rerunSelectedRun"
          @back="returnToProjectList"
        />
        <section v-else class="workspace-loading-pane" aria-label="Workspace loading status">
          <span class="workspace-loading-pane__mark">MISSION</span>
          <strong>{{ loading ? 'Loading workspace…' : 'Workspace unavailable' }}</strong>
          <span>{{ loadError || '等待 Mission 投影。' }}</span>
          <button v-if="loadError" type="button" @click="loadWorkspace()">Retry</button>
        </section>
      </template>

      <template #main="mainState">
        <EditorGroup
          v-if="projection"
          :projection="projection"
          :open-entries="openEntries"
          :active-editor-id="activeEditorId"
          :selected-semantic-task-key="selectedSemanticTaskKey"
          :selected-symbol-id="selectedSymbolId"
          :focus-node-id="focusNodeId"
          :registry="registry"
          :workbench-context="workbenchContext"
          :runtime-store="runtimeStore"
          :inspector-visible="mainState.rightPaneVisible"
          :inspector-auto-hidden="mainState.rightAutoHidden"
          :toggle-inspector="mainState.toggleRightPane"
          :sidebar-hidden="mainState.leftAutoHidden"
          :cancel-pending="cancelPending"
          @restore-sidebar="mainState.restoreLeftPane()"
          @activate="activeEditorId = $event"
          @close="closeEditor"
          @select-semantic-task="selectSemanticTask"
          @select-symbol="selectRunSymbol"
          @open-semantic-task="openSemanticTask"
          @locate-graph="locateGraph"
          @open-artifact="openEntry"
          @open-entry="openEntry"
          @cancel-run="cancelActiveRun"
          @content-ready="finishForegroundContent"
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
          :selected-symbol="selectedSymbol"
          :graph-nodes="projection?.graphNodes || []"
          :available="inspectorAvailable"
          :run-id="projection?.activeRun?.runId || selectedRunId || null"
          :mission-id="missionId"
          :graph="projection?.activeGraph || null"
          :run-status="projection?.activeRun?.status || null"
          :historical="isHistorical"
          :runtime-store="runtimeStore"
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
              @select="selectRuntimeTarget"
            />
          </template>
        </WorkbenchBottomPanel>
      </template>
    </WorkbenchLayout>

    <div
      v-if="loadError && projection"
      class="workspace-request-error"
      :class="{ 'is-collapsed': requestErrorCollapsed }"
      role="alert"
    >
      <span class="workspace-request-error__indicator" aria-hidden="true" />
      <span class="workspace-request-error__message">{{ loadError }}</span>
      <button
        class="workspace-request-error__toggle"
        type="button"
        :aria-expanded="!requestErrorCollapsed"
        :aria-label="requestErrorCollapsed ? '展开错误提示' : '收起错误提示'"
        :title="requestErrorCollapsed ? '展开错误提示' : '收起错误提示'"
        @click="requestErrorCollapsed = !requestErrorCollapsed"
      >
        <span aria-hidden="true">{{ requestErrorCollapsed ? '‹' : '›' }}</span>
      </button>
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
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { agentosApi, type MissionWorkspaceProjection, type WorkspaceEntry, type WorkspaceGraphNode } from '@/services/api/agentos'
import WorkbenchLayout from '@/components/workbench/WorkbenchLayout.vue'
import EditorGroup, { type OpenWorkspaceEntry } from '@/components/workspace/EditorGroup.vue'
import RuntimeInspector from '@/components/workspace/RuntimeInspector.vue'
import WorkbenchBottomPanel, { type WorkbenchBottomTab } from '@/components/workbench/WorkbenchBottomPanel.vue'
import WorkbenchContributionRenderer from '@/components/workbench/WorkbenchContributionRenderer.vue'
import { createNativeWorkbenchRegistry } from '@/workbench/composition'
import { createWorkbenchContext } from '@/workbench/context'
import { RuntimeObservationAdapter, type RuntimeObservation, type RuntimeSelection } from '@/workbench/runtime/observation'
import { acquireRunRuntimeStore, releaseRunRuntimeStore, type RunRuntimeStore } from '@/workbench/runtime/runtimeEvents'
import type { RunDocumentSymbol } from '@/workbench/runtime/runDocument'
import { isRunDeliverableEntry } from '@/workbench/runtime/deliverableIdentity'
import { chooseFailedRunRetryMode } from '@/utils/retryModeChoice'

const route = useRoute()
const router = useRouter()
const missionId = computed(() => String(route.params.missionId || route.query.missionId || ''))
const registry = createNativeWorkbenchRegistry()

const projection = ref<MissionWorkspaceProjection | null>(null)
const loading = ref(false)
const loadError = ref('')
const requestErrorCollapsed = ref(false)
const rerunPending = ref(false)
const cancelPending = ref(false)
const selectedRunId = ref<string | null>(typeof route.query.runId === 'string' ? route.query.runId : null)
const currentRunId = ref<string | null>(null)
const openEditors = ref<string[]>([])
const activeEditorId = ref<string | null>(null)
const selectedSemanticTaskKey = ref<string | null>(null)
const selectedSymbolId = ref<string | null>(null)
const selectedSymbolType = ref<RunDocumentSymbol['type'] | null>(null)
const selectedSymbol = ref<RunDocumentSymbol | null>(null)
const focusNodeId = ref<string | null>(null)
const selectedGraphNodeId = ref<string | null>(null)
// Runtime observations can contain tens of thousands of immutable trace rows.
// The snapshot is replaced as a whole, so deep Vue proxies only add work here.
const runtimeObservation = shallowRef<RuntimeObservation | null>(null)
const runtimeStore = shallowRef<RunRuntimeStore | null>(null)
let runtimeStoreRunId: string | null = null
const artifactChoices = ref<WorkspaceEntry[]>([])
const entryCache = ref<Record<string, WorkspaceEntry>>({})
let controller: AbortController | null = null
const runtimeObservationAdapter = new RuntimeObservationAdapter()
let pendingObservation: { runId: string; start: () => void } | null = null
const finishForegroundContent = (runId: string | null) => {
  if (!pendingObservation || pendingObservation.runId !== runId) return
  const pending = pendingObservation
  pendingObservation = null
  if (selectedRunId.value === runId) pending.start()
}

const workspaceProjectionRetryDelays = [
  250, 500, 1000, 2000, 3000,
  ...Array.from({ length: 23 }, () => 5000)
]

// Run Progress is a first-class editor entry. Its identity is scoped to the Run
// so reopening/history switching cannot silently reuse another Run's document.
const progressEntryFor = (runId: string | null): WorkspaceEntry => ({
  entryId: runId ? `run:${runId}:progress` : 'overview:progress',
  kind: 'progress',
  name: '运行进度',
  title: '运行进度',
  group: 'overview',
  displayOrder: -1,
  runId,
  status: runId ? projection.value?.activeRun?.status || null : null,
  isActive: Boolean(runId)
})
const entriesWithProgress = computed<WorkspaceEntry[]>(() => {
  if (!projection.value) return []
  const progressEntry = progressEntryFor(projection.value.activeRun?.runId || selectedRunId.value)
  const projectedEntries = projection.value.entries
  const projectedRunIds = new Set(projectedEntries
    .filter(entry => entry.kind === 'run' && entry.runId)
    .map(entry => entry.runId))
  const runtimeRunEntries: WorkspaceEntry[] = projection.value.runs
    .filter(run => !projectedRunIds.has(run.runId))
    .map((run, index) => ({
      entryId: `run:${run.runId}`,
      kind: 'run',
      name: run.runId,
      group: 'runs',
      displayOrder: index,
      runId: run.runId,
      status: run.status,
      parentRunId: run.parentRunId,
      sourceRunId: run.sourceRunId,
      createdAt: run.createdAt,
      completedAt: run.completedAt,
      isActive: run.isActive
    }))
  const missionEntry: WorkspaceEntry[] = projectedEntries.some(entry => entry.entryId === 'overview:mission.md')
    ? []
    : [{
        entryId: 'overview:mission.md',
        kind: 'virtual_document',
        name: 'mission.md',
        group: 'overview',
        displayOrder: 1,
        content: projection.value.mission.goal
      }]
  return [progressEntry, ...missionEntry, ...projectedEntries, ...runtimeRunEntries]
})
const augmentedProjection = computed<MissionWorkspaceProjection | null>(() => (
  projection.value ? { ...projection.value, entries: entriesWithProgress.value } : null
))
const entriesById = computed(() => new Map(entriesWithProgress.value.map(entry => [entry.entryId, entry])))
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
  if (inspectorEntry.value?.kind === 'task') {
    return projection.value?.graphNodes.find(node => node.semanticTaskKey === inspectorEntry.value?.semanticTaskKey) || null
  }
  if (inspectorEntry.value?.kind !== 'graph' && inspectorEntry.value?.kind !== 'artifact') {
    return projection.value?.graphNodes.find(node => node.acgNodeId === selectedGraphNodeId.value) || null
  }
  if (inspectorEntry.value.kind === 'artifact') return null
  return projection.value?.graphNodes.find(node => node.acgNodeId === selectedGraphNodeId.value) || null
})
const isHistorical = computed(() => Boolean(
  projection.value?.activeRun && currentRunId.value && projection.value.activeRun.runId !== currentRunId.value
))
const terminalRunStatuses = new Set(['completed', 'succeeded', 'failed', 'cancelled', 'superseded'])
const cancellableRunStatuses = new Set(['pending', 'planning', 'running', 'retrying', 'waiting_review'])
const canRerunSelectedRun = computed(() => Boolean(
  projection.value?.activeRun?.runId && terminalRunStatuses.has(projection.value.activeRun.status || '')
))
const shouldResumeSelectedRun = computed(() => projection.value?.activeRun?.status === 'failed')
const canCancelActiveRun = computed(() => Boolean(
  projection.value?.activeRun?.runId
  && !isHistorical.value
  && cancellableRunStatuses.has(projection.value.activeRun.status || '')
  && !cancelPending.value
))
const rerunDisabledReason = computed(() => {
  if (rerunPending.value) return '正在创建新的 Run'
  if (!canRerunSelectedRun.value) return '当前运行尚未结束'
  return shouldResumeSelectedRun.value
    ? '复用已完成节点，从失败节点继续执行'
    : '从当前 Run 创建新的执行版本'
})
const rerunLabel = computed(() => shouldResumeSelectedRun.value ? '从失败处继续' : '再次运行')

const workbenchContext = computed(() => createWorkbenchContext({
  missionId: missionId.value,
  runId: projection.value?.activeRun?.runId || selectedRunId.value || null,
  selectedSemanticTaskKey: selectedSemanticTaskKey.value,
  selectedArtifactId: selectedSymbol.value?.artifactId || inspectorEntry.value?.artifactId || null,
  selectedAcgNodeId: selectedGraphNodeId.value,
  selectedSymbolId: selectedSymbolId.value,
  selectedSymbolType: selectedSymbolType.value,
  activeEditorId: activeEditorId.value,
  activeEntryKind: activeOpened.value?.entry.kind || null,
  historicalMode: isHistorical.value,
  diagnostics: projection.value?.diagnostics || [],
  runtimeObservation: runtimeObservation.value
}))

const sidebarContribution = computed(() => registry.getSidebarViews(workbenchContext.value)[0] || null)
const sidebarProps = computed(() => ({
  projection: augmentedProjection.value,
  activeEditorId: activeEditorId.value,
  selectedSemanticTaskKey: selectedSemanticTaskKey.value,
  selectedRunId: selectedRunId.value,
  canRerun: canRerunSelectedRun.value,
  rerunPending: rerunPending.value,
  rerunDisabledReason: rerunDisabledReason.value,
  rerunLabel: rerunLabel.value
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
  const promptEntry = nextProjection.entries.find(entry => entry.entryId === 'overview:mission.md')
  const first = nextProjection.entries.find(entry => entry.entryId === 'overview:graph.acg')
  const finalEntry = nextProjection.entries.find(entry => entry.kind === 'artifact' && isRunDeliverableEntry(entry))
  const runActive = nextProjection.activeRun?.status === 'running' || nextProjection.activeRun?.status === 'pending'
  const progressEntry = progressEntryFor(nextProjection.activeRun?.runId || selectedRunId.value)
  const openIds = [
    ...(runActive ? [progressEntry.entryId] : []),
    ...(runActive && promptEntry ? [promptEntry.entryId] : []),
    ...(finalEntry ? [finalEntry.entryId] : first ? [first.entryId] : [])
  ]
  if (!openIds.length && promptEntry) openIds.push(promptEntry.entryId)
  if (!openIds.length) return
  openIds.forEach(entryId => {
    const entry = entryId === progressEntry.entryId
      ? progressEntry
      : nextProjection.entries.find(item => item.entryId === entryId)
    if (entry) entryCache.value[entry.entryId] = entry
  })
  openEditors.value = openIds
  activeEditorId.value = runActive ? progressEntry.entryId : openIds[0]
}

const syncProgressEditorIdentity = (nextProjection: MissionWorkspaceProjection, requestedRunId: string | null) => {
  const nextEntry = progressEntryFor(nextProjection.activeRun?.runId || requestedRunId)
  const currentId = openEditors.value.find(entryId => entryCache.value[entryId]?.kind === 'progress')
  if (!currentId || currentId === nextEntry.entryId) {
    entryCache.value[nextEntry.entryId] = nextEntry
    return
  }
  const index = openEditors.value.indexOf(currentId)
  openEditors.value.splice(index, 1, nextEntry.entryId)
  entryCache.value[nextEntry.entryId] = nextEntry
  if (activeEditorId.value === currentId) activeEditorId.value = nextEntry.entryId
}

const focusProgressEditor = (nextProjection: MissionWorkspaceProjection, requestedRunId: string | null) => {
  const runId = nextProjection.activeRun?.runId || requestedRunId
  if (!runId) return
  const nextEntry = progressEntryFor(runId)
  const currentId = openEditors.value.find(entryId => (
    entryId === 'overview:progress' || entryCache.value[entryId]?.kind === 'progress'
  ))
  if (currentId && currentId !== nextEntry.entryId) {
    const index = openEditors.value.indexOf(currentId)
    if (index >= 0) openEditors.value.splice(index, 1, nextEntry.entryId)
  } else if (!openEditors.value.includes(nextEntry.entryId)) {
    openEditors.value.unshift(nextEntry.entryId)
  }
  entryCache.value[nextEntry.entryId] = nextEntry
  activeEditorId.value = nextEntry.entryId
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

// Java 网关对 AgentOS GET 的预算只有几秒；活跃 Run 执行高峰时投影查询可能暂时
// 超时变成 502/503/504。这类瞬时抖动与 404（投影未注册）一样按退避梯子重试。
const TRANSIENT_PROJECTION_STATUSES = new Set([502, 503, 504])

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
      const status = responseStatus(error)
      const transientFailure = status !== null && TRANSIENT_PROJECTION_STATUSES.has(status)
      const pendingProjection404 = !transientFailure && Boolean(runId) && status === 404
      if ((!transientFailure && !pendingProjection404) || attempt >= workspaceProjectionRetryDelays.length) {
        throw error
      }

      if (pendingProjection404 && !projectionPending && runId) {
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

// 降级投影重拉：PLANNING_PROJECTION_PENDING 表示 identity graph 尚未注册，
// Run 活跃期间周期性重拉投影，注册完成后 STEPS/OUTPUT/RUNS/Graph 即刻出现。
const PROJECTION_REFRESH_MS = 8000
const ACTIVE_PROJECTION_RUN_STATUSES = new Set(['pending', 'planning', 'running', 'retrying', 'waiting_review'])
let projectionRefreshTimer: ReturnType<typeof setTimeout> | null = null

const stopProjectionRefresh = () => {
  if (projectionRefreshTimer !== null) {
    clearTimeout(projectionRefreshTimer)
    projectionRefreshTimer = null
  }
}

const projectionPending = (projection: MissionWorkspaceProjection) => Boolean(
  projection.diagnostics?.some(item => item.code === 'PLANNING_PROJECTION_PENDING')
  && ACTIVE_PROJECTION_RUN_STATUSES.has(projection.activeRun?.status || '')
)
const projectionActive = (projection: MissionWorkspaceProjection) => (
  ACTIVE_PROJECTION_RUN_STATUSES.has(projection.activeRun?.status || '')
)

const scheduleProjectionRefresh = () => {
  stopProjectionRefresh()
  projectionRefreshTimer = setTimeout(async () => {
    projectionRefreshTimer = null
    if (loading.value) return
    const projectionSnapshot = projection.value
    if (projectionSnapshot && projectionActive(projectionSnapshot)) await loadWorkspace(selectedRunId.value)
  }, PROJECTION_REFRESH_MS)
}

const loadWorkspace = async (runId = selectedRunId.value, options: { focusProgress?: boolean } = {}) => {
  if (!missionId.value) {
    loadError.value = '缺少 missionId，无法加载 Mission Workspace。'
    return
  }
  // Keep the rendered projection and runtime observation visible while the
  // periodic projection refresh is in flight. Clearing them here made the
  // inspector and bottom panels flash on every refresh cycle.
  const runSelectionChanged = Boolean(
    runId
    && projection.value?.activeRun?.runId
    && projection.value.activeRun.runId !== runId
  )
  const preserveRenderedWorkspace = Boolean(projection.value && !runSelectionChanged)
  controller?.abort()
  if (!preserveRenderedWorkspace) {
    pendingObservation = null
    runtimeObservationAdapter.stop()
  }
  stopProjectionRefresh()
  controller = new AbortController()
  const requestController = controller
  if (!preserveRenderedWorkspace) runtimeObservation.value = null
  loading.value = true
  loadError.value = ''
  try {
    const nextProjection = await requestWorkspaceProjection(runId, requestController.signal)
    projection.value = nextProjection
    currentRunId.value ||= defaultRunId(nextProjection.runs)
    selectedRunId.value = nextProjection.activeRun?.runId || runId || null
    nextProjection.entries.forEach(entry => { entryCache.value[entry.entryId] = entry })
    syncProgressEditorIdentity(nextProjection, runId)
    openDefaultEditor(nextProjection)
    if (options.focusProgress) focusProgressEditor(nextProjection, runId)
    const nextRunId = nextProjection.activeRun?.runId || runId || null
    const streamRunId = projectionActive(nextProjection) ? nextRunId : null
    if (runtimeStoreRunId !== streamRunId) {
      releaseRunRuntimeStore(runtimeStoreRunId, runtimeStore.value)
      runtimeStore.value = acquireRunRuntimeStore(streamRunId)
      runtimeStoreRunId = streamRunId
    }
    if (nextRunId) {
      if (runtimeObservation.value?.runId !== nextRunId) runtimeObservation.value = null
      const startObservation = () => runtimeObservationAdapter.start(nextRunId, {
        historical: Boolean(currentRunId.value && currentRunId.value !== nextRunId),
        diagnostics: nextProjection.diagnostics,
        onUpdate: observation => {
          if (selectedRunId.value === observation.runId) {
            runtimeObservation.value = observation
          }
        }
      })
      // Give the foreground document the first read slot. Inspector/Trace
      // requests start when its read finishes, including failures.
      const opened = activeOpened.value
      if (!runtimeObservation.value && opened?.available && opened.entry.kind === 'artifact'
        && (opened.entry.contentRef || opened.entry.artifactId)) {
        pendingObservation = { runId: nextRunId, start: startObservation }
      } else startObservation()
    }
    // 降级投影等待 identity 注册：活跃 Run 期间周期重拉，直到 PLANNING_PROJECTION_PENDING 消失。
    if (projectionActive(nextProjection)) scheduleProjectionRefresh()
  } catch (error: unknown) {
    if (isAbortError(error)) return
    // 重试梯子耗尽才到这里：活跃 Run 期间继续周期重拉，抖动恢复后错误条自动
    // 消失；一次网关抖动不应把报错钉在右上角并让工作台停止自愈。
    loadError.value = projection.value
      ? 'Mission Workspace Projection 暂时刷新失败，正在自动重试…'
      : '无法加载 Mission Workspace Projection，请稍后重试。'
    scheduleProjectionRefresh()
  } finally {
    if (controller === requestController && !requestController.signal.aborted) loading.value = false
  }
}

const persistRunInUrl = async (runId: string) => {
  await router.replace({ query: { ...route.query, runId } })
}

const selectRun = async (runId: string) => {
  if (runId === projection.value?.activeRun?.runId && projection.value) {
    const progress = entriesWithProgress.value.find(entry => entry.kind === 'progress')
    if (progress) openEntry(progress)
    return
  }
  selectedRunId.value = runId
  selectedSymbolId.value = null
  selectedSymbolType.value = null
  selectedSymbol.value = null
  selectedSemanticTaskKey.value = null
  selectedGraphNodeId.value = null
  focusNodeId.value = null
  await persistRunInUrl(runId)
  await loadWorkspace(runId, { focusProgress: true })
}

const createClientRequestId = () => globalThis.crypto?.randomUUID?.()
  || `rerun-${Date.now()}-${Math.random().toString(36).slice(2)}`

const rerunErrorMessage = (error: unknown) => {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown; message?: unknown } } })?.response
  const detail = [response?.data?.detail, response?.data?.message]
    .find(value => typeof value === 'string' && value.trim())
  if (typeof detail === 'string') return detail
  if (response?.status === 401 || response?.status === 403) return '当前账户无权创建新的 Run'
  if (response?.status === 404) return '当前 Mission 或源 Run 不存在'
  if (response?.status === 422) return '历史运行配置无法用于再次运行'
  return '创建新的 Run 失败，请稍后重试'
}

watch(loadError, (nextError, previousError) => {
  if (!nextError || nextError !== previousError) requestErrorCollapsed.value = false
})

const cancelErrorMessage = (error: unknown) => {
  const status = responseStatus(error)
  if (status === 401 || status === 403) return '当前账户无权停止这个 Run'
  if (status === 404) return '当前 Run 不存在，工作台需要重新加载'
  return '停止运行失败，请稍后重试'
}

const cancelActiveRun = async () => {
  const run = projection.value?.activeRun
  if (!run?.runId || !canCancelActiveRun.value) return
  try {
    await ElMessageBox.confirm(
      '确定要停止当前运行吗？已完成的步骤会保留，后续步骤不再执行。',
      run.status === 'waiting_review' ? '放弃审核' : '停止运行',
      { confirmButtonText: '停止运行', cancelButtonText: '继续运行', type: 'warning' }
    )
  } catch {
    return
  }

  cancelPending.value = true
  loadError.value = ''
  try {
    const cancelled = await agentosApi.cancelWorkflowRun(run.runId)
    const status = cancelled.status
    projection.value = projection.value
      ? {
          ...projection.value,
          activeRun: projection.value.activeRun?.runId === run.runId
            ? { ...projection.value.activeRun, status, isActive: false }
            : projection.value.activeRun,
          runs: projection.value.runs.map(item => item.runId === run.runId
            ? { ...item, status, isActive: false }
            : item)
        }
      : projection.value
    ElMessage.success('运行已停止')
  } catch (error: unknown) {
    if (responseStatus(error) === 409) {
      ElMessage.warning('该运行已结束，无需停止')
      await loadWorkspace(run.runId)
    } else {
      ElMessage.error(cancelErrorMessage(error))
    }
  } finally {
    cancelPending.value = false
  }
}

const rerunSelectedRun = async () => {
  const sourceRunId = projection.value?.activeRun?.runId
  if (!sourceRunId || !canRerunSelectedRun.value || rerunPending.value) return
  rerunPending.value = true
  loadError.value = ''
  const clientRequestId = createClientRequestId()
  try {
    if (shouldResumeSelectedRun.value) {
      const sourceRun = await agentosApi.getWorkflowRun(sourceRunId)
      const failedStep = sourceRun.steps.find(step => step.status === 'failed')
      if (!failedStep?.stepId) {
        throw new Error('未找到可恢复的失败节点')
      }
      const mode = await chooseFailedRunRetryMode(sourceRunId)
      if (!mode) return
      const nextRun = await agentosApi.retryWorkflowStepAsync(sourceRunId, failedStep.stepId, {
        clientRequestId,
        reason: 'resume_failed',
        expectedRuntimeRevision: sourceRun.runtimeRevision,
        mode
      })
      currentRunId.value = nextRun.runId
      selectedRunId.value = nextRun.runId
      await persistRunInUrl(nextRun.runId)
      await loadWorkspace(nextRun.runId, { focusProgress: true })
      return
    }
    const history = await agentosApi.getWorkflowHistoryConfig(sourceRunId)
    const nextRun = await agentosApi.rerunWorkflowAsync(missionId.value, {
      reviewMode: history.reviewMode || 'auto',
      input: history.input || {},
      enabledPluginIds: history.enabledPluginIds || null,
      clientRequestId,
      sourceRunId,
      rerunReason: 'manual_rerun'
    })
    currentRunId.value = nextRun.runId
    selectedRunId.value = nextRun.runId
    await persistRunInUrl(nextRun.runId)
    await loadWorkspace(nextRun.runId, { focusProgress: true })
  } catch (error: unknown) {
    if (!isAbortError(error)) loadError.value = rerunErrorMessage(error)
  } finally {
    rerunPending.value = false
  }
}

const openEntry = (entry: WorkspaceEntry) => {
  entryCache.value[entry.entryId] = entry
  if (!openEditors.value.includes(entry.entryId)) openEditors.value.push(entry.entryId)
  activeEditorId.value = entry.entryId
  artifactChoices.value = []
  if (entry.kind === 'task' || entry.kind === 'artifact') {
    const type = entry.kind
    selectedSymbolType.value = type
    selectedSymbolId.value = `${type}:${entry.kind === 'artifact' ? (entry.artifactKey || entry.artifactId || entry.entryId) : (entry.semanticTaskKey || entry.acgNodeId || entry.entryId)}`
    selectedSymbol.value = {
      id: selectedSymbolId.value,
      type,
      status: ['completed', 'succeeded'].includes(entry.status || '') ? 'completed' : ['failed', 'cancelled'].includes(entry.status || '') ? 'failed' : ['running', 'pending', 'planning'].includes(entry.status || '') ? 'running' : 'pending',
      title: entry.name,
      subtitle: entry.semanticTaskKey || entry.artifactKey || undefined,
      runId: entry.runId || projection.value?.activeRun?.runId || '',
      semanticTaskKey: entry.semanticTaskKey,
      graphNodeId: entry.acgNodeId,
      artifactKey: entry.artifactKey,
      artifactId: entry.artifactId,
      children: []
    }
    if (entry.semanticTaskKey) selectSemanticTask(entry.semanticTaskKey)
  } else if (entry.kind !== 'progress' && entry.kind !== 'run') {
    selectedSymbolId.value = null
    selectedSymbolType.value = null
    selectedSymbol.value = null
  }
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

const selectRunSymbol = (item: RunDocumentSymbol) => {
  selectedSymbolId.value = item.id
  selectedSymbolType.value = item.type
  selectedSymbol.value = item
  if (item.graphNodeId) {
    selectedGraphNodeId.value = item.graphNodeId
    focusNodeId.value = item.graphNodeId
  }
  if (item.semanticTaskKey) selectSemanticTask(item.semanticTaskKey)
}

const selectRuntimeTarget = (selection: RuntimeSelection) => {
  const node = projection.value?.graphNodes.find(item => (
    (selection.stepId && item.acgNodeId === selection.stepId)
    || (selection.semanticTaskKey && item.semanticTaskKey === selection.semanticTaskKey)
  ))
  if (!node) return
  selectedSemanticTaskKey.value = node.semanticTaskKey || null
  selectedGraphNodeId.value = node.acgNodeId
  focusNodeId.value = node.acgNodeId
  const graphEntry = projection.value?.entries.find(item => item.kind === 'graph')
  if (graphEntry && inspectorEntry.value?.kind === 'artifact') openEntry(graphEntry)
}

const openSemanticTask = (semanticTaskKey: string | null) => {
  selectSemanticTask(semanticTaskKey)
  if (!semanticTaskKey || !projection.value) return
  const task = projection.value.entries.find(entry => entry.kind === 'task' && entry.semanticTaskKey === semanticTaskKey)
  if (task) {
    openEntry(task)
    return
  }
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
  if (!projection.value) return
  // Run Progress 的 ACG Compile 直接携带 graph entry：打开既有 Graph Editor 即可。
  if (entry.kind === 'graph') {
    openEntry(entry)
    return
  }
  if (entry.identityQuality === 'legacy' || !entry.semanticTaskKey) return
  const graphEntry = projection.value.entries.find(item => item.kind === 'graph')
  const graphNode = projection.value.graphNodes.find(item => item.semanticTaskKey === entry.semanticTaskKey)
  if (!graphEntry || !graphNode) return
  selectedSemanticTaskKey.value = entry.semanticTaskKey
  selectedGraphNodeId.value = graphNode.acgNodeId
  // 先打开 Graph Editor，再写入 focusNodeId，确保首次挂载时也能被图组件的 watcher 捕获。
  focusNodeId.value = null
  openEntry(graphEntry)
  void nextTick(() => {
    focusNodeId.value = graphNode.acgNodeId
  })
}

void loadWorkspace()
watch(activeEditorId, () => {
  if (activeOpened.value?.entry.kind !== 'artifact') finishForegroundContent(selectedRunId.value)
})
onBeforeUnmount(() => {
  pendingObservation = null
  controller?.abort()
  runtimeObservationAdapter.stop()
  stopProjectionRefresh()
  releaseRunRuntimeStore(runtimeStoreRunId, runtimeStore.value)
  runtimeStore.value = null
  runtimeStoreRunId = null
})
</script>

<style scoped>
.mission-workspace-view { width: 100%; height: 100%; min-width: 0; min-height: 0; overflow: hidden; background: var(--bg-app); }
.workspace-loading-pane { display: grid; place-items: center; align-content: center; gap: 8px; box-sizing: border-box; height: 100%; padding: 22px; color: var(--text-secondary); font-size: 12px; text-align: center; }
.workspace-loading-pane::before,
.workspace-main-state::before { width: 7px; height: 7px; border: 1px solid color-mix(in srgb, var(--primary-color) 60%, var(--border-light)); border-radius: 50%; background: var(--primary-fade); box-shadow: 0 0 0 5px color-mix(in srgb, var(--primary-color) 8%, transparent); content: ''; animation: workspace-state-pulse 1.8s ease-in-out infinite; }
.workspace-loading-pane strong { color: var(--text-primary); font-size: 13px; }
.workspace-loading-pane span:not(.workspace-loading-pane__mark) { max-width: 230px; line-height: 1.6; }
.workspace-loading-pane__mark { color: var(--primary-color); font: 10px var(--font-mono, monospace); letter-spacing: .08em; }
.workspace-loading-pane button, .workspace-main-state button { width: max-content; min-height: 29px; padding: 0 10px; border: 1px solid var(--border-light); border-radius: 5px; color: var(--text-secondary); background: transparent; cursor: pointer; font-size: 11px; }
.workspace-loading-pane button:hover, .workspace-main-state button:hover { color: var(--primary-color); border-color: var(--primary-line); background: var(--primary-fade); }
.workspace-main-state { display: grid; place-items: center; align-content: center; gap: 8px; box-sizing: border-box; height: 100%; min-height: 260px; padding: 24px; color: var(--text-secondary); font-size: 12px; text-align: center; }
.workspace-main-state strong { color: var(--text-primary); font-size: 14px; font-weight: 650; }
.workspace-main-state > span { max-width: 320px; line-height: 1.65; }
.workspace-main-state button { margin-top: 3px; }

@keyframes workspace-state-pulse {
  0%, 100% { opacity: .42; transform: scale(.88); }
  50% { opacity: 1; transform: scale(1); }
}

@media (prefers-reduced-motion: reduce) {
  .workspace-loading-pane::before,
  .workspace-main-state::before { animation: none; }
}
.workspace-request-error {
  /* Keep the notice in the route viewport. Fixed positioning put it under the
     desktop title bar, so only the lower edge was visible in Tauri. */
  position: absolute;
  top: 14px;
  right: 18px;
  z-index: 12;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  width: min(560px, calc(100% - 36px));
  min-width: 0;
  box-sizing: border-box;
  padding: 10px 12px 10px 14px;
  border: 1px solid color-mix(in srgb, var(--danger) 48%, var(--border-light));
  border-radius: 10px;
  color: var(--danger);
  background: color-mix(in srgb, var(--bg-card) 94%, var(--danger) 6%);
  box-shadow: var(--shadow-md), 0 1px 0 color-mix(in srgb, var(--text-primary) 7%, transparent) inset;
  -webkit-backdrop-filter: blur(14px);
  backdrop-filter: blur(14px);
  font-size: 11px;
  transition: width 180ms var(--ease-out), padding 180ms var(--ease-out), border-radius 180ms ease, box-shadow 180ms ease;
  animation: workspace-request-error-enter 180ms var(--ease-out);
}
.workspace-request-error__indicator {
  flex: 0 0 7px;
  width: 7px;
  height: 7px;
  margin-top: 5px;
  border-radius: 50%;
  background: var(--danger);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--danger) 12%, transparent);
}
.workspace-request-error__message {
  flex: 1 1 auto;
  order: 1;
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
  text-wrap: pretty;
  line-height: 1.45;
}
.workspace-request-error > button:not(.workspace-request-error__toggle) {
  order: 2;
  flex: 0 0 auto;
  min-height: 28px;
  padding: 0 10px;
  border: 1px solid var(--border-light);
  border-radius: 7px;
  color: var(--text-secondary);
  background: var(--surface-subtle);
  cursor: pointer;
  font-size: 10px;
  font-weight: 650;
  white-space: nowrap;
  transition: color 140ms ease, border-color 140ms ease, background-color 140ms ease, transform 140ms ease;
}
.workspace-request-error > button:not(.workspace-request-error__toggle):hover {
  border-color: color-mix(in srgb, var(--danger) 38%, var(--border-light));
  color: var(--danger);
  background: var(--surface-hover);
}
.workspace-request-error > button:not(.workspace-request-error__toggle):active { transform: translateY(1px); }
.workspace-request-error > button:not(.workspace-request-error__toggle):focus-visible {
  outline: 2px solid color-mix(in srgb, var(--danger) 55%, transparent);
  outline-offset: 2px;
}
.workspace-request-error__toggle {
  order: 3;
  display: grid;
  flex: 0 0 28px;
  place-items: center;
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 7px;
  color: var(--text-muted);
  background: transparent;
  cursor: pointer;
  font-size: 17px;
  line-height: 1;
  transition: color 140ms ease, border-color 140ms ease, background-color 140ms ease;
}
.workspace-request-error__toggle:hover,
.workspace-request-error__toggle:focus-visible {
  border-color: var(--border-light);
  color: var(--text-primary);
  background: var(--surface-subtle);
}
.workspace-request-error__toggle:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--danger) 55%, transparent);
  outline-offset: 2px;
}
.workspace-request-error.is-collapsed {
  align-items: center;
  justify-content: center;
  width: 42px;
  min-height: 46px;
  gap: 8px;
  padding: 8px 6px;
  border-radius: 12px;
  box-shadow: var(--shadow-md), 0 0 0 1px color-mix(in srgb, var(--danger) 9%, transparent) inset;
}
.workspace-request-error.is-collapsed .workspace-request-error__indicator {
  flex-basis: 7px;
  margin-top: 0;
}
.workspace-request-error.is-collapsed .workspace-request-error__message,
.workspace-request-error.is-collapsed > button:not(.workspace-request-error__toggle) {
  display: none;
}
.workspace-request-error.is-collapsed .workspace-request-error__toggle {
  order: 2;
}
@keyframes workspace-request-error-enter {
  from { opacity: 0; transform: translateX(16px); }
  to { opacity: 1; transform: translateX(0); }
}
@media (prefers-reduced-motion: reduce) {
  .workspace-request-error,
  .workspace-request-error__toggle,
  .workspace-request-error > button:not(.workspace-request-error__toggle) {
    animation: none;
    transition: none;
  }
}
@media (max-width: 760px) {
  .workspace-request-error {
    top: 10px;
    right: 12px;
    width: calc(100% - 24px);
  }
}
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
