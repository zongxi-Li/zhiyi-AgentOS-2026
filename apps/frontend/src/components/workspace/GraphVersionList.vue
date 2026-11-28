<script setup lang="ts">
import { computed, inject } from 'vue'
import { RefreshRight, Share } from '@element-plus/icons-vue'
import { graphVersionKey, graphVersionTime, graphVersionPair, graphVersionsKey } from './graphVersions'

const versions = inject(graphVersionsKey, null)
const emit = defineEmits<{ openGraph: [] }>()
const entries = computed(() => [...(versions?.entries.value || [])].reverse())
const select = (key: string) => { versions?.select(key); emit('openGraph') }
const follow = () => { versions?.follow(); emit('openGraph') }
</script>

<template>
  <div v-if="versions" class="graph-version-list">
    <button v-if="entries.length" class="version-follow" :class="{ 'is-following': versions.following.value }"
      type="button" :aria-pressed="versions.following.value" @click="follow">
      <span class="version-follow__dot" aria-hidden="true" />
      <span>{{ versions.following.value ? '正在跟随当前版本' : '返回当前版本' }}</span>
      <el-icon aria-hidden="true"><RefreshRight /></el-icon>
    </button>
    <div v-if="versions.error.value" class="version-list-state" role="status">
      <span>{{ versions.error.value }}</span><button type="button" @click="versions.refresh()">重试</button>
    </div>
    <p v-else-if="!entries.length" class="version-list-state" role="status">{{ versions.loading.value ? '正在加载图版本…' : '尚无规划与执行版本' }}</p>
    <ol v-if="entries.length" aria-label="规划与执行版本">
      <li v-for="entry in entries" :key="graphVersionKey(entry)">
        <button class="version-row" :class="{ 'is-selected': versions.selectedKey.value === graphVersionKey(entry) }"
          type="button" :aria-pressed="versions.selectedKey.value === graphVersionKey(entry)"
          :title="graphVersionPair(entry)" @click="select(graphVersionKey(entry))">
          <span class="version-row__rail" aria-hidden="true"><el-icon><Share /></el-icon></span>
          <span class="version-row__body">
            <span class="version-row__heading"><strong>ACG {{ entry.taskPlanVersion == null ? '—' : `v${entry.taskPlanVersion}` }}</strong><span class="version-row__badge" :class="{ 'is-current': entry.current }">{{ entry.current ? '当前' : '历史' }}</span><time>{{ graphVersionTime(entry) }}</time></span>
            <span class="version-row__details">
              <span>RGraph v{{ entry.graphVersion }}</span>
              <span class="version-row__separator" aria-hidden="true">·</span>
              <span class="version-row__reason">{{ entry.reason || (entry.predecessorBlueprintId ? '执行图修订' : '初始执行图') }}</span>
            </span>
            <span v-if="entry.patch || entry.inherited.completedStepIds.length" class="version-row__summary">
              <span v-if="entry.patch" class="version-row__changes">
                <span v-if="entry.patch.addedNodeIds.length">+{{ entry.patch.addedNodeIds.length }} 新增</span>
                <span v-if="entry.patch.updatedNodeIds.length">{{ entry.patch.updatedNodeIds.length }} 调整</span>
                <span v-if="entry.patch.removedNodeIds.length">−{{ entry.patch.removedNodeIds.length }} 移除</span>
              </span>
              <span v-if="entry.inherited.completedStepIds.length" class="version-row__inherited">复用 {{ entry.inherited.completedStepIds.length }} 个已完成节点</span>
            </span>
          </span>
        </button>
      </li>
    </ol>
    <div v-if="versions.history.value?.proposals?.length" class="version-proposals" aria-label="未生效修订">
      <span>未生效修订</span>
      <article v-for="proposal in versions.history.value.proposals" :key="proposal.proposalId"><strong>{{ proposal.status === 'rejected' ? '已拒绝' : '待处理' }}</strong><p>{{ proposal.reason || '尚未形成执行图版本' }}</p></article>
    </div>
    <p v-if="entries.length" class="version-list-note">切换版本仅用于查看结构快照</p>
  </div>
</template>

<style scoped>
.graph-version-list { padding: 3px 0 5px; font-size: 11px; }
.graph-version-list button { font: inherit; cursor: pointer; }
.version-follow { display: flex; align-items: center; gap: 7px; width: calc(100% - 16px); margin: 2px 8px 7px; padding: 7px 8px; border: 1px solid var(--wb-border-soft); border-radius: 5px; background: var(--wb-surface-inset); color: var(--wb-text-secondary); text-align: left; }
.version-follow > span:nth-child(2) { flex: 1; }
.version-follow.is-following { color: var(--wb-accent); background: color-mix(in srgb, var(--wb-accent) 7%, var(--wb-surface-inset)); }
.version-follow__dot { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
ol { margin: 0; padding: 0; list-style: none; }
.version-row { display: flex; gap: 6px; width: 100%; padding: 6px 10px 7px; border: 0; border-left: 2px solid transparent; color: var(--wb-text-secondary); background: transparent; text-align: left; }
.version-row:hover { background: var(--wb-surface-hover, var(--wb-surface-2)); }
.version-row.is-selected { border-left-color: var(--wb-accent); background: color-mix(in srgb, var(--wb-accent) 10%, transparent); }
.version-row__rail { flex: 0 0 15px; padding-top: 2px; color: var(--wb-text-muted); }
.is-selected .version-row__rail { color: var(--wb-accent); }
.version-row__body { display: grid; flex: 1; gap: 3px; min-width: 0; }
.version-row__heading { display: flex; align-items: center; gap: 6px; }
.version-row__heading strong { color: var(--wb-text); font: 600 12px var(--font-mono, monospace); }
.version-row__heading time { margin-left: auto; color: var(--wb-text-muted); font-size: 10px; white-space: nowrap; }
.version-row__badge { padding: 1px 5px; border: 1px solid var(--wb-border-soft); border-radius: 3px; font-size: 9px; color: var(--wb-text-muted); }
.version-row__badge.is-current { color: var(--wb-accent); border-color: color-mix(in srgb, var(--wb-accent) 30%, transparent); }
.version-row__details, .version-row__summary, .version-row__changes { display: flex; flex-wrap: wrap; align-items: baseline; gap: 3px 7px; min-width: 0; color: var(--wb-text-muted); font-size: 10px; line-height: 1.4; }
.version-row__reason { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.version-row__separator { color: var(--wb-border-strong, var(--wb-text-muted)); }
.version-row__changes > span:first-child { color: var(--sem-success, var(--wb-accent)); }
.version-row__inherited { color: var(--wb-text-muted); }
.version-list-note { margin: 6px 14px 0; color: var(--wb-text-muted); line-height: 1.6; font-size: 10px; }
.version-list-state { display: flex; gap: 8px; align-items: center; margin: 8px 14px; color: var(--wb-text-muted); line-height: 1.7; }
.version-list-state button { border: 0; padding: 2px 4px; background: transparent; color: var(--wb-accent); white-space: nowrap; }
.version-proposals { margin: 9px 12px 0; padding-top: 9px; border-top: 1px solid var(--wb-border-soft); color: var(--wb-text-muted); }
.version-proposals article { margin-top: 8px; } .version-proposals strong { font-size: 10px; color: var(--sem-waiting, var(--wb-text-secondary)); } .version-proposals p { margin: 4px 0; line-height: 1.6; }
button:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: -2px; }
</style>
