<script setup lang="ts">
import { computed } from 'vue'
import type { WorkspaceReviewProjection, WorkspaceReviewRound } from '@/services/api/agentos/types/graph'

const props = defineProps<{ review?: WorkspaceReviewProjection | null; nodes?: { nodeId: string; name?: string }[]; graphVersion?: number; navigable?: boolean }>()
const emit = defineEmits<{ selectNode: [nodeId: string] }>()
const review = computed(() => props.review?.schemaVersion === 1
  && (props.graphVersion == null || props.review.graphVersion === props.graphVersion) ? props.review : null)
const statusLabel = computed(() => ({ reading: '正在补读', reviewing: '正在复核', completed: '已完成', blocked: '等待处理' })[review.value?.status || 'reading'])
const roundLabel = (round: number) => round ? `第 ${round} 轮` : '初始读取'
const actionLabel = (action: string) => ({ continue: '继续执行', revise: '补读与复核', recover: '恢复执行', complete: '完成审查', wait: '等待处理', ask: '等待补充', read: '读取证据', review: '复核结果' } as Record<string, string>)[action] || action
const node = (id: string) => props.nodes?.find(item => item.nodeId === id)
const references = (round: WorkspaceReviewRound) => [round.observationRef, round.decisionRef, round.patchRef, ...round.traceRefs].filter((value): value is string => Boolean(value))
</script>

<template>
  <section v-if="review" class="workspace-review" aria-label="仓库审查进展">
    <div class="workspace-review__summary" role="status">
      <strong>仓库审查 · {{ roundLabel(review.round) }}</strong>
      <span>图 v{{ review.graphVersion }} · {{ statusLabel }}</span>
      <span>剩余目录 {{ review.gaps.missingListingCount }} · 文件 {{ review.gaps.missingReadCount }}<template v-if="review.gaps.unsupportedEntryCount"> · 待处理条目 {{ review.gaps.unsupportedEntryCount }}</template></span>
    </div>
    <details class="workspace-review__details">
      <summary>审查轮次与证据 · {{ review.rounds.length }} 轮记录</summary>
      <div v-if="review.gaps.missingListings.length || review.gaps.missingReads.length || review.gaps.unsupportedEntries.length" class="workspace-review__gaps">
        <p v-if="review.gaps.missingListings.length">待查看目录：<code v-for="path in review.gaps.missingListings" :key="path">{{ path }}</code></p>
        <p v-if="review.gaps.missingReads.length">待读文件：<code v-for="path in review.gaps.missingReads" :key="path">{{ path }}</code></p>
        <p v-if="review.gaps.unsupportedEntries.length">待处理条目：<code v-for="path in review.gaps.unsupportedEntries" :key="path">{{ path }}</code></p>
        <small>上方数量为全部缺口；此处列出已记录的路径样本。</small>
      </div>
      <ol v-if="review.rounds.length" class="workspace-review__rounds">
        <li v-for="round in review.rounds" :key="`${round.graphVersion}:${round.round}`">
          <div><strong>{{ roundLabel(round.round) }}</strong> · 图 v{{ round.graphVersion }} · {{ actionLabel(round.action) }}</div>
          <p v-if="round.reason">{{ round.reason }}</p>
          <div v-if="round.addedStepIds.length" class="workspace-review__nodes">
            <span>新增步骤：</span>
            <template v-for="id in round.addedStepIds" :key="id">
              <button v-if="navigable && node(id)" type="button" @click="emit('selectNode', id)">{{ node(id)?.name || id }}</button>
              <code v-else>{{ node(id)?.name || id }}</code>
            </template>
          </div>
          <p v-if="round.stepIds.length">关联步骤：<code v-for="id in round.stepIds" :key="id">{{ node(id)?.name || id }}</code></p>
          <details v-if="references(round).length" class="workspace-review__references">
            <summary>证据与轨迹引用 · {{ references(round).length }}</summary>
            <code v-for="reference in references(round)" :key="reference">{{ reference }}</code>
          </details>
        </li>
      </ol>
      <p v-else>尚无已记录的图修订轮次。</p>
    </details>
  </section>
</template>

<style scoped>
.workspace-review { flex: 0 0 auto; padding: 9px 14px; border-bottom: 1px solid var(--wb-border-soft); color: var(--wb-text-secondary); font-size: 11px; line-height: 1.7; }
.workspace-review__summary { display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 12px; }
.workspace-review__summary strong, .workspace-review__rounds strong { color: var(--wb-text); font-weight: 550; }
.workspace-review__details > summary, .workspace-review__references > summary { cursor: pointer; color: var(--wb-text-muted); }
.workspace-review__details { margin-top: 4px; }
.workspace-review__details[open] { max-height: 240px; overflow: auto; }
.workspace-review__rounds { margin: 8px 0 0; padding-left: 20px; }
.workspace-review__rounds li + li { margin-top: 10px; }
.workspace-review p { margin: 4px 0; overflow-wrap: anywhere; }
.workspace-review code { display: inline-block; max-width: 100%; margin-right: 7px; color: var(--wb-text-secondary); font: 10px/1.7 var(--font-mono, monospace); overflow-wrap: anywhere; }
.workspace-review__references code { display: block; }
.workspace-review__nodes { display: flex; flex-wrap: wrap; gap: 4px 6px; align-items: baseline; }
.workspace-review__nodes button { padding: 1px 5px; border: 1px solid var(--wb-border-soft); border-radius: 4px; background: transparent; color: var(--wb-accent); font: inherit; cursor: pointer; }
.workspace-review__nodes button:focus-visible { outline: 1px solid var(--wb-accent); outline-offset: 2px; }
.workspace-review__gaps small { color: var(--wb-text-muted); }
</style>
