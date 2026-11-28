<template>
  <section class="docking-workbench" aria-label="Mission 停靠工作区" @scroll.capture="scrollbars.onScroll">
    <Teleport :to="topbarTarget || 'body'" :disabled="!topbarTarget">
    <nav ref="layoutMenu" class="docking-workbench__toolbar" aria-label="工作区布局">
      <button class="docking-workbench__menu-trigger" type="button" aria-haspopup="menu" :aria-expanded="menuOpen" @click="menuOpen = !menuOpen">布局</button>
      <div v-if="menuOpen" class="docking-workbench__menu" role="menu" aria-label="布局选项">
      <button type="button" role="menuitemcheckbox" :aria-checked="arranging" @click="arranging = !arranging">{{ arranging ? '完成布局调整' : '调整布局' }}</button>
      <button v-for="id in DOCK_PANELS" :key="id" type="button" role="menuitemcheckbox" :aria-checked="!hidden.includes(id)"
        :disabled="!ready || !enabled(id)" @click="togglePanel(id)"><span aria-hidden="true">{{ hidden.includes(id) ? '○' : '✓' }}</span>{{ DOCK_TITLES[id] }}</button>
      <button type="button" role="menuitem" :disabled="!ready" @click="resetLayout(); menuOpen = false">恢复默认布局</button>
      </div>
    </nav>
    </Teleport>
    <div ref="canvas" class="docking-workbench__canvas" @mousedown.capture="blockMiddleClose" @auxclick.capture="blockMiddleClose">
    <DockviewVue style="width: 100%; height: 100%" :theme="theme" default-renderer="always"
      :hide-borders="true" :disable-floating-groups="true" :disable-tabs-overflow-list="true" @ready="onReady"
      >
      <template #panel-explorer><div class="docking-workbench__panel docking-workbench__panel--sidebar"><slot name="left" /></div></template>
      <template #panel-editor><div class="docking-workbench__panel"><slot name="main" v-bind="mainState" /></div></template>
      <template #panel-inspector><div class="docking-workbench__panel docking-workbench__panel--sidebar"><slot name="right" v-bind="rightState" /></div></template>
      <template #panel-bottom><div class="docking-workbench__panel"><slot name="bottom" v-bind="bottomState" /></div></template>
      <template #defaultTab="{ api: panelApi }">
        <div class="docking-workbench__tab">
          <span>{{ panelApi.title }}</span>
          <button type="button" :aria-label="`隐藏 ${panelApi.title}`" @pointerdown.stop @mousedown.stop
            @click.stop="hidePanel(panelApi.id as DockPanelId)">×</button>
        </div>
      </template>
    </DockviewVue>
    </div>
    <footer v-if="$slots['status-bar']" class="docking-workbench__status"><slot name="status-bar" v-bind="bottomState" /></footer>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, shallowRef, watch } from 'vue'
import { DockviewVue, type DockviewReadyEvent, type DockviewTheme, type SerializedDockview } from 'dockview-vue'
import 'dockview-vue/dist/styles/dockview.css'
import { createWorkspaceScrollbars } from './workspaceScrollbars'
import { DOCK_PANELS, DOCK_TITLES, cleanDockLayout, createDefaultDockLayout, readDockLayout,
  saveDockLayout, setDockPanelHidden, type DockPanelId } from './dockingLayout'

const props = withDefaults(defineProps<{ showLeft?: boolean; showRight?: boolean; showBottomPanel?: boolean }>(), {
  showLeft: true, showRight: true, showBottomPanel: true
})
const scrollbars = createWorkspaceScrollbars()
const theme: DockviewTheme = { name: 'zhiyi', className: 'dockview-theme-zhiyi', gap: 0,
  dndOverlayMounting: 'absolute', dndPanelOverlay: 'group' }
