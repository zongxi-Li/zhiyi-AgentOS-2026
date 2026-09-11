<template>
  <article class="planning-stage-artifact" :aria-label="stageInfo.title" :data-testid="`planning-${viewKey}-artifact`">
    <header class="planning-stage-artifact__header">
      <div>
        <div class="planning-stage-artifact__eyebrow">PLANNING STAGE</div>
        <h2>{{ stageInfo.title }}</h2>
        <p>{{ stageInfo.summary }}</p>
      </div>
      <span class="planning-stage-artifact__status">
        <span class="planning-stage-artifact__status-dot" aria-hidden="true"></span>
        {{ statusLabel }}
      </span>
    </header>

    <section class="planning-stage-artifact__objective" aria-labelledby="planning-stage-objective-title">
      <div class="planning-stage-artifact__section-label" id="planning-stage-objective-title">OBJECTIVE</div>
      <p>{{ missionGoal }}</p>
    </section>

    <section class="planning-stage-artifact__facts" aria-labelledby="planning-stage-facts-title">
      <div class="planning-stage-artifact__section-heading">
        <div class="planning-stage-artifact__section-label" id="planning-stage-facts-title">STAGE FACTS</div>
        <span>{{ stageInfo.factCaption }}</span>
      </div>
      <div class="planning-stage-artifact__metrics">
        <div v-for="metric in metrics" :key="metric.key" class="planning-stage-artifact__metric">
          <span>{{ metric.label }}</span>
          <strong>{{ metric.value }}</strong>
          <small>{{ metric.description }}</small>
        </div>
      </div>
    </section>

    <section class="planning-stage-artifact__downstream" aria-labelledby="planning-stage-downstream-title">
      <div class="planning-stage-artifact__section-label" id="planning-stage-downstream-title">PIPELINE POSITION</div>
      <div class="planning-stage-artifact__pipeline">
        <span v-for="(item, index) in stageInfo.pipeline" :key="item">
          {{ item }}<template v-if="index < stageInfo.pipeline.length - 1"><b aria-hidden="true">→</b></template>
        </span>
      </div>
      <p>{{ stageInfo.downstream }}</p>
    </section>

    <footer class="planning-stage-artifact__footer">
      <span>RUN {{ runId || '—' }}</span>
      <span>·</span>
      <span>{{ viewKey }}</span>
    </footer>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { RunDocumentSymbol, RunDocumentViewKey } from '@/workbench/runtime/runDocument'

type PlanningStageKey = Exclude<RunDocumentViewKey, 'intent-profile'>

const props = defineProps<{
  symbol: RunDocumentSymbol
  missionGoal: string
  runId: string | null
  viewKey: PlanningStageKey
}>()

const stageInfo = computed(() => ({
  'task-plan': {
    title: '任务规划',
    summary: '将意图画像拆分为可执行的任务骨架与依赖关系。',
    factCaption: '已从规划事件确认',
    pipeline: ['Intent Profile', 'Task Plan', 'Detail'],
    downstream: '规划结果会作为任务细化与后续执行编排的输入。'
  },
  detail: {
    title: '任务细化',
    summary: '为任务骨架补充执行所需的范围、能力与交付细节。',
    factCaption: '当前阶段范围',
    pipeline: ['Task Plan', 'Detail', 'Relations'],
    downstream: '细化结果会进入依赖构建，并为执行阶段提供更明确的任务边界。'
  },
  relations: {
    title: '依赖关系',
    summary: '整理任务之间的先后关系，为图谱编译和执行调度提供依据。',
    factCaption: '当前阶段范围',
    pipeline: ['Detail', 'Relations', 'ACG'],
    downstream: '依赖结果会进入 ACG 编译，并影响后续执行顺序。'
  }
}[props.viewKey]))

const statusLabel = computed(() => ({
  completed: '已完成',
  running: '进行中',
  failed: '失败',
  warning: '需关注',
  pending: '待开始'
}[props.symbol.status]))

