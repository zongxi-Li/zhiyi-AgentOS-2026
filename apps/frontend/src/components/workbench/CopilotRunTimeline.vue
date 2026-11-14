<template>
  <div class="run-timeline" aria-label="任务执行时间线">
    <div v-if="active || hasWorkContent" class="run-timeline__status" role="status">
      <button type="button" class="run-timeline__history-toggle" :aria-expanded="historyExpanded" aria-label="展开或收起工作记录" @click="historyExpanded = !historyExpanded">
        <ArrowRight class="run-timeline__chevron" :class="{ 'is-expanded': historyExpanded }" aria-hidden="true" />
        <span>{{ elapsed ? `${active ? '已运行' : '用时'} ${elapsed}` : '工作记录' }}</span>
      </button>
      <span class="run-timeline__state"><span v-if="active && !waitingForApproval" class="run-timeline__dot is-active" />{{ statusText }}</span>
    </div>
    <template v-for="entry in entries" :key="entry.id">
    <slot v-if="entry.kind === 'message'" name="message" :message="entry.message" />
    <article v-else-if="entry.kind === 'progress'" v-show="historyExpanded" class="run-timeline__planning run-timeline__progress">
      <p>{{ entry.text }}</p>
      <details v-if="entry.detail" class="run-timeline__failure"><summary>失败信息</summary><p>{{ entry.detail }}</p></details>
    </article>
    <article v-else-if="entry.kind === 'plan' && plan" class="run-timeline__plan">
      <h3>初步规划 <small>版本 {{ plan.planVersion }}</small></h3>
      <p v-if="plan.objective" class="run-timeline__objective">{{ plan.objective }}</p>
      <template v-if="plan.tasks[0]?.rationale"><p class="run-timeline__context">规划思路摘要</p><p>{{ plan.tasks[0].rationale }}</p></template>
      <details v-if="plan.constraints.length">
        <summary>任务边界与约束 · {{ plan.constraints.length }}</summary>
        <ul><li v-for="constraint in plan.constraints" :key="constraint">{{ constraint }}</li></ul>
      </details>
      <details class="run-timeline__steps">
        <summary>查看 {{ plan.tasks.length }} 个步骤与规划依据</summary>
        <ol><li v-for="task in plan.tasks" :key="task.key"><details>
          <summary>{{ task.title }}</summary><p>{{ task.objective }}</p>
          <p v-if="task.rationale"><strong>规划依据：</strong>{{ task.rationale }}</p>
          <ul v-if="task.acceptanceCriteria.length"><li v-for="criterion in task.acceptanceCriteria" :key="criterion">{{ criterion }}</li></ul>
        </details></li></ol>
      </details>
      <details v-if="plan.expectedArtifacts.length"><summary>预期交付物</summary><ul><li v-for="artifact in plan.expectedArtifacts" :key="artifact">{{ artifact }}</li></ul></details>
      <p v-if="['pending', 'planning'].includes(status)" class="run-timeline__confirm">请检查以上规划，确认后继续。</p>
    </article>
    <article v-else-if="entry.kind === 'planning'" v-show="historyExpanded" class="run-timeline__planning">
      <p :class="{ 'run-timeline__context': planningText }"><span v-if="planningText">规划思路摘要 · </span>{{ planningMessage }}</p>
      <div v-if="planningText" class="run-timeline__planning-text run-timeline__text markdown-body" v-html="planningMarkup"></div>
      <details v-else-if="runtime?.planning.draft.nodes.length" class="run-timeline__draft" open><summary>正在形成的计划 · {{ runtime.planning.draft.nodes.length }} 个步骤</summary>
        <ul><li v-for="node in runtime.planning.draft.nodes" :key="node.key">{{ node.title }}<p v-if="node.rationale">{{ node.rationale }}</p></li></ul>
      </details>
      <small v-if="planningText || runtime?.planning.draft.nodes.length" class="run-timeline__draft-note">当前为规划草稿，以待确认的初步规划为准。</small>
    </article>
    <details v-else-if="entry.kind === 'tools'" v-show="historyExpanded" class="run-timeline__tools">
      <summary class="run-timeline__operation-summary">
        <ArrowRight class="run-timeline__chevron" aria-hidden="true" />
        <span class="run-timeline__tool-name">{{ [...new Set(entry.items.map(item => toolLabel(item.tool)))].join('、') }}</span>
        <small v-if="entry.items.length > 1">{{ entry.items.length }} 项</small>
        <span class="run-timeline__flag" :class="`is-${toolGroupStatus(entry.items)}`">{{ toolStatusLabel(toolGroupStatus(entry.items)) }}</span>
      </summary>
      <details v-for="item in entry.items" :key="item.id" class="run-timeline__tool">
        <summary>
          <ArrowRight class="run-timeline__chevron" aria-hidden="true" />
          <span class="run-timeline__tool-name">{{ toolLabel(item.tool) }}</span>
          <small class="run-timeline__flag" :class="`is-${item.status}`">{{ toolStatusLabel(item.status) }}</small>
        </summary>
        <dl><div v-if="item.stepId"><dt>步骤</dt><dd>{{ item.stepId }}</dd></div><div v-if="item.executionId"><dt>执行记录</dt><dd>{{ item.executionId }}</dd></div><div v-if="item.receiptRef"><dt>结果凭据</dt><dd>{{ item.receiptRef }}</dd></div></dl>
      </details>
    </details>
    <article v-else-if="entry.kind === 'output'" v-show="historyExpanded" class="run-timeline__output">
        <p class="run-timeline__context">{{ entry.output.planning ? '规划思路摘要' : entry.output.title }} <small>{{ outputStatus(entry.output) }}</small></p>
        <TaskWorkSummary v-if="entry.output.node && active && !['COMPLETED', 'FAILED', 'CANCELLED'].includes(entry.output.node.status)" :node="entry.output.node" :objective="entry.output.approach?.objective" :rationale="entry.output.approach?.rationale" />
        <div v-if="entry.output.text" class="run-timeline__text markdown-body" v-html="outputMarkup.get(entry.output.id)"></div>
        <p v-else-if="!entry.output.node">正在等待模型正文…</p>
        <small v-if="entry.output.planning" class="run-timeline__draft-note">规划草稿，以待确认的初步规划为准。</small>
        <small v-else-if="!entry.output.running" class="run-timeline__draft-note">这是本次接收的生成片段，完整结果以步骤交付为准。</small>
    </article>
    <slot v-else-if="entry.kind === 'controls'" name="controls" />
    </template>
    <slot name="approvals" />
  </div>
