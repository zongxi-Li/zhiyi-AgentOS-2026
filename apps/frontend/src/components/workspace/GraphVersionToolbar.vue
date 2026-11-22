<script setup lang="ts">
import { computed, inject } from 'vue'
import { RefreshRight } from '@element-plus/icons-vue'
import { graphVersionKey, graphVersionTime, graphVersionsKey } from './graphVersions'

const versions = inject(graphVersionsKey, null)
const emit = defineEmits<{ locateNode: [id: string] }>()
const changes = computed(() => {
  const diff = versions?.difference.value
  if (!diff) return []
  return [
    ...diff.addedNodeIds.map(id => ({ id, kind: 'added', label: '新增' })),
    ...diff.updatedNodeIds.map(id => ({ id, kind: 'updated', label: '调整' })),
    ...diff.removedNodeIds.map(id => ({ id, kind: 'removed', label: '移除' }))
  ].map(item => ({ ...item, name: versions?.displayGraph.value?.nodes.find(node => node.nodeId === item.id)?.name
    || versions?.previousGraph.value?.nodes.find(node => node.nodeId === item.id)?.name || item.id }))
})
</script>

<template>
  <div class="version-toolbar">
    <div class="version-toolbar__controls">
      <slot name="heading" />
      <template v-if="versions">
      <label class="version-select"><span>图版本</span><select aria-label="选择图版本" :value="versions.selectedKey.value || ''"
        :disabled="!versions.entries.value.length" @change="versions.select(($event.target as HTMLSelectElement).value)">
        <option v-if="!versions.entries.value.length" value="">当前版本</option>
        <option v-for="entry in [...versions.entries.value].reverse()" :key="graphVersionKey(entry)" :value="graphVersionKey(entry)">v{{ entry.graphVersion }}{{ entry.current ? ' · 当前' : ' · 历史' }}</option>
      </select></label>
      <button class="version-toolbar__follow" :class="{ 'is-active': versions.following.value }" type="button" :aria-pressed="versions.following.value" @click="versions.follow()"><span aria-hidden="true" class="follow-dot" />{{ versions.following.value ? '跟随当前' : '返回当前' }}</button>
      <span class="version-toolbar__spacer" />
      <button type="button" class="version-toolbar__compare" :disabled="!versions.previous.value" :aria-pressed="versions.comparing.value"
        @click="versions.comparing.value = !versions.comparing.value">{{ versions.comparing.value ? '退出对比' : '对比上一版' }}</button>
      <button type="button" class="version-toolbar__refresh" :disabled="versions.loading.value" aria-label="刷新图版本" title="刷新图版本" @click="versions.refresh()"><el-icon aria-hidden="true"><RefreshRight /></el-icon></button>
      </template>
    </div>
    <div class="version-toolbar__meta">
    <template v-if="versions">
    <div v-if="!versions.following.value && versions.selected.value" class="version-history-notice" role="status">
      <span>正在查看 v{{ versions.selected.value.graphVersion }}<template v-if="versions.current.value"> · 当前版本 v{{ versions.current.value.graphVersion }}</template></span>
    </div>
    <div v-if="versions.selected.value" class="version-summary">
      <p :title="versions.selected.value.reason || undefined">{{ versions.selected.value.reason || (versions.previous.value ? '执行图修订' : '初始执行图') }}</p>
      <div class="version-summary__facts"><time>{{ graphVersionTime(versions.selected.value) }}</time>
        <span v-if="versions.selected.value.inherited.completedStepIds.length">复用 {{ versions.selected.value.inherited.completedStepIds.length }} 节点</span>
        <span v-if="versions.selected.value.patch">新增 {{ versions.selected.value.patch.addedNodeIds.length }} 节点</span>
      </div>
    </div>
    </template>
    <slot name="status" />
    </div>
    <template v-if="versions">
    <p v-if="versions.error.value" class="version-toolbar__error" role="status">{{ versions.error.value }}<button type="button" @click="versions.refresh()">重试</button></p>
    <p v-if="versions.snapshotError.value" class="version-toolbar__error" role="alert">{{ versions.snapshotError.value }}<button type="button" @click="versions.retrySnapshot()">重试</button></p>
    <section v-if="versions.comparing.value && versions.previous.value" class="graph-difference" aria-label="相邻图版本对比">
      <div class="graph-difference__header"><strong>v{{ versions.previous.value.graphVersion }} → v{{ versions.selected.value?.graphVersion }}</strong>
        <template v-if="versions.difference.value"><span class="is-added">+{{ versions.difference.value.addedNodeIds.length }} 新增</span><span class="is-updated">{{ versions.difference.value.updatedNodeIds.length }} 调整</span><span class="is-removed">−{{ versions.difference.value.removedNodeIds.length }} 移除</span>
          <span>依赖 +{{ versions.difference.value.addedEdgeIds.length }} / ~{{ versions.difference.value.updatedEdgeIds.length }} / −{{ versions.difference.value.removedEdgeIds.length }}</span></template>
        <span v-else role="status">正在加载对比…</span>
      </div>
      <div v-if="changes.length" class="graph-difference__nodes"><button v-for="change in changes" :key="change.id" type="button" :class="`is-${change.kind}`" :title="change.name" @click="emit('locateNode', change.id)"><span>{{ change.label }}</span>{{ change.name }}</button></div>
      <p v-else-if="versions.difference.value">{{ versions.difference.value.addedEdgeIds.length || versions.difference.value.updatedEdgeIds.length || versions.difference.value.removedEdgeIds.length ? '节点内容沿用，依赖关系已调整' : '本次修订没有节点或依赖结构变化' }}</p>
    </section>
    </template>
  </div>