const valueFor = (key: string) => {
  const value = props.symbol.metrics?.[key]
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

const metrics = computed(() => props.viewKey === 'task-plan'
  ? [
      { key: 'taskCount', label: '任务', value: valueFor('taskCount'), description: '已解析的任务数量' },
      { key: 'dependencyCount', label: '依赖', value: valueFor('dependencyCount'), description: '已建立的依赖关系' },
      { key: 'status', label: '阶段状态', value: statusLabel.value, description: '规划事件当前状态' }
    ]
  : [
      { key: 'status', label: '阶段状态', value: statusLabel.value, description: '规划事件当前状态' },
      { key: 'input', label: '上游输入', value: props.viewKey === 'detail' ? 'Task Plan' : 'Detail', description: '本阶段依赖的结果' },
      { key: 'output', label: '下游输出', value: props.viewKey === 'detail' ? 'Relations' : 'ACG', description: '本阶段继续提供给' }
    ])
</script>

<style scoped>
.planning-stage-artifact { min-height: 100%; padding: 24px 20px 28px; color: var(--wb-text); }
.planning-stage-artifact__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; padding-bottom: 22px; border-bottom: 1px solid var(--wb-border-soft); }
.planning-stage-artifact__eyebrow, .planning-stage-artifact__section-label { color: var(--wb-accent); font: 11px var(--font-mono, monospace); letter-spacing: .1em; }
.planning-stage-artifact h2 { margin: 7px 0 5px; font-size: 20px; line-height: 1.3; }
.planning-stage-artifact p { margin: 0; color: var(--wb-text-secondary); font-size: 13px; line-height: 1.6; }
.planning-stage-artifact__status { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 7px; padding: 5px 9px; border: 1px solid color-mix(in srgb, var(--wb-success) 35%, var(--wb-border)); border-radius: var(--wb-radius-sm); color: var(--wb-success); font: 11px var(--font-mono, monospace); }
.planning-stage-artifact__status-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.planning-stage-artifact__objective { margin-top: 22px; padding: 15px 16px; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-sm); background: var(--wb-surface-inset); }
.planning-stage-artifact__objective p { margin-top: 9px; color: var(--wb-text); font-size: 14px; line-height: 1.65; }
.planning-stage-artifact__facts { margin-top: 24px; }
.planning-stage-artifact__section-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.planning-stage-artifact__section-heading > span { color: var(--wb-text-muted); font: 11px var(--font-mono, monospace); }
.planning-stage-artifact__metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); margin-top: 10px; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-sm); overflow: hidden; }
.planning-stage-artifact__metric { min-width: 0; padding: 14px 12px; background: var(--wb-surface-2); }
.planning-stage-artifact__metric + .planning-stage-artifact__metric { border-left: 1px solid var(--wb-border-soft); }
.planning-stage-artifact__metric span, .planning-stage-artifact__metric small { display: block; color: var(--wb-text-muted); font-size: 12px; }
.planning-stage-artifact__metric strong { display: block; margin: 7px 0 4px; color: var(--wb-text); font-size: 20px; line-height: 1.1; }
.planning-stage-artifact__metric small { overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.planning-stage-artifact__downstream { margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--wb-border-soft); }
.planning-stage-artifact__pipeline { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; margin: 12px 0 8px; }
.planning-stage-artifact__pipeline span { display: inline-flex; align-items: center; gap: 7px; padding: 5px 8px; border: 1px solid color-mix(in srgb, var(--wb-accent) 28%, var(--wb-border)); border-radius: var(--wb-radius-sm); color: var(--wb-text-secondary); background: var(--wb-accent-soft); font-size: 12px; }
.planning-stage-artifact__pipeline b { color: var(--wb-text-muted); font: 13px var(--font-mono, monospace); font-weight: 400; }
.planning-stage-artifact__footer { display: flex; gap: 7px; margin-top: 26px; color: var(--wb-text-muted); font: 11px var(--font-mono, monospace); }
@media (max-width: 760px) {
  .planning-stage-artifact__metrics { grid-template-columns: 1fr; }
  .planning-stage-artifact__metric + .planning-stage-artifact__metric { border-top: 1px solid var(--wb-border-soft); border-left: 0; }
}
</style>