</template>
<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, shallowRef, watch, ref } from 'vue'
import { ArrowRight } from '@element-plus/icons-vue'
import type { CopilotInitialPlan, CopilotToolActivity } from '@/services/api/agentos/api/copilot'
import { acquireRunRuntimeStore, releaseRunRuntimeStore, type RunRuntimeStore, type NodeRuntimeState } from '@/workbench/runtime/runtimeEvents'
import type { WorkspaceGraphNode } from '@/services/api/agentos'
import TaskWorkSummary from '../workspace/TaskWorkSummary.vue'
import { planningContent, streamingContent } from '@/workbench/runtime/streamingContent'
import { projectModelOutput, type RuntimeTraceObservation } from '@/workbench/runtime/observation'
import { renderMarkdown } from '@/utils/markdown'
import { planningProfileText, planningProgressText, type CopilotConversationMessage } from './copilotConversation'

const props = withDefaults(defineProps<{ runId: string | null; status: string; plan?: CopilotInitialPlan | null; graphNodes?: WorkspaceGraphNode[]; tools?: CopilotToolActivity[]; traces?: RuntimeTraceObservation[]; messages?: CopilotConversationMessage[]; startedAt?: string | null; updatedAt?: string | null; waitingForApproval?: boolean }>(), { plan: null, graphNodes: () => [], tools: () => [], traces: () => [], messages: () => [], waitingForApproval: false })
const active = computed(() => ['pending', 'planning', 'running', 'retrying', 'waiting_review'].includes(props.status))
const emit = defineEmits<{ content: [hasContent: boolean] }>()
const runtime = shallowRef<RunRuntimeStore | null>(null)
const now = ref(Date.now())
const historyExpanded = ref(true)
watch(() => props.runId, () => { historyExpanded.value = true })
let attachedRunId: string | null = null
let suspended = false
let clock: ReturnType<typeof setInterval> | undefined
function disconnect(clear = true) {
  if (runtime.value && attachedRunId) releaseRunRuntimeStore(attachedRunId, runtime.value)
  if (clear) runtime.value = null
  attachedRunId = null
  if (clock) clearInterval(clock)
  clock = undefined
}
function connect() {
  if (!active.value && attachedRunId === props.runId) { disconnect(false); return }
  disconnect()
  if (suspended || !props.runId || !active.value) return
  attachedRunId = props.runId
  runtime.value = acquireRunRuntimeStore(props.runId)
  clock = setInterval(() => { now.value = Date.now() }, 1000)
}
watch(() => [props.runId, active.value], connect, { immediate: true })
onDeactivated(() => { suspended = true; disconnect() })
onActivated(() => { if (suspended) { suspended = false; connect() } })
onBeforeUnmount(disconnect)
interface WorkOutput { id: string; title: string; timestamp: string | null; text: string; running: boolean; failed: boolean; planning: boolean; node?: NodeRuntimeState; approach?: CopilotInitialPlan['tasks'][number] }
const outputStatus = (output: WorkOutput) => output.running
  ? output.node && !output.node.firstTokenAt && !output.node.chunkCount ? '等待正文' : '正在生成'
  : output.failed ? '生成已中断' : '工作说明'
