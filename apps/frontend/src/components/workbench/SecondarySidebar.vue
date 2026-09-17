<template>
  <aside class="secondary-sidebar" aria-label="Secondary Sidebar">
    <header class="secondary-sidebar__header">
      <div class="secondary-sidebar__heading">
        <span>INSPECTOR</span>
        <strong :title="title">{{ title }}</strong>
      </div>
      <span v-if="historical" class="secondary-sidebar__badge">Historical</span>
    </header>

    <nav class="secondary-sidebar__tabs" aria-label="Inspector views" role="tablist">
      <button
        v-for="view in views"
        :key="view.id"
        type="button"
        role="tab"
        :aria-selected="activeView?.id === view.id"
        :class="{ 'is-active': activeView?.id === view.id }"
        @click="selectView(view.id)"
      >
        {{ view.title }}
      </button>
    </nav>

    <div class="secondary-sidebar__body">
      <component
        v-if="activeView"
        :is="activeViewComponent"
        :key="`${activeView.id}:${contextKey}`"
        v-bind="activeViewProps"
        @locate-graph="emit('locateGraph')"
      />
      <div v-else class="secondary-sidebar__empty">没有可用的观察视角。</div>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { computed, markRaw, ref, toRaw, watch } from 'vue'
import type { WorkbenchInspectorContext, SecondarySidebarViewContribution } from '@/workbench/types'
import type { WorkbenchContributionRegistry } from '@/workbench/registry'

const props = withDefaults(defineProps<{
  registry: WorkbenchContributionRegistry
  context: WorkbenchInspectorContext
  title: string
  historical?: boolean
  componentProps?: Record<string, unknown>
  storageKey?: string
}>(), {
  historical: false,
  componentProps: () => ({}),
  storageKey: 'zhiyi.mission.workspace.secondary-sidebar.view.v1'
})

const emit = defineEmits<{ locateGraph: [] }>()

const readStoredViewId = () => {
  try {
    return localStorage.getItem(props.storageKey) || ''
  } catch {
    return ''
  }
}

const activeViewId = ref(readStoredViewId())
const views = computed<SecondarySidebarViewContribution[]>(() => props.registry.resolveSecondarySidebarViews(props.context).map(view => ({
  ...view,
  component: markRaw(toRaw(view.component))
})))
const activeView = computed(() => views.value.find(view => view.id === activeViewId.value) || views.value[0] || null)
const activeViewComponent = computed(() => activeView.value?.component || null)
const contextKey = computed(() => [
  props.context.runId,
  props.context.activeEditorId,
  props.context.activeEntryKind,
  props.context.selectedSemanticTaskKey,
  props.context.selectedAcgNodeId,
  props.context.selectedArtifactId
].map(value => value || '').join('|'))
const activeViewProps = computed(() => ({
  ...props.componentProps,
  context: props.context,
  ...(activeView.value?.getProps?.(props.context) || {})
}))

const persistViewId = (viewId: string) => {
  try {
    localStorage.setItem(props.storageKey, viewId)
  } catch {
    // Local storage is a convenience only; the active view remains in memory.
  }
}

const selectView = (viewId: string) => {
  activeViewId.value = viewId
  persistViewId(viewId)
}

watch(views, nextViews => {
  if (nextViews.some(view => view.id === activeViewId.value)) return
  const nextView = nextViews[0]
  if (nextView) {
    activeViewId.value = nextView.id
    persistViewId(nextView.id)
  }
}, { immediate: true })
</script>

<style scoped>
.secondary-sidebar { display: flex; flex-direction: column; min-width: 0; min-height: 0; height: 100%; color: var(--wb-text); background: var(--wb-surface-shell); }
.secondary-sidebar__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; min-height: 70px; padding: 12px 16px 10px; border-bottom: 1px solid var(--wb-border-soft); background: var(--wb-surface-pane); }
.secondary-sidebar__heading { min-width: 0; }
.secondary-sidebar__heading span { display: block; color: var(--wb-accent); font: 10px var(--font-mono, monospace); letter-spacing: .12em; }
.secondary-sidebar__heading strong { display: block; max-width: 240px; margin-top: 6px; overflow: hidden; font-size: 17px; font-weight: 700; line-height: 1.2; text-overflow: ellipsis; white-space: nowrap; }
.secondary-sidebar__badge { flex: 0 0 auto; padding: 3px 6px; border: 1px solid var(--wb-border); border-radius: var(--wb-radius-sm); color: var(--wb-warning); font: 10px var(--font-mono, monospace); }
.secondary-sidebar__tabs { display: flex; align-self: flex-start; flex: 0 1 auto; width: min(460px, calc(100% - 28px)); max-width: calc(100% - 28px); gap: 2px; min-height: 38px; margin: 8px 14px 9px; padding: 2px; border: 1px solid var(--wb-border-soft); border-radius: 9px; background: var(--wb-surface-inset); box-shadow: inset 0 1px 3px color-mix(in srgb, #000 28%, transparent), 0 1px 3px color-mix(in srgb, #000 24%, transparent); overflow-x: auto; scrollbar-width: none; }
.secondary-sidebar__tabs::-webkit-scrollbar { display: none; }
.secondary-sidebar__tabs button { flex: 1 0 auto; min-height: 32px; padding: 0 9px; border: 1px solid transparent; border-radius: 7px; color: var(--wb-text-muted); background: transparent; cursor: pointer; font-size: 12px; font-weight: 500; white-space: nowrap; transition: color 140ms var(--ease-out), background 140ms var(--ease-out), box-shadow 140ms var(--ease-out), transform 140ms var(--ease-out); }
.secondary-sidebar__tabs button:hover { color: var(--wb-text-secondary); background: var(--wb-hover); }
.secondary-sidebar__tabs button.is-active { border-color: color-mix(in srgb, var(--wb-accent) 46%, var(--wb-border-soft)); color: var(--wb-accent); background: color-mix(in srgb, var(--wb-accent) 10%, var(--wb-surface-section)); box-shadow: 0 2px 8px color-mix(in srgb, #000 30%, transparent), 0 0 0 1px color-mix(in srgb, var(--wb-accent) 14%, transparent) inset; font-weight: 650; }
.secondary-sidebar__tabs button:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: -1px; }
.secondary-sidebar__body { flex: 1 1 auto; min-height: 0; overflow: auto; padding: 8px 14px 18px; background: var(--wb-surface-shell); scrollbar-gutter: stable; overscroll-behavior: contain; }
.secondary-sidebar__body :deep(.inspector-section) { margin-bottom: 10px; }
.secondary-sidebar__body :deep(.inspector-section:last-child) { margin-bottom: 0; }
.secondary-sidebar__empty { display: grid; place-items: center; min-height: 160px; padding: 22px 14px; color: var(--wb-text-muted); font-size: 12px; text-align: center; }
</style>