const api = shallowRef<DockviewReadyEvent['api'] | null>(null)
const canvas = ref<HTMLElement | null>(null)
const topbarTarget = shallowRef<HTMLElement | null>(null)
const layoutMenu = ref<HTMLElement | null>(null)
const menuOpen = ref(false)
const arranging = ref(false)
const closeLayoutMenu = (event: Event) => {
  if (event.type === 'keydown' ? (event as KeyboardEvent).key === 'Escape'
    : !layoutMenu.value?.contains(event.target as Node)) menuOpen.value = false
}
const ready = ref(false)
const hidden = ref<DockPanelId[]>([])
const maximized = ref(false)
const layoutRevision = ref(0)
let defaults: SerializedDockview | null = null
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
let restoring = false
let subscription: { dispose(): void } | undefined
const enabled = (id: DockPanelId) => id === 'explorer' ? props.showLeft : id === 'inspector' ? props.showRight : id === 'bottom' ? props.showBottomPanel : true
const persist = () => { if (api.value && !restoring) saveDockLayout(api.value, hidden.value) }
const scheduleSave = () => {
  if (restoring || disposed) return
  clearTimeout(timer)
  timer = setTimeout(persist, 250)
}
function setHidden(id: DockPanelId, value: boolean) {
  if (!api.value) return
  hidden.value = value ? [...new Set([...hidden.value, id])] : hidden.value.filter(item => item !== id)
  setDockPanelHidden(api.value, id, value || !enabled(id))
  maximized.value = false
  scheduleSave()
}
const hidePanel = (id: DockPanelId) => setHidden(id, true)
const togglePanel = (id: DockPanelId) => setHidden(id, !hidden.value.includes(id))
const restoreLeftPane = () => setHidden('explorer', false)
const toggleRightPane = () => setHidden('inspector', mainState.value.rightPaneVisible)
const setBottomPanelCollapsed = (value: boolean) => setHidden('bottom', value)
const toggleRightPaneMaximized = () => {
  const panel = api.value?.getPanel('inspector')
  if (!panel || hidden.value.includes('inspector')) return
  if (panel.api.isMaximized()) panel.api.exitMaximized()
  else panel.api.maximize()
  maximized.value = panel.api.isMaximized()
}
// Legacy slot contract, now driven by explicit Dockview panel visibility.
// Dockview resizes groups instead of automatically hiding narrow columns.
const panelVisible = (id: DockPanelId) => {
  void layoutRevision.value
  return enabled(id) && !hidden.value.includes(id) && (api.value?.getPanel(id)?.api.isVisible ?? true)
}
const mainState = computed(() => ({ leftAutoHidden: !panelVisible('explorer'), restoreLeftPane,
  rightAutoHidden: false, rightEnabled: props.showRight,
  rightPaneVisible: panelVisible('inspector'),
  rightCollapsedByUser: hidden.value.includes('inspector'), toggleRightPane }))
const rightState = computed(() => ({ rightPaneMaximized: maximized.value, toggleRightPaneMaximized, toggleRightPane }))
const bottomState = computed(() => ({ collapsed: !panelVisible('bottom'),
  setCollapsed: setBottomPanelCollapsed, toggleCollapsed: () => setBottomPanelCollapsed(!bottomState.value.collapsed) }))
const applyVisibility = () => {
  if (!api.value) return
  for (const group of api.value.groups) group.api.setVisible(true)
  for (const id of DOCK_PANELS) if (hidden.value.includes(id) || !enabled(id)) setDockPanelHidden(api.value, id, true)
}
const updateHeaders = () => {
  if (!api.value) return
  for (const group of api.value.groups) {
    const hide = !arranging.value && group.panels.length === 1
    if (group.header.hidden !== hide) group.header.hidden = hide
  }
}
watch(arranging, updateHeaders)
function onReady(event: DockviewReadyEvent) {
  api.value = event.api
  restoring = true
  createDefaultDockLayout(event.api)
  defaults = cleanDockLayout(event.api.toJSON())
  const saved = readDockLayout()
  if (saved) {
    try {
      event.api.fromJSON(saved.layout, { reuseExistingPanels: true })
      hidden.value = saved.hidden
    } catch {
      event.api.fromJSON(defaults, { reuseExistingPanels: true })
      hidden.value = []
    }
  }
  applyVisibility()
  updateHeaders()
  restoring = false
  ready.value = true
  subscription = event.api.onDidLayoutChange(() => {
    updateHeaders()
    layoutRevision.value++
    maximized.value = Boolean(event.api.getPanel('inspector')?.api.isMaximized())
    scheduleSave()
  })
  scheduleSave()
}
function resetLayout() {
  if (!api.value || !defaults) return
  restoring = true
  api.value.fromJSON(defaults, { reuseExistingPanels: true })
  hidden.value = []
  maximized.value = false
  applyVisibility()
  updateHeaders()
  restoring = false
  scheduleSave()
}
watch(() => [props.showLeft, props.showRight, props.showBottomPanel], () => {
  if (!api.value) return
  for (const id of DOCK_PANELS) setDockPanelHidden(api.value, id, hidden.value.includes(id) || !enabled(id))
})
function blockMiddleClose(event: MouseEvent) {
  if (event.button === 1) { event.preventDefault(); event.stopPropagation() }
}
onMounted(async () => {
  document.addEventListener('pointerdown', closeLayoutMenu)
  document.addEventListener('keydown', closeLayoutMenu)
  await nextTick()
  if (!disposed) topbarTarget.value = document.getElementById('mission-workspace-layout-menu')
})
onDeactivated(() => { scrollbars.clear(); clearTimeout(timer); persist(); menuOpen.value = false; topbarTarget.value = null })
onActivated(async () => {
  await nextTick()
  if (!disposed) topbarTarget.value = document.getElementById('mission-workspace-layout-menu')
  if (!disposed && canvas.value) api.value?.layout(canvas.value.clientWidth, canvas.value.clientHeight)
})
onBeforeUnmount(() => {
  scrollbars.clear()
  clearTimeout(timer)
  persist()
  disposed = true
  subscription?.dispose()
  document.removeEventListener('pointerdown', closeLayoutMenu)
  document.removeEventListener('keydown', closeLayoutMenu)
  api.value = null
})
defineExpose({ restoreLeftPane, toggleRightPane, setBottomPanelCollapsed, resetLayout })
</script>