const outputs = computed<WorkOutput[]>(() => Object.entries(runtime.value?.nodes || {}).filter(([, node]) => node.modelStartedAt || node.outputBuffer || node.lastActivityAt)
  .slice(-8).map(([id, node]) => ({ id: node.outputId || id, title: node.title || props.graphNodes.find(graphNode => graphNode.acgNodeId === id)?.name || '当前步骤', timestamp: node.modelStartedAt, text: streamingContent(node.outputBuffer), planning: false, node,
    approach: props.plan?.tasks.find(task => task.key === props.graphNodes.find(graphNode => graphNode.acgNodeId === id)?.semanticTaskKey),
    running: active.value && ['MODEL_STARTING', 'STREAMING'].includes(node.phase) && !['COMPLETED', 'FAILED', 'CANCELLED'].includes(node.status), failed: node.status === 'FAILED' })))
const pastOutputs = computed<WorkOutput[]>(() => (runtime.value?.outputHistory || []).map(item => ({ ...item, planning: item.kind === 'planning', running: false })))
const planningText = computed(() => planningContent(runtime.value?.planning.outputBuffer || ''))
const planningMarkup = computed(() => renderMarkdown(planningText.value))
let outputCache = new Map<string, { text: string; html: string }>()
const outputMarkup = computed(() => {
  // Streaming a new paragraph should not reparse every earlier explanation.
  const next = new Map<string, { text: string; html: string }>()
  for (const output of [...pastOutputs.value, ...outputs.value]) {
    const previous = outputCache.get(output.id)
    next.set(output.id, previous?.text === output.text ? previous : { text: output.text, html: renderMarkdown(output.text) })
  }
  outputCache = next
  return new Map([...next].map(([id, rendered]) => [id, rendered.html]))
})
const planningHistory = computed(() => projectModelOutput(props.traces.filter(trace => trace.runId === props.runId))
  .filter(item => !['started', 'stage_started'].includes(item.kind)).slice(-10))
