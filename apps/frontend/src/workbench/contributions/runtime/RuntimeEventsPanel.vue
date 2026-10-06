<template>
  <section class="runtime-activity" aria-label="Runtime Activity Feed">
    <header class="runtime-activity__intro">
      <div class="runtime-activity__heading">
        <strong>Activity</strong>
        <span>{{ filteredItems.length }} semantic events</span>
      </div>
      <span class="runtime-activity__side">
        <label class="runtime-activity__filter">
          <span class="sr-only">筛选活动类型</span>
          <select v-model="kindFilter" aria-label="筛选活动类型">
            <option value="all">全部</option>
            <option v-for="option in kindOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
          </select>
        </label>
        <button class="runtime-activity__close" type="button" title="关闭运行面板" aria-label="关闭运行面板" @click="emit('close')">
          <el-icon aria-hidden="true"><Close /></el-icon>
        </button>
      </span>
    </header>

    <BrandEmpty v-if="!filteredItems.length" class="runtime-activity__empty">
      {{ presentations.length ? '没有符合条件的活动' : '尚未观测到 Runtime Activity' }}
    </BrandEmpty>
    <div v-else class="runtime-activity__feed">
      <RuntimeEventRow
        v-for="item in filteredItems"
        :key="item.id"
        :item="item"
        @select="selectItem(item)"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Close } from '@element-plus/icons-vue'
import BrandEmpty from '@/components/common/BrandEmpty.vue'
import RuntimeEventRow from '@/components/workbench/runtime/RuntimeEventRow.vue'
import type { RuntimeObservation, RuntimeSelection } from '@/workbench/runtime/observation'
import {
  projectRuntimeObservation,
  type RuntimePresentationKind,
  type RuntimeSemanticPresentation
} from '@/workbench/runtime/runtimePresentation'

const props = defineProps<{ runtimeObservation: RuntimeObservation | null }>()
const emit = defineEmits<{ select: [selection: RuntimeSelection]; close: [] }>()

const kindFilter = ref<'all' | RuntimePresentationKind>('all')
const kindOptions: Array<{ value: RuntimePresentationKind; label: string }> = [
  { value: 'model', label: '模型' },
  { value: 'tool', label: '工具' },
  { value: 'command', label: '命令' },
  { value: 'artifact', label: '产物' },
  { value: 'error', label: '错误' },
  { value: 'completion', label: '完成' },
  { value: 'generic', label: '其他' }
]

const presentations = computed(() => projectRuntimeObservation(props.runtimeObservation))
const filteredItems = computed<RuntimeSemanticPresentation[]>(() => (
  kindFilter.value === 'all'
    ? presentations.value
    : presentations.value.filter(item => item.kind === kindFilter.value)
))

const selectItem = (item: RuntimeSemanticPresentation) => emit('select', {
  stepId: item.stepId,
  semanticTaskKey: item.semanticTaskKey
})
</script>

<style scoped>
.runtime-activity { display: flex; flex-direction: column; min-height: 100%; color: var(--wb-text-secondary); background: var(--wb-surface-1); }
.runtime-activity__intro { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 30px; box-sizing: border-box; padding: 4px 12px; }
.runtime-activity__heading { display: inline-flex; align-items: baseline; gap: 8px; min-width: 0; }
.runtime-activity__heading strong { color: var(--wb-text); font: 10px var(--font-mono, monospace); letter-spacing: .08em; text-transform: uppercase; }
.runtime-activity__heading span { overflow: hidden; color: var(--wb-text-muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.runtime-activity__filter select { min-height: 24px; padding: 0 6px; border: 1px solid color-mix(in srgb, var(--wb-border) 76%, transparent); border-radius: var(--wb-radius-sm); color: var(--wb-text-secondary); background: var(--wb-surface-inset); font: inherit; font-size: 10px; }
.runtime-activity__filter select:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: 1px; }
.runtime-activity__side { display: inline-flex; align-items: center; gap: 8px; }
.runtime-activity__close { display: inline-grid; place-items: center; width: 22px; height: 22px; padding: 0; border: 1px solid transparent; border-radius: 6px; background: transparent; color: var(--wb-text-muted); font-size: 13px; line-height: 1; cursor: pointer; transition: background-color 140ms var(--ease-out, ease), color 140ms var(--ease-out, ease); }
.runtime-activity__close:hover, .runtime-activity__close:focus-visible { background: var(--wb-hover); color: var(--wb-accent); outline: none; }
.runtime-activity__feed { display: grid; align-content: start; }
.runtime-activity__empty { flex: 1; margin: 0; }
.sr-only { position: absolute; width: 1px; height: 1px; padding: 0; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
</style>
