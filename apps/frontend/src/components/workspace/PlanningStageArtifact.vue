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
      <div class="planning-stage-artifact__section-label" id="planning-stage-objective-title">{{ contentLabel }}</div>
      <p v-if="viewKey === 'task-plan'">{{ missionGoal }}</p>
      <div v-else-if="viewKey === 'detail'" class="planning-stage-artifact__task-list">
        <article v-for="task in tasks" :key="task.key" class="planning-stage-artifact__task">
          <div><strong>{{ task.title }}</strong><code>{{ task.key }}</code></div>
          <p>{{ task.objective || '暂无任务目标' }}</p>
          <small v-if="task.capabilityRequirements.length">能力：{{ task.capabilityRequirements.join('、') }}</small>
          <small v-if="task.acceptanceCriteria.length">验收：{{ task.acceptanceCriteria.join('；') }}</small>
        </article>
        <p v-if="!tasks.length" class="planning-stage-artifact__empty">当前 Run 未返回任务细化数据。</p>
      </div>
      <div v-else class="planning-stage-artifact__relation-list">
        <div v-for="(relation, index) in relations" :key="`${relation.sourceKey}:${relation.targetKey}:${index}`" class="planning-stage-artifact__relation">
          <span>{{ taskTitle(relation.sourceKey) }}</span><b>→</b><span>{{ taskTitle(relation.targetKey) }}</span><small>{{ relation.relationType }}</small>
        </div>
        <p v-if="!relations.length" class="planning-stage-artifact__empty">当前 Run 未返回依赖关系数据。</p>
      </div>
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
  plan?: Record<string, any> | null
}>()

type PlanTask = { key: string; title: string; objective: string; capabilityRequirements: string[]; acceptanceCriteria: string[] }
type PlanRelation = { sourceKey: string; targetKey: string; relationType: string }
const tasks = computed<PlanTask[]>(() => (Array.isArray(props.plan?.nodes) ? props.plan.nodes : []).map((item: any) => ({
  key: String(item?.key || ''), title: String(item?.title || item?.key || ''), objective: String(item?.objective || ''),
  capabilityRequirements: Array.isArray(item?.capabilityRequirements) ? item.capabilityRequirements.map(String) : [],
  acceptanceCriteria: Array.isArray(item?.acceptanceCriteria) ? item.acceptanceCriteria.map(String) : []
})).filter((item: PlanTask) => item.key))
const relations = computed<PlanRelation[]>(() => (Array.isArray(props.plan?.relations) ? props.plan.relations : []).map((item: any) => ({
  sourceKey: String(item?.sourceKey || ''), targetKey: String(item?.targetKey || ''), relationType: String(item?.relationType || 'depends_on')
})).filter((item: PlanRelation) => item.sourceKey && item.targetKey))
const taskTitle = (key: string) => tasks.value.find(item => item.key === key)?.title || key
const contentLabel = computed(() => props.viewKey === 'task-plan' ? 'MISSION OBJECTIVE' : props.viewKey === 'detail' ? 'TASK DETAILS' : 'DEPENDENCY GRAPH')

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
.planning-stage-artifact__task-list, .planning-stage-artifact__relation-list { display: grid; gap: 8px; margin-top: 10px; }
.planning-stage-artifact__task { padding: 11px 12px; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-sm); background: var(--wb-surface-2); }
.planning-stage-artifact__task > div { display: flex; justify-content: space-between; gap: 12px; }
.planning-stage-artifact__task strong { font-size: 13px; }
.planning-stage-artifact__task code, .planning-stage-artifact__task small { color: var(--wb-text-muted); font: 10px/1.5 var(--font-mono, monospace); }
.planning-stage-artifact__task small { display: block; margin-top: 5px; }
.planning-stage-artifact__relation { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr) auto; align-items: center; gap: 9px; padding: 9px 11px; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-sm); background: var(--wb-surface-2); font-size: 12px; }
.planning-stage-artifact__relation b { color: var(--wb-accent); }
.planning-stage-artifact__relation small { color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); }
.planning-stage-artifact__empty { color: var(--wb-text-muted) !important; }
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
