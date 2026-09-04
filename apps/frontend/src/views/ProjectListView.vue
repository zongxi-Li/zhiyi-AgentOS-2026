<template>
  <WorkbenchLayout :show-left="false" :show-right="false" storage-key="zhiyi.projects.layout.v1">
    <template #main>
      <main class="project-list" aria-label="Projects">
        <header class="project-list__header">
          <div>
            <span class="project-list__eyebrow">PROJECTS</span>
            <h1>工程项目</h1>
            <p>每个项目拥有独立的 Mission、Runs 与只读交付物。</p>
          </div>
          <button class="project-list__create" type="button" @click="createMission">
            <el-icon aria-hidden="true"><Plus /></el-icon>
            <span>新建工程</span>
          </button>
        </header>

        <section class="project-list__toolbar" aria-label="项目筛选">
          <label class="project-list__search">
            <el-icon aria-hidden="true"><Search /></el-icon>
            <input v-model="searchText" type="search" placeholder="搜索项目名称或 Mission ID" />
          </label>
          <div class="project-list__toolbar-actions">
            <span class="project-list__count">{{ filteredMissions.length }} 个项目</span>
            <div class="project-view-toggle" role="group" aria-label="项目显示方式">
              <button
                type="button"
                data-view-mode="list"
                :class="{ 'is-active': viewMode === 'list' }"
                :aria-pressed="viewMode === 'list'"
                title="宽版列表"
                @click="setViewMode('list')"
              >
                <el-icon aria-hidden="true"><List /></el-icon><span>列表</span>
              </button>
              <button
                type="button"
                data-view-mode="grid"
                :class="{ 'is-active': viewMode === 'grid' }"
                :aria-pressed="viewMode === 'grid'"
                title="项目网格"
                @click="setViewMode('grid')"
              >
                <el-icon aria-hidden="true"><Grid /></el-icon><span>网格</span>
              </button>
            </div>
          </div>
        </section>

        <section v-if="loading && !missions.length" class="project-list__state" role="status">
          <strong>正在加载项目</strong>
          <span>读取 Mission Project 列表…</span>
        </section>
        <section v-else-if="errorMessage" class="project-list__state project-list__state--error" role="alert">
          <strong>项目列表暂时不可用</strong>
          <span>{{ errorMessage }}</span>
          <button type="button" @click="loadMissions">重新加载</button>
        </section>
        <section v-else-if="!filteredMissions.length" class="project-list__state" role="status">
          <strong>{{ searchText ? '没有匹配的项目' : '还没有工程项目' }}</strong>
          <span>{{ searchText ? '换一个名称或 Mission ID 试试。' : '创建第一个 Mission，开始一次运行。' }}</span>
          <button v-if="!searchText" type="button" @click="createMission">新建工程</button>
        </section>
        <section v-else class="project-list__rows" :class="{ 'is-grid': viewMode === 'grid' }" aria-label="Mission Projects">
          <div
            v-for="mission in filteredMissions"
            :key="mission.missionId"
            class="project-row"
            :class="{ 'is-grid': viewMode === 'grid' }"
            role="button"
            tabindex="0"
            :aria-label="`打开项目：${mission.title || '未命名工程'}`"
            @click="openMission(mission)"
            @keydown.enter="handleProjectRowKeydown($event, mission)"
            @keydown.space="handleProjectRowKeydown($event, mission)"
            @contextmenu.prevent="openActionMenu($event, mission)"
          >
            <span class="project-row__icon" aria-hidden="true"><el-icon><FolderOpened /></el-icon></span>
            <span class="project-row__copy">
              <strong :title="mission.title">{{ mission.title || '未命名工程' }}</strong>
              <span>{{ mission.missionId }}</span>
            </span>
            <span class="project-row__meta">
              <span class="project-row__status" :class="`is-${statusTone(mission)}`">
                <i aria-hidden="true"></i>{{ statusLabel(mission) }}
              </span>
              <span>{{ mission.runCount }} 次运行</span>
              <time :datetime="mission.updatedAt">{{ formatDate(mission.updatedAt) }}</time>
            </span>
            <button
              class="project-row__actions"
              type="button"
              aria-haspopup="menu"
              aria-controls="project-action-menu"
              :aria-expanded="actionMenu.mission?.missionId === mission.missionId"
              :aria-label="`打开${mission.title || '未命名工程'}的任务操作`"
              @click.stop="openActionMenu($event, mission)"
              @contextmenu.prevent.stop="openActionMenu($event, mission)"
            >
              <el-icon><MoreFilled /></el-icon>
            </button>
            <span class="project-row__arrow" aria-hidden="true">›</span>
          </div>
        </section>
      </main>
    </template>
  </WorkbenchLayout>

  <Teleport to="body">
    <div
      v-if="actionMenu.mission"
      id="project-action-menu"
      ref="actionMenuElement"
      class="project-action-menu"
      role="menu"
      aria-label="项目操作"
      :style="{ left: `${actionMenu.x}px`, top: `${actionMenu.y}px` }"
    >
      <button type="button" role="menuitem" data-action="open" @click="openActionMission">
        <el-icon><View /></el-icon><span>打开项目</span>
      </button>
      <button type="button" role="menuitem" data-action="copy" @click="copyActionMissionId">
        <el-icon><CopyDocument /></el-icon><span>复制 Mission ID</span>
      </button>
      <div class="project-action-menu__separator"></div>
      <button
        type="button"
        role="menuitem"
        data-action="archive"
        :disabled="!isTerminalMission(actionMenu.mission)"
        :title="mutationDisabledReason(actionMenu.mission)"
        @click="archiveActionMission"
      >
        <el-icon><FolderAdd /></el-icon><span>归档任务</span>
      </button>
      <button
        class="is-danger"
        type="button"
        role="menuitem"
        data-action="delete"
        :disabled="!isTerminalMission(actionMenu.mission)"
        :title="mutationDisabledReason(actionMenu.mission)"
        @click="deleteActionMission"
      >
        <el-icon><DeleteIcon /></el-icon><span>删除任务</span>
      </button>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, h, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { CopyDocument, Delete as DeleteIcon, FolderAdd, FolderOpened, Grid, List, MoreFilled, Plus, Search, View } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import WorkbenchLayout from '@/components/workbench/WorkbenchLayout.vue'