<style scoped>
.docking-workbench { display: flex; flex-direction: column; width: 100%; height: 100%; min-width: 0; min-height: 0; overflow: hidden; background: var(--wb-surface-shell); color: var(--wb-text); }
.docking-workbench__canvas { flex: 1 1 auto; min-height: 0; min-width: 0; }
.docking-workbench__panel { height: 100%; width: 100%; min-width: 0; min-height: 0; overflow: hidden; display: flex; flex-direction: column; }
.docking-workbench__panel--sidebar { background: var(--wb-surface-1); }
.docking-workbench__toolbar { position: relative; flex: 0 0 auto; color: var(--text-secondary); font: 500 14px var(--font-sans); -webkit-app-region: no-drag; }
.docking-workbench__toolbar button { border: 0; border-radius: 4px; padding: 5px 8px; color: inherit; background: transparent; cursor: pointer; font: inherit; -webkit-app-region: no-drag; }
.docking-workbench__toolbar .docking-workbench__menu-trigger { height: 28px; padding: 0 8px; color: var(--app-topbar-muted); font: 520 13px var(--font-serif); white-space: nowrap; }
.docking-workbench__toolbar button:hover:not(:disabled) { color: var(--text-primary); background: var(--wb-hover); }
.docking-workbench__menu { position: absolute; top: 100%; left: 0; z-index: 1000; min-width: 180px; padding: 5px; border: 1px solid var(--wb-border); border-radius: 7px; background: var(--bg-card); color: var(--text-primary); box-shadow: 0 8px 24px rgb(0 0 0 / 20%); }
.docking-workbench__menu button { display: flex; align-items: center; gap: 12px; width: 100%; text-align: left; white-space: nowrap; font-size: 12px; }
.docking-workbench__menu button:last-child { border-top: 1px solid var(--wb-border-soft); margin-top: 4px; border-radius: 0; }
.docking-workbench__toolbar button:disabled { opacity: .45; cursor: default; }
.docking-workbench__status { flex: 0 0 auto; }
.docking-workbench__tab { display: flex; align-items: center; gap: 14px; height: 100%; padding: 0 10px; font: 12px var(--font-sans); }
.docking-workbench__tab button { padding: 0 3px; border: 0; background: transparent; color: inherit; cursor: pointer; font-size: 16px; }
.docking-workbench button:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: -2px; }
</style>

<style>
@property --workspace-scrollbar-ink {
  syntax: '<color>';
  inherits: true;
  initial-value: transparent;
}
.docking-workbench * { --workspace-scrollbar-ink: transparent; }
.docking-workbench .workspace-scroll-owner { transition: --workspace-scrollbar-ink 180ms ease; }
.docking-workbench .workspace-scroll-active { --workspace-scrollbar-ink: var(--scrollbar-thumb); }
.docking-workbench ::-webkit-scrollbar-thumb { background: var(--workspace-scrollbar-ink) !important; }
.docking-workbench ::-webkit-scrollbar-thumb:hover,
.docking-workbench ::-webkit-scrollbar-thumb:active { background: var(--scrollbar-thumb-hover) !important; }
.docking-workbench ::-webkit-scrollbar-track,
.docking-workbench ::-webkit-scrollbar-corner { background: transparent !important; }
@media (prefers-reduced-motion: reduce) {
  .docking-workbench .workspace-scroll-owner { transition: none; }
}
.dockview-theme-zhiyi {
  --dv-background-color: var(--wb-surface-shell);
  --dv-group-view-background-color: var(--wb-surface-shell);
  --dv-tabs-and-actions-container-background-color: var(--wb-surface-shell);
  --dv-activegroup-visiblepanel-tab-background-color: var(--wb-surface-2);
  --dv-activegroup-hiddenpanel-tab-background-color: var(--wb-surface-shell);
  --dv-inactivegroup-visiblepanel-tab-background-color: var(--wb-surface-1);
  --dv-inactivegroup-hiddenpanel-tab-background-color: var(--wb-surface-shell);
  --dv-activegroup-visiblepanel-tab-color: var(--wb-text);
  --dv-activegroup-hiddenpanel-tab-color: var(--wb-text-muted);
  --dv-inactivegroup-visiblepanel-tab-color: var(--wb-text-secondary);
  --dv-inactivegroup-hiddenpanel-tab-color: var(--wb-text-muted);
  --dv-tab-divider-color: transparent;
  --dv-tabs-and-actions-container-height: 30px;
  --dv-tab-font-size: 12px;
  --dv-separator-border: transparent;
  --dv-active-sash-color: var(--wb-accent);
  --dv-drag-over-background-color: color-mix(in srgb, var(--wb-accent) 18%, transparent);
  --dv-drag-over-border-color: var(--wb-accent);
  --dv-icon-hover-background-color: var(--wb-hover);
  --dv-paneview-header-border-color: var(--wb-border-soft);
  --dv-sash-size: 5px;
}
.dockview-theme-zhiyi .dv-tab.dv-active-tab { box-shadow: inset 0 2px var(--wb-accent); }
</style>