</template>

<style scoped>
.version-toolbar { min-width: 0; background: var(--wb-surface-section); color: var(--wb-text-secondary); font-size: 11px; }
.version-toolbar__controls { display: flex; flex-wrap: wrap; align-items: center; gap: 5px 8px; min-height: 28px; padding: 5px 12px 4px; }
.version-toolbar__meta { display: flex; flex-wrap: wrap; align-items: center; gap: 2px 14px; padding: 3px 12px 4px; min-width: 0; border-top: 1px solid color-mix(in srgb, var(--wb-border-soft) 55%, transparent); background: color-mix(in srgb, var(--wb-surface-inset) 45%, var(--wb-surface-section)); }
.version-toolbar__meta:empty { display: none; }
.version-toolbar button, .version-toolbar select { box-sizing: border-box; color: var(--wb-text-secondary); border: 1px solid var(--wb-border-soft); border-radius: 6px; background: var(--wb-surface-section); font: inherit; cursor: pointer; transition: color 120ms ease, background-color 120ms ease, border-color 120ms ease; }
.version-toolbar button { display: inline-flex; align-items: center; justify-content: center; gap: 5px; min-height: 24px; padding: 2px 7px; }
.version-toolbar button:hover:not(:disabled) { border-color: color-mix(in srgb, var(--wb-accent) 40%, var(--wb-border-soft)); color: var(--wb-accent); background: color-mix(in srgb, var(--wb-accent) 6%, var(--wb-surface-section)); }
.version-toolbar button:disabled, .version-toolbar select:disabled { opacity: .45; cursor: default; }
.version-toolbar button:focus-visible, .version-toolbar select:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: 2px; }
.version-select { display: inline-flex; align-items: center; gap: 7px; }
.version-select > span { color: var(--wb-text-muted); font-size: 10px; }
.version-select select { min-height: 24px; max-width: 150px; padding: 2px 23px 2px 8px; color: var(--wb-text); background: var(--wb-surface-inset); font-weight: 500; }
.version-toolbar__spacer { flex: 1; }
.version-toolbar .version-toolbar__follow { background: transparent; border-color: transparent; }
.version-toolbar .version-toolbar__follow.is-active { color: var(--wb-accent); background: color-mix(in srgb, var(--wb-accent) 7%, transparent); }
.follow-dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
.version-toolbar .version-toolbar__compare[aria-pressed="true"] { color: var(--wb-accent); border-color: color-mix(in srgb, var(--wb-accent) 40%, var(--wb-border-soft)); background: color-mix(in srgb, var(--wb-accent) 8%, var(--wb-surface-section)); }
.version-toolbar .version-toolbar__refresh { width: 27px; padding: 0; background: transparent; border-color: transparent; }
.version-history-notice { display: flex; min-width: 0; color: var(--wb-accent); font-size: 10px; line-height: 22px; }
.version-summary { display: flex; flex: 0 1 auto; min-width: 0; align-items: center; flex-wrap: wrap; gap: 2px 10px; }
.version-summary p { max-width: 220px; min-width: 0; margin: 0; line-height: 22px; color: var(--wb-text-secondary); font-size: 10px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.version-summary__facts { display: flex; flex-wrap: wrap; gap: 8px; color: var(--wb-text-muted); font-size: 10px; }
.version-summary__facts span { padding-left: 8px; border-left: 1px solid var(--wb-border-soft); }
.version-summary__facts time { font-variant-numeric: tabular-nums; }
.graph-difference { padding: 9px 14px 11px; border-top: 1px solid var(--wb-border-soft); background: var(--wb-surface-inset); }
.graph-difference__header { display: flex; flex-wrap: wrap; gap: 7px 14px; align-items: center; }
.graph-difference__header strong { color: var(--wb-text); font-family: var(--font-mono, monospace); }
.is-added { --change-color: var(--sem-success, #8bcb78); } .is-updated { --change-color: var(--sem-waiting, #d9b86c); } .is-removed { --change-color: var(--sem-failed, #e06c75); }
.graph-difference__header > [class] { color: var(--change-color); }
.graph-difference__nodes { display: flex; flex-wrap: wrap; gap: 6px; max-height: 100px; overflow-y: auto; margin-top: 9px; }
.graph-difference__nodes button { min-height: 25px; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; border-color: color-mix(in srgb, var(--change-color) 32%, var(--wb-border-soft)); }
.graph-difference__nodes button span { flex-shrink: 0; font-size: 10px; color: var(--change-color); }
.graph-difference p { margin: 8px 0 0; color: var(--wb-text-muted); }
.version-toolbar__error { display: flex; align-items: center; gap: 8px; margin: 0; padding: 5px 14px 8px; color: var(--sem-waiting, var(--wb-text-secondary)); }
.version-toolbar__error button { min-height: 22px; border: 0; color: var(--wb-accent); background: transparent; }
</style>