import { agentosApi, type MissionListItem } from '@/services/api/agentos'

const router = useRouter()
const missions = ref<MissionListItem[]>([])
const searchText = ref('')
const loading = ref(false)
const errorMessage = ref('')
let controller: AbortController | null = null
const actionMenu = reactive<{ mission: MissionListItem | null; x: number; y: number }>({ mission: null, x: 0, y: 0 })
const actionMenuElement = ref<HTMLElement | null>(null)
type ProjectViewMode = 'list' | 'grid'
const PROJECT_VIEW_MODE_STORAGE_KEY = 'zhiyi.projects.view-mode.v1'
const viewMode = ref<ProjectViewMode>(
  typeof window !== 'undefined' && window.localStorage.getItem(PROJECT_VIEW_MODE_STORAGE_KEY) === 'grid' ? 'grid' : 'list'
)

const filteredMissions = computed(() => {
  const query = searchText.value.trim().toLocaleLowerCase()
  if (!query) return missions.value
  return missions.value.filter(mission => [mission.title, mission.missionId, mission.description]
    .some(value => value.toLocaleLowerCase().includes(query)))
})

const statusTone = (mission: MissionListItem) => {
  const status = mission.latestRunStatus || mission.status
  if (['completed', 'succeeded'].includes(status)) return 'success'
  if (['failed', 'cancelled'].includes(status)) return 'danger'
  if (['running', 'planning', 'pending', 'waiting_review', 'retrying'].includes(status)) return 'active'
  return 'muted'
}

const statusLabel = (mission: MissionListItem) => {
  const status = mission.latestRunStatus || mission.status
  return ({
    completed: '已完成', succeeded: '已完成', running: '运行中', planning: '规划中',
    pending: '待启动', waiting_review: '待审核', retrying: '重试中', failed: '失败',
    cancelled: '已取消', archived: '已归档', created: '已创建'
  } as Record<string, string>)[status] || status || '未知'
}

const formatDate = (value: string) => {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)
}

const missionIdentity = (mission: MissionListItem) => mission.missionId
const isTerminalMission = (mission: MissionListItem) => {
  if (mission.runCount === 0) return true
  const status = mission.latestRunStatus || mission.status
  return ['completed', 'succeeded', 'failed', 'cancelled', 'superseded'].includes(status)
}
const mutationDisabledReason = (mission: MissionListItem) => (
  isTerminalMission(mission) ? '' : '运行中的任务不能归档或删除'
)

const loadMissions = async () => {
  controller?.abort()
  controller = new AbortController()
  const requestController = controller
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await agentosApi.listMissions({ page: 1, pageSize: 100 }, { signal: requestController.signal })
    if (requestController.signal.aborted) return
    missions.value = response.items
  } catch (error: any) {
    if (requestController.signal.aborted || error?.name === 'CanceledError' || error?.name === 'AbortError') return
    errorMessage.value = error?.response?.data?.detail || error?.message || '请稍后重试。'
  } finally {
    if (controller === requestController && !requestController.signal.aborted) loading.value = false
  }
}