const planningProfile = computed(() => runtime.value?.planning.profile || planningHistory.value.find(item => item.kind === 'profile_resolved')?.metrics || null)
const elapsed = computed(() => {
  if (!props.startedAt) return ''
  const end = active.value ? now.value : Date.parse(props.updatedAt || '')
  const seconds = Math.floor((end - Date.parse(props.startedAt)) / 1000)
  if (!Number.isFinite(seconds) || seconds < 0) return ''
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
})
const statusText = computed(() => props.waitingForApproval ? '等待你确认' : ({ pending: '正在准备任务', planning: '正在规划', running: '正在执行', retrying: '正在恢复', waiting_review: '等待审核', failed: '本次运行未完成', completed: '本次运行已完成', cancelled: '本次运行已取消', superseded: '已由后续运行接替' } as Record<string, string>)[props.status] || '等待运行状态')
const planningMessage = computed(() => {
  const planning = runtime.value?.planning
  if (planning?.status === 'FAILED' || planningHistory.value.some(item => item.kind === 'failed')) return '本次规划未完成，下面保留已收到的规划内容与阶段记录。'
  if (planning?.status === 'COMPLETED') return '初步规划已生成，正在载入待确认版本。'
  const stage = (planning?.stage || planning?.draft.stage || '').split('.')[0]
  const labels: Record<string, string> = { intent_profile: '理解目标与约束', profile: '理解目标与约束', decompose: '拆分任务与规划依据', tasks: '拆分任务步骤', outline: '拟定任务步骤', detail: '补充步骤目标与验收标准', relations: '梳理步骤依赖', coverage: '检查交付覆盖', repair: '修正规划并重新校验', planning: '校验初步规划' }
  return stage ? `正在整理规划：${labels[stage] || '形成执行方案'}` : props.status === 'running' ? '正在处理当前步骤，执行进展将在这里显示。' : '正在理解任务并形成初步规划，完成后会在这里供你确认。'
})
const activity = computed(() => {
  const items = new Map(props.tools.map(tool => [tool.executionId, { ...tool, id: tool.executionId }]))
  const operationKey = (stepId: string, attemptId: string, tool: string) => JSON.stringify([stepId, attemptId, tool])
  const completedAt = new Map<string, number>()
  for (const tool of props.tools) {
    if (!tool.stepId || !tool.attemptId || tool.status === 'running') continue
    const time = Date.parse(tool.createdAt)
    if (!Number.isFinite(time)) continue
    const key = operationKey(tool.stepId, tool.attemptId, tool.tool)
    completedAt.set(key, Math.max(completedAt.get(key) ?? -Infinity, time))
  }
  for (const event of runtime.value?.activity.events || []) {
    if (!['tool.execution_started', 'tool.execution_completed'].includes(event.eventType)) continue
    const p = event.payload || {}
    const startId = `${event.nodeId}:${event.attemptId}:${p.tool}`
    const id = String(p.executionId || startId)
    if (event.eventType === 'tool.execution_started') {
      const completionTime = completedAt.get(operationKey(event.nodeId || '', event.attemptId || '', p.tool || ''))
      // A refreshed receipt can arrive before the matching completion event.
      // Keep later calls of the same tool visible within the same node attempt.
      if (items.has(id) || (completionTime !== undefined && Date.parse(event.timestamp || '') <= completionTime)) continue
    }
    if (event.eventType === 'tool.execution_completed') items.delete(startId)
    items.set(id, { id, executionId: p.executionId || '', tool: p.tool || '', status: event.eventType === 'tool.execution_completed' ? p.status || 'completed' : 'running', stepId: event.nodeId || '', attemptId: event.attemptId || undefined, createdAt: event.timestamp || '', receiptRef: p.receiptRef })
  }
  return [...items.values()].slice(-100)
})
type ToolItem = typeof activity.value[number]
type ConversationEntry = { id: string; time: number } & (
  | { kind: 'progress'; text: string; detail?: string | null }
  | { kind: 'message'; message: CopilotConversationMessage }
  | { kind: 'tools'; items: ToolItem[] }
  | { kind: 'output'; output: WorkOutput }
  | { kind: 'plan' | 'planning' | 'controls' }
)
const hasWorkContent = computed(() => Boolean(planningText.value || runtime.value?.planning.draft.nodes.length || planningProfile.value || planningHistory.value.length || outputs.value.length || pastOutputs.value.length || props.plan || activity.value.length))
const entries = computed(() => {
  const start = Date.parse(props.startedAt || '') || 0
  const time = (timestamp?: string | null) => {
    const parsed = Date.parse(timestamp || '')
    return Number.isFinite(parsed) ? parsed : start
  }
  const result: ConversationEntry[] = planningHistory.value
    .filter(item => !(props.plan && item.kind === 'completed') && !(planningProfile.value && item.kind === 'stage_completed' && item.stage === 'intent_profile'))
    .map(item => ({ id: `progress:${item.id}`, kind: 'progress', time: time(item.timestamp), text: planningProgressText(item), detail: item.detail }))
  if (planningProfile.value && !planningHistory.value.some(item => item.kind === 'profile_resolved')) {
    result.push({ id: 'planning-profile', kind: 'progress', time: start, text: planningProfileText(planningProfile.value) })
  }
  if (!props.plan && (planningText.value || runtime.value?.planning.draft.nodes.length || active.value && (!outputs.value.length && !activity.value.length))) {
    result.push({ id: 'planning-preview', kind: 'planning', time: time(runtime.value?.planning.modelStartedAt || runtime.value?.planning.startedAt) })
  }
  if (props.plan) {
    const planRecord = planningHistory.value.filter(item => ['completed', 'graph_compiled', 'plan_parsed'].includes(item.kind)).pop()
    const planTime = time(runtime.value?.planning.completedAt || planRecord?.timestamp)
    result.push({ id: 'accepted-plan', kind: 'plan', time: planTime }, { id: 'controls', kind: 'controls', time: planTime })
  } else result.push({ id: 'controls', kind: 'controls', time: Infinity })
  result.push(...activity.value.map(item => ({ id: `tool:${item.id}`, kind: 'tools' as const, time: time(item.createdAt), items: [item] })))
  result.push(...[...pastOutputs.value, ...outputs.value].map(output => ({ id: `output:${output.id}`, kind: 'output' as const, time: time(output.timestamp), output })))
  result.push(...props.messages.map(message => ({ id: `message:${message.id}`, kind: 'message' as const, time: time(message.time), message })))
  result.sort((a, b) => a.time - b.time)
  // Only combine adjacent operations. A chat message or progress paragraph keeps its place.
  return result.reduce<ConversationEntry[]>((grouped, entry) => {
    const previous = grouped[grouped.length - 1]
    if (entry.kind === 'tools' && previous?.kind === 'tools'
      && previous.items[0].stepId === entry.items[0].stepId && previous.items[0].attemptId === entry.items[0].attemptId) previous.items.push(...entry.items)
    else grouped.push(entry)
    return grouped
  }, [])
})
const toolStatusLabel = (status: string) => ({ completed: '已完成', failed: '失败', running: '执行中', cancelled: '已取消' } as Record<string, string>)[status] || status
const toolGroupStatus = (items: ToolItem[]) => items.some(item => item.status === 'running') ? 'running' : items.some(item => item.status === 'failed') ? 'failed' : items.every(item => item.status === 'completed') ? 'completed' : items[0].status
watch(() => [planningText.value, runtime.value?.planning.draft.nodes, planningProfile.value, planningHistory.value, outputs.value, pastOutputs.value, props.plan, activity.value], () => {
  emit('content', hasWorkContent.value)
}, { immediate: true })
const toolLabel = (tool: string) => ({ 'fs.read': '读取文件', read_file: '读取文件', 'fs.list': '查看目录', list_files: '查看目录', 'fs.write': '写入文件', write_file: '写入文件', 'fs.patch': '修改文件', patch_file: '修改文件', 'shell.exec': '运行命令', run_tests: '运行测试' } as Record<string, string>)[tool] || tool || '工具操作'
</script>
<style scoped>
.run-timeline { min-width: 0; color: var(--wb-text-secondary); font-size: 13px; line-height: 1.75; text-wrap: pretty; }
.run-timeline__status { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 14px; margin: 0 0 22px; color: var(--wb-text-muted); font-size: 11px; }
.run-timeline__history-toggle { display: inline-flex; align-items: center; gap: 7px; min-height: 28px; padding: 0; border: 0; border-radius: 4px; background: transparent; color: inherit; font: inherit; cursor: pointer; }
.run-timeline__history-toggle:hover { color: var(--wb-text); }
.run-timeline__history-toggle:focus-visible, summary:focus-visible { outline: 1px solid var(--wb-accent); outline-offset: 3px; }
.run-timeline__state { display: inline-flex; align-items: center; gap: 6px; }
.run-timeline__dot { width: 5px; height: 5px; flex: 0 0 5px; background: var(--wb-accent); border-radius: 50%; }
.run-timeline__dot.is-active { animation: activity-pulse 1.8s ease-in-out infinite; }
.run-timeline__planning, .run-timeline__plan, .run-timeline__output { margin: 0 0 22px; }
p { margin: 0 0 12px; overflow-wrap: anywhere; }
p:last-child { margin-bottom: 0; }
h3 { margin: 0 0 12px; color: var(--wb-text); font-size: 13px; font-weight: 600; }
h3 small { margin-left: 7px; font-size: 10px; font-weight: 400; color: var(--wb-text-muted); }
.run-timeline__objective { white-space: pre-wrap; }
details { margin: 10px 0; }
summary { cursor: pointer; color: var(--wb-text-muted); border-radius: 4px; font-size: 12px; transition: color 140ms var(--ease-out, ease); }
summary:hover { color: var(--wb-text); }
ol, ul { margin: 10px 0; padding-left: 20px; }
li { margin: 8px 0; overflow-wrap: anywhere; }
li p { margin: 6px 0; }
.run-timeline__confirm { color: var(--wb-text-muted); font-size: 12px; }
.run-timeline__context, .run-timeline__draft-note { color: var(--wb-text-muted); font-size: 11px; }
.run-timeline__context { margin-bottom: 8px; }
.run-timeline__context small { margin-left: 8px; font-size: inherit; }
.run-timeline__draft-note { display: block; margin-top: 8px; }
.run-timeline__failure summary { color: var(--wb-danger); }
.run-timeline__failure p { margin-top: 8px; font: 11px/1.7 var(--font-mono, monospace); }
.run-timeline__tools { margin: -6px 0 20px; }
.run-timeline__tool { margin: 6px 0 6px 18px; }
.run-timeline__tools summary { display: flex; align-items: center; gap: 7px; min-height: 28px; list-style: none; }
.run-timeline__tools summary::-webkit-details-marker { display: none; }
.run-timeline__tools summary small { flex-shrink: 0; font-size: 10px; }
.run-timeline__chevron { width: 11px; height: 11px; flex: 0 0 11px; color: var(--wb-text-muted); transition: transform 160ms var(--ease-out, ease); }
.run-timeline__chevron.is-expanded, details[open] > summary > .run-timeline__chevron { transform: rotate(90deg); }
.run-timeline__tool-name { min-width: 0; overflow-wrap: anywhere; }
.run-timeline__flag { flex-shrink: 0; margin-left: auto; color: var(--wb-text-muted); font-size: 10px; }
.run-timeline__flag.is-failed { color: var(--wb-danger); }
.run-timeline__flag.is-running { color: var(--wb-accent); }
dl { margin: 6px 0 12px 18px; font-size: 11px; }
dl > div { display: grid; grid-template-columns: 58px minmax(0, 1fr); gap: 8px; align-items: baseline; }
dl > div + div { margin-top: 5px; }
dt { color: var(--wb-text-muted); }
dd { margin: 0; overflow-wrap: anywhere; font: 11px/1.6 var(--font-mono, monospace); }
.run-timeline__text.markdown-body { color: inherit; font-size: inherit; line-height: inherit; }
.run-timeline__text { overflow-wrap: anywhere; }
.run-timeline__text :deep(p:first-child) { margin-top: 0; }
.run-timeline__text :deep(p:last-child) { margin-bottom: 0; }
.run-timeline__text :deep(pre) { max-width: 100%; overflow: auto; }
@keyframes activity-pulse { 50% { opacity: .35; } }
@media (prefers-reduced-motion: reduce) { .run-timeline__dot.is-active { animation: none; } .run-timeline__chevron { transition: none; } }
</style>
