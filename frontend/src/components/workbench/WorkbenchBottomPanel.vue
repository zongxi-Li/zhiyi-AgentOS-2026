<template>
  <section
    class="workbench-bottom-panel"
    :class="{ 'is-collapsed': collapsed }"
    aria-label="运行底部面板"
  >
    <header class="workbench-bottom-panel__header">
      <nav class="workbench-bottom-panel__tabs" role="tablist" aria-label="运行面板视图">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          class="workbench-bottom-panel__tab"
          :class="{ active: activeTab === tab.id }"
          type="button"
          role="tab"
          :aria-selected="activeTab === tab.id"
          @click="activeTab = tab.id"
        >
          <span>{{ tab.label }}</span>
          <small v-if="tab.count !== undefined">{{ tab.count }}</small>
        </button>
      </nav>
      <div class="workbench-bottom-panel__actions">
        <span class="workbench-bottom-panel__caption">运行面板</span>
        <button
          class="workbench-bottom-panel__collapse"
          type="button"
          :title="collapsed ? '展开运行面板' : '收起运行面板'"
          :aria-label="collapsed ? '展开运行面板' : '收起运行面板'"
          :aria-expanded="!collapsed"
          @click="collapsed = !collapsed"
        >
          <el-icon aria-hidden="true"><ArrowUp v-if="collapsed" /><ArrowDown v-else /></el-icon>
        </button>
      </div>
    </header>

    <div v-if="!collapsed" class="workbench-bottom-panel__body" role="tabpanel">
      <slot :name="`tab-${activeTab}`" :active-tab="activeTab">
        <slot :active-tab="activeTab" />
      </slot>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowDown, ArrowUp } from '@element-plus/icons-vue'

export interface WorkbenchBottomTab {
  id: string
  label: string
  count?: number
}

const props = withDefaults(defineProps<{
  tabs: WorkbenchBottomTab[]
  modelValue?: boolean
  storageKey?: string
}>(), {
  modelValue: false,
  storageKey: ''
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const readActiveTab = () => {
  if (!props.storageKey || typeof window === 'undefined') return props.tabs[0]?.id || ''
  try {
    const value = window.localStorage.getItem(`${props.storageKey}.activeTab`)
    return value && props.tabs.some(tab => tab.id === value) ? value : props.tabs[0]?.id || ''
  } catch {
    return props.tabs[0]?.id || ''
  }
}

const activeTab = ref(readActiveTab())

const collapsed = computed({
  get: () => Boolean(props.modelValue),
  set: value => emit('update:modelValue', value)
})

watch(() => props.tabs, tabs => {
  if (!tabs.some(tab => tab.id === activeTab.value)) activeTab.value = tabs[0]?.id || ''
}, { deep: true })

watch(activeTab, value => {
  if (!props.storageKey || typeof window === 'undefined' || !value) return
  try { window.localStorage.setItem(`${props.storageKey}.activeTab`, value) } catch { /* storage is optional */ }
})
</script>

<style scoped>
.workbench-bottom-panel {
  position: relative;
  width: 100%;
  height: 100%;
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-sizing: border-box;
  border: 1px solid var(--wb-border-soft);
  border-radius: var(--wb-radius-section);
  background: var(--wb-surface-section);
  box-shadow: var(--wb-shadow-section);
}

.workbench-bottom-panel__header {
  flex: 0 0 var(--wb-panel-tab-height);
  min-width: 0;
  display: flex;
  align-items: stretch;
  justify-content: space-between;
  border-bottom: 1px solid var(--wb-border-soft);
  background: var(--wb-surface-section);
}

.workbench-bottom-panel__tabs {
  min-width: 0;
  display: flex;
  align-items: stretch;
  overflow-x: auto;
  scrollbar-width: none;
}

.workbench-bottom-panel__tabs::-webkit-scrollbar { display: none; }

.workbench-bottom-panel__tab {
  min-width: 74px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  margin: 0 2px;
  padding: 0 11px;
  border: 0;
  border-bottom: 2px solid transparent;
  border-radius: 6px 6px 0 0;
  background: transparent;
  color: var(--wb-text-muted);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.workbench-bottom-panel__tab:hover { color: var(--wb-text); background: color-mix(in srgb, var(--wb-hover) 58%, transparent); }
.workbench-bottom-panel__tab.active { border-bottom-color: var(--wb-accent); background: color-mix(in srgb, var(--wb-accent) 8%, transparent); color: var(--wb-accent); font-weight: 700; }
.workbench-bottom-panel__tab small { color: inherit; font: 10px var(--font-mono, monospace); opacity: .64; }

.workbench-bottom-panel__actions { flex: 0 0 auto; display: inline-flex; align-items: center; gap: 8px; padding: 0 8px 0 12px; }
.workbench-bottom-panel__caption { color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); letter-spacing: .06em; text-transform: uppercase; }
.workbench-bottom-panel__collapse { width: 28px; height: 28px; display: inline-grid; place-items: center; padding: 0; border: 1px solid transparent; border-radius: 8px; background: transparent; color: var(--wb-text-muted); font-size: 16px; line-height: 1; cursor: pointer; transition: background-color 140ms var(--ease-out), color 140ms var(--ease-out); }
.workbench-bottom-panel__collapse:hover, .workbench-bottom-panel__collapse:focus-visible { background: var(--wb-hover); color: var(--wb-accent); outline: none; }
.workbench-bottom-panel__body { flex: 1 1 auto; min-width: 0; min-height: 0; overflow: auto; overscroll-behavior: contain; scrollbar-gutter: stable; background: var(--wb-surface-section); }

.workbench-bottom-panel.is-collapsed .workbench-bottom-panel__header { border-bottom: 0; }
</style>