const openMission = (mission: MissionListItem) => {
  closeActionMenu()
  void router.push({
    name: 'MissionWorkspace',
    params: { missionId: mission.missionId },
    query: mission.latestRunId ? { runId: mission.latestRunId } : undefined
  })
}

const handleProjectRowKeydown = (event: KeyboardEvent, mission: MissionListItem) => {
  if (event.target !== event.currentTarget) return
  event.preventDefault()
  openMission(mission)
}

const createMission = () => {
  void router.push({ name: 'CreateMission' })
}

const setViewMode = (mode: ProjectViewMode) => {
  viewMode.value = mode
  window.localStorage.setItem(PROJECT_VIEW_MODE_STORAGE_KEY, mode)
}

const closeActionMenu = () => { actionMenu.mission = null }

const openActionMenu = async (event: MouseEvent, mission: MissionListItem) => {
  actionMenu.mission = mission
  const target = event.currentTarget as HTMLElement | null
  const rect = target?.getBoundingClientRect()
  actionMenu.x = event.clientX || (rect ? rect.right - 184 : 8)
  actionMenu.y = event.clientY || (rect ? rect.bottom + 6 : 8)
  await nextTick()
  const menu = actionMenuElement.value
  if (!menu) return
  actionMenu.x = Math.max(8, Math.min(actionMenu.x, window.innerWidth - menu.offsetWidth - 8))
  actionMenu.y = Math.max(8, Math.min(actionMenu.y, window.innerHeight - menu.offsetHeight - 8))
}

const copyMissionId = async (missionId: string) => {
  try {
    if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable')
    await navigator.clipboard.writeText(missionId)
    ElMessage.success('Mission ID 已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择 Mission ID')
  }
}

const openActionMission = () => {
  const mission = actionMenu.mission
  if (!mission) return
  closeActionMenu()
  void openMission(mission)
}

const copyActionMissionId = () => {
  const mission = actionMenu.mission
  if (!mission) return
  closeActionMenu()
  void copyMissionId(missionIdentity(mission))
}

const missionMutationError = (error: unknown, action: string) => {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown; message?: unknown } } })?.response
  const detail = [response?.data?.message, response?.data?.detail]
    .find(value => typeof value === 'string' && value.trim())
  if (response?.status === 409 && detail === 'mission has active runs') {
    return `任务仍有活动执行，暂时不能${action}`
  }
  if (response?.status === 404) return '任务不存在或当前账户无权操作'
  return typeof detail === 'string' ? `${action}失败：${detail.slice(0, 160)}` : `任务${action}失败，请稍后重试`
}

const removeMission = (missionId: string) => {
  missions.value = missions.value.filter(mission => mission.missionId !== missionId)
}

const missionDisplayTitle = (mission: MissionListItem) => {
  const title = mission.title?.replace(/\s+/g, ' ').trim()
  return title || '未命名工程'
}

const missionDeleteMessage = (mission: MissionListItem) => {
  const title = missionDisplayTitle(mission)
  return h('div', { class: 'mission-delete-message' }, [
    h('p', { class: 'mission-delete-message__prompt' }, '确定删除以下任务？'),
    h('p', { class: 'mission-delete-message__title', 'aria-label': title }, title),
    h('p', { class: 'mission-delete-message__note' }, '删除后，执行审计事实仍会保留。')
  ])
}

const showMissionSuccess = (message: string) => {
  ElMessage({
    message,
    type: 'success',
    customClass: 'mission-toast mission-toast--success',
    duration: 2400,
    showClose: false,
    offset: 18
  })
}

const archiveActionMission = async () => {
  const mission = actionMenu.mission
  if (!mission || !isTerminalMission(mission)) return
  try {
    await agentosApi.archiveMission(missionIdentity(mission))
    removeMission(missionIdentity(mission))
    closeActionMenu()
    showMissionSuccess('任务已归档')
  } catch (error: unknown) {
    ElMessage.error(missionMutationError(error, '归档'))
  }
}

const deleteActionMission = async () => {
  const mission = actionMenu.mission
  if (!mission || !isTerminalMission(mission)) return
  try {
    await ElMessageBox.confirm(
      missionDeleteMessage(mission),
      '删除任务',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
        customClass: 'apple-delete-message-box',
        modalClass: 'apple-delete-message-box__overlay',
        confirmButtonClass: 'apple-delete-confirm-button',
        cancelButtonClass: 'apple-delete-cancel-button',
        roundButton: true,
        showClose: true,
        closeOnClickModal: true
      }
    )
  } catch {
    return
  }
  try {
    await agentosApi.deleteMission(missionIdentity(mission))
    removeMission(missionIdentity(mission))
    closeActionMenu()
    showMissionSuccess('任务已删除')
  } catch (error: unknown) {
    ElMessage.error(missionMutationError(error, '删除'))
  }
}

const handleActionDismiss = (event: PointerEvent) => {
  if (!actionMenuElement.value?.contains(event.target as Node)) closeActionMenu()
}
const handleActionKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Escape') closeActionMenu()
}

onMounted(() => {
  window.addEventListener('pointerdown', handleActionDismiss)
  window.addEventListener('keydown', handleActionKeydown)
  void loadMissions()
})
onBeforeUnmount(() => {
  controller?.abort()
  window.removeEventListener('pointerdown', handleActionDismiss)
  window.removeEventListener('keydown', handleActionKeydown)
})
</script>

<style scoped>
.project-list { display: flex; flex-direction: column; width: 100%; min-height: 100%; padding: 34px clamp(24px, 5vw, 76px) 56px; color: var(--text-primary); background: var(--bg-app); }
.project-list__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; max-width: 1040px; width: 100%; margin: 0 auto; padding-bottom: 28px; }
.project-list__eyebrow { color: var(--primary-color); font: 10px var(--font-mono, monospace); letter-spacing: .14em; }
.project-list h1 { margin: 8px 0 5px; font-size: 25px; line-height: 1.2; }
.project-list__header p { margin: 0; color: var(--text-secondary); font-size: 12px; }
.project-list__create, .project-list__state button { display: inline-flex; align-items: center; gap: 7px; border: 1px solid var(--primary-color); border-radius: 7px; padding: 10px 15px; color: #fff; background: var(--primary-color); cursor: pointer; font-size: 12px; }
.project-list__create:hover, .project-list__state button:hover { filter: brightness(.96); }
.project-list__toolbar, .project-list__rows, .project-list__state { max-width: 1040px; width: 100%; margin: 0 auto; }
.project-list__toolbar { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 12px 0; border-top: 1px solid var(--border-light); border-bottom: 1px solid var(--border-light); }
.project-list__search { display: flex; align-items: center; gap: 8px; width: min(390px, 100%); color: var(--text-muted); }
.project-list__search input { width: 100%; border: 0; outline: 0; color: var(--text-primary); background: transparent; font-size: 12px; }
.project-list__toolbar-actions { display: flex; align-items: center; gap: 16px; }
.project-list__count { color: var(--text-muted); font: 10px var(--font-mono, monospace); }
.project-view-toggle { display: inline-flex; align-items: center; gap: 2px; padding: 2px; border: 1px solid var(--border-light); border-radius: 7px; background: var(--surface-subtle); }
.project-view-toggle button { display: inline-flex; align-items: center; justify-content: center; gap: 5px; min-width: 58px; height: 26px; padding: 0 8px; border: 0; border-radius: 5px; color: var(--text-muted); background: transparent; cursor: pointer; font-size: 10px; }
.project-view-toggle button:hover, .project-view-toggle button:focus-visible { color: var(--text-primary); outline: none; }
.project-view-toggle button.is-active { color: var(--primary-color); background: var(--surface-solid); box-shadow: var(--shadow-sm); }
.project-list__rows { padding-top: 10px; }
.project-row { display: grid; grid-template-columns: 34px minmax(0, 1fr) auto 30px 18px; align-items: center; gap: 14px; width: 100%; min-height: 74px; padding: 12px 13px; border-bottom: 1px solid var(--border-light); color: inherit; background: transparent; text-align: left; cursor: pointer; }
.project-row:hover, .project-row:focus-visible { background: var(--primary-fade); }
.project-row:focus-visible { outline: 2px solid var(--primary-line); outline-offset: -2px; }
.project-row__icon { display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; border: 1px solid var(--primary-line); border-radius: 7px; color: var(--primary-color); background: var(--primary-fade); }
.project-row__copy { min-width: 0; }
.project-row__copy strong, .project-row__copy span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.project-row__copy strong { font-size: 13px; }
.project-row__copy span { margin-top: 4px; color: var(--text-muted); font: 10px var(--font-mono, monospace); }
.project-row__meta { display: flex; align-items: center; gap: 20px; color: var(--text-secondary); font-size: 11px; white-space: nowrap; }
.project-row__status { display: inline-flex; align-items: center; gap: 6px; }
.project-row__status i { width: 6px; height: 6px; border-radius: 50%; background: var(--text-muted); }
.project-row__status.is-success i { background: var(--success); }
.project-row__status.is-active i { background: var(--primary-color); }
.project-row__status.is-danger i { background: var(--danger); }
.project-row__actions { display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; padding: 0; border: 0; border-radius: 6px; color: var(--text-muted); background: transparent; cursor: pointer; opacity: .58; }
.project-row__actions:hover, .project-row__actions:focus-visible { color: var(--primary-color); background: var(--surface-solid); opacity: 1; outline: none; }
.project-row__arrow { color: var(--text-muted); font-size: 21px; }
.project-list__rows.is-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; padding-top: 16px; }
.project-row.is-grid { grid-template-columns: 34px minmax(0, 1fr) 30px 18px; align-content: center; min-height: 142px; padding: 16px; border: 1px solid var(--border-light); border-radius: var(--radius-card); background: var(--surface-raised); box-shadow: var(--shadow-sm); }
.project-row.is-grid:hover, .project-row.is-grid:focus-visible { border-color: var(--primary-line); box-shadow: var(--shadow-md); }
.project-row.is-grid .project-row__copy strong { font-size: 12px; line-height: 1.45; white-space: normal; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.project-row.is-grid .project-row__meta { grid-column: 1 / -1; gap: 12px; justify-content: space-between; width: 100%; padding-top: 10px; border-top: 1px solid var(--border-light); font-size: 10px; }
.project-row.is-grid .project-row__meta time { margin-left: auto; }
.project-row.is-grid .project-row__actions { grid-column: 3; grid-row: 1; }
.project-row.is-grid .project-row__arrow { grid-column: 4; grid-row: 1; }
.project-list__state { display: grid; justify-items: center; gap: 8px; padding: 100px 20px; color: var(--text-secondary); text-align: center; }
.project-list__state strong { color: var(--text-primary); font-size: 15px; }
.project-list__state span { font-size: 12px; }
.project-list__state button { margin-top: 8px; }
.project-list__state--error strong { color: var(--danger); }
@media (max-width: 960px) { .project-list__rows.is-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 720px) { .project-list { padding: 24px 18px 40px; } .project-list__header { display: block; } .project-list__create { margin-top: 18px; } .project-list__toolbar-actions { gap: 8px; } .project-view-toggle button { min-width: 30px; padding: 0 7px; } .project-view-toggle button span { display: none; } .project-row { grid-template-columns: 34px minmax(0, 1fr) 30px 18px; } .project-row__meta { grid-column: 2 / 3; gap: 12px; margin-top: -8px; font-size: 10px; } .project-row__actions { grid-column: 3; grid-row: 1 / 3; } .project-row__arrow { grid-column: 4; grid-row: 1 / 3; } .project-list__rows.is-grid { grid-template-columns: 1fr; } .project-row.is-grid { grid-template-columns: 34px minmax(0, 1fr) 30px 18px; } .project-row.is-grid .project-row__meta { grid-column: 1 / -1; margin-top: 0; } }
</style>

<style>
.project-action-menu { position: fixed; z-index: 3000; box-sizing: border-box; width: 190px; padding: 5px; border: 1px solid var(--border-light); border-radius: var(--radius-card); background: var(--bg-card); box-shadow: var(--shadow-lg); color: var(--text-primary); animation: project-action-menu-in 180ms var(--ease-out) both; }
.project-action-menu button { width: 100%; min-height: 32px; display: grid; grid-template-columns: 20px minmax(0, 1fr); align-items: center; gap: 6px; padding: 0 9px; border: 0; border-radius: var(--radius-control); background: transparent; color: inherit; font: inherit; font-size: 12px; text-align: left; cursor: pointer; }
.project-action-menu button:hover:not(:disabled), .project-action-menu button:focus-visible { background: var(--primary-fade); color: var(--primary-color); outline: none; }
.project-action-menu button.is-danger { color: var(--danger); }
.project-action-menu button:disabled { color: var(--text-disabled); cursor: not-allowed; }
.project-action-menu__separator { height: 1px; margin: 4px 6px; background: var(--border-light); }
@keyframes project-action-menu-in { from { opacity: 0; transform: translateY(-4px) scale(.98); } to { opacity: 1; transform: translateY(0) scale(1); } }
@media (prefers-reduced-motion: reduce) { .project-action-menu { animation: none; } }
</style>
