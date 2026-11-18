<template>
  <div class="run-timeline" aria-label="任务执行时间线">
    <WorkspaceReviewProgress :review="workspaceReview" :nodes="reviewNodes" />
    <div v-if="active || hasWorkContent" class="run-timeline__status" role="status">
      <button type="button" class="run-timeline__history-toggle" :aria-expanded="historyExpanded" aria-label="展开或收起工作记录" @click="historyExpanded = !historyExpanded">
        <ArrowRight class="run-timeline__chevron" :class="{ 'is-expanded': historyExpanded }" aria-hidden="true" />
        <span>{{ elapsed ? `${active ? '已运行' : '用时'} ${elapsed}` : '工作记录' }}</span>
      </button>
      <span class="run-timeline__state"><span v-if="active && !waitingForApproval" class="run-timeline__dot is-active" />{{ statusText }}</span>
      <code v-if="reviewDiagnostic?.errorCode" class="run-timeline__review-error">{{ reviewDiagnostic.errorCode }}</code>
    </div>
    <section v-for="group in workGroups" :key="group.id" v-show="!group.agent || historyExpanded" :class="group.agent ? 'agent-work' : 'timeline-flow'" :data-agent-id="group.agent?.agentRegistration?.agentId || group.agent?.agentName">
      <header v-if="group.agent" class="agent-work__heading" :class="`is-${agentState(group.agent)}`">
        <component :is="agentState(group.agent) === 'completed' ? CircleCheck : agentState(group.agent) === 'failed' ? CircleClose : Connection" class="agent-work__icon" aria-hidden="true" />
        <strong>{{ group.agent.agentName || '执行 Agent 待确认' }}</strong>
        <span class="agent-work__state">{{ agentStateLabel(group.agent) }}</span>
        <button v-if="group.agent.agentRegistration" type="button" class="agent-work__pool-link" @click="emit('inspect-agent', group.agent.agentRegistration.instanceId)">查看执行池 <ArrowRight aria-hidden="true" /></button>
        <details class="agent-work__identity"><summary :aria-label="`${group.agent.agentName || 'Agent'} 的执行信息`"><MoreFilled aria-hidden="true" /></summary>
          <div><span>{{ group.agent.title }}</span><small v-if="group.agent.agentRegistration">{{ group.agent.agentRegistration.instanceId }} · 第 {{ group.agent.agentRegistration.generation }} 代</small></div>
        </details>
      </header>
      <div v-if="group.agent" class="agent-work__assignment">
        <span class="agent-work__task">{{ group.agent.title }}</span>
        <span v-if="group.agent.agentRegistration" class="agent-work__instance">{{ group.agent.agentRegistration.instanceId }} · 第 {{ group.agent.agentRegistration.generation }} 代</span>
        <span v-if="group.agent.modelName" class="agent-work__model">{{ group.agent.modelName }}</span>
      </div>
    <template v-for="entry in group.entries" :key="entry.id">
    <slot v-if="entry.kind === 'message'" name="message" :message="entry.message" />
    <details v-else-if="entry.kind === 'progress'" v-show="historyExpanded" class="run-timeline__progress" :open="entry.items.some(item => item.detail)">
      <summary class="run-timeline__operation-summary"><ArrowRight class="run-timeline__chevron" aria-hidden="true" /><span>规划记录</span><small>{{ entry.items.length }} 项</small></summary>
      <article v-for="item in entry.items" :key="item.id" class="run-timeline__progress-item">
        <ChatTranscriptBlock :block="{ id: item.id, kind: 'status', state: 'completed', text: item.text }" />
        <details v-if="item.detail" class="run-timeline__failure"><summary>失败信息</summary><p>{{ item.detail }}</p></details>
      </article>
    </details>
    <article v-else-if="entry.kind === 'plan' && plan" class="run-timeline__plan">
      <h3>初步规划 <small>版本 {{ plan.planVersion }}</small></h3>
      <div v-if="plan.objective" class="run-timeline__objective markdown-body" v-html="planObjectiveMarkup" />
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
      <ChatTranscriptBlock v-if="!plan" :block="{ id: 'planning-status', kind: 'status', state: 'completed', text: planningMessage }" />
      <CopilotPlannerStep v-if="planningText || planningReasoning || runtime?.planning.outputId" :key="runtime?.planning.outputId || 'planning-current'" class="run-timeline__planning-text" :id="runtime?.planning.outputId || 'planning-current'"
        :stage="runtime?.planning.stage" :text="planningText" :reasoning="planningReasoning" :reasoning-truncated="runtime?.planning.reasoningTruncated" :state="planningOutputState" :elapsed-ms="runtime?.planning.elapsedMs" />
      <details v-else-if="runtime?.planning.draft.nodes.length" class="run-timeline__draft"><summary>查看规划草稿 · {{ runtime.planning.draft.nodes.length }} 个步骤</summary>
        <ul><li v-for="node in runtime.planning.draft.nodes" :key="node.key">{{ node.title }}<p v-if="node.rationale">{{ node.rationale }}</p></li></ul>
      </details>
      <small v-if="!planningText && runtime?.planning.draft.nodes.length" class="run-timeline__draft-note">当前为规划草稿，以待确认的初步规划为准。</small>
    </article>
    <details v-else-if="entry.kind === 'tools'" v-show="historyExpanded" class="run-timeline__tools">
      <summary class="run-timeline__operation-summary">
        <component :is="toolGroupIcon(entry.items)" class="run-timeline__operation-icon" aria-hidden="true" />
        <span class="run-timeline__tool-name">{{ [...new Set(entry.items.map(item => toolLabel(item.tool)))].join('、') }}</span>
        <small v-if="entry.items.length > 1">{{ entry.items.length }} 项</small>
        <small v-if="entry.items.some(item => item.approvalDecision?.source === 'policy')" class="run-timeline__approval-summary">已自动批准</small>
        <span class="run-timeline__flag" :class="`is-${toolGroupStatus(entry.items)}`">{{ toolStatusLabel(toolGroupStatus(entry.items)) }}</span>
        <ArrowRight class="run-timeline__chevron" aria-hidden="true" />
      </summary>
      <details v-for="item in entry.items" :key="item.id" class="run-timeline__tool">
        <summary>
          <ArrowRight class="run-timeline__chevron" aria-hidden="true" />
          <span class="run-timeline__tool-name">{{ toolLabel(item.tool) }}</span>
          <small class="run-timeline__flag" :class="`is-${item.status}`">{{ toolStatusLabel(item.status) }}</small>
          <small v-if="item.approvalDecision?.source === 'policy'" class="run-timeline__auto-approved">已自动批准</small>
        </summary>
        <p v-if="item.target" class="run-timeline__tool-target">{{ item.target }}</p>
        <pre v-if="item.resultPreview" class="run-timeline__tool-result">{{ item.resultPreview }}</pre>
        <dl><div v-if="item.stepId"><dt>步骤</dt><dd>{{ item.stepId }}</dd></div><div v-if="item.executionId"><dt>执行记录</dt><dd>{{ item.executionId }}</dd></div><div v-if="item.receiptRef"><dt>结果凭据</dt><dd>{{ item.receiptRef }}</dd></div></dl>
        <dl v-if="item.approvalDecision" class="run-timeline__approval-decision" aria-label="工具审批记录">
          <div><dt>批准来源</dt><dd>{{ item.approvalDecision.source === 'policy' ? '任务自动审批策略' : '人工批准' }}</dd></div>
          <div v-if="item.approvalDecision.actor"><dt>操作者</dt><dd>{{ item.approvalDecision.actor.userId }}<span v-if="item.approvalDecision.actor.tenantId"> · {{ item.approvalDecision.actor.tenantId }}</span></dd></div>
          <div v-if="item.approvalDecision.decidedAt"><dt>批准时间</dt><dd>{{ item.approvalTime }}</dd></div>
          <div v-if="item.approvalDecision.policyRevision != null"><dt>策略版本</dt><dd>{{ item.approvalDecision.policyRevision }}</dd></div>
        </dl>
      </details>
    </details>
    <CopilotPlannerStep v-else-if="entry.kind === 'output' && entry.output.planning" v-show="historyExpanded" :id="entry.output.id"
      :stage="entry.output.stage" :text="entry.output.text" :reasoning="entry.output.reasoning" :reasoning-truncated="entry.output.reasoningTruncated" :state="entry.output.state || (entry.output.failed ? 'interrupted' : 'completed')" :elapsed-ms="entry.output.elapsedMs" />
    <article v-else-if="entry.kind === 'output'" v-show="historyExpanded" class="run-timeline__output">
        <header v-if="entry.output.running || entry.output.failed || !group.agent" class="run-timeline__output-heading"><h3 v-if="!group.agent">{{ entry.output.title }}</h3><small>{{ outputStatus(entry.output) }}</small></header>
        <details v-if="entry.output.modelName || entry.output.approach?.objective || entry.output.approach?.rationale" class="run-timeline__approach">
          <summary>执行详情</summary>
          <p v-if="entry.output.modelName" class="run-timeline__model">模型 · {{ entry.output.modelName }}</p>
          <p v-if="entry.output.approach?.objective">{{ entry.output.approach.objective }}</p>
          <p v-if="entry.output.approach?.rationale && entry.output.approach.rationale !== entry.output.approach.objective">{{ entry.output.approach.rationale }}</p>
        </details>
        <CopilotPlannerStep v-if="entry.output.reasoning" :key="`${entry.output.id}:reasoning`" class="run-timeline__reasoning" execution
          :id="`${entry.output.id}:reasoning`" text="" :reasoning="entry.output.reasoning" :state="entry.output.running ? 'streaming' : entry.output.failed ? 'interrupted' : 'completed'" />
        <TaskWorkSummary v-if="!entry.output.text && !entry.output.reasoning && entry.output.node && active && !['COMPLETED', 'FAILED', 'CANCELLED'].includes(entry.output.node.status)" :node="entry.output.node" />
        <div v-if="entry.output.text" class="run-timeline__text markdown-body" v-html="outputMarkup.get(entry.output.id)"></div>
        <p v-else-if="!entry.output.node && !entry.output.reasoning">正在等待模型正文…</p>
        <small v-if="entry.output.planning" class="run-timeline__draft-note">规划草稿，以待确认的初步规划为准。</small>
        <details v-else-if="!entry.output.running && entry.output.text" class="run-timeline__source-note"><summary>关于此记录</summary><small>这是本次接收的生成片段，完整结果以步骤交付为准。</small></details>
    </article>
    <slot v-else-if="entry.kind === 'controls'" name="controls" />
    </template>
    </section>
    <slot name="approvals" />
  </div>
</template>
<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, shallowRef, watch, ref } from 'vue'
import { ArrowRight, CircleCheck, CircleClose, Connection, Document, FolderOpened, EditPen, Monitor, MoreFilled, Tools } from '@element-plus/icons-vue'
import type { CopilotInitialPlan, CopilotToolActivity } from '@/services/api/agentos/api/copilot'
import { acquireRunRuntimeStore, releaseRunRuntimeStore, type RunRuntimeStore, type NodeRuntimeState } from '@/workbench/runtime/runtimeEvents'
import type { WorkspaceGraphNode } from '@/services/api/agentos'
import TaskWorkSummary from '../workspace/TaskWorkSummary.vue'
import ChatTranscriptBlock from '@/components/ChatTranscriptBlock.vue'
import CopilotPlannerStep from './CopilotPlannerStep.vue'
import WorkspaceReviewProgress from '@/components/agentos/WorkspaceReviewProgress.vue'
import type { WorkspaceReviewProjection } from '@/services/api/agentos/types/graph'
import { planningContent, streamingContent } from '@/workbench/runtime/streamingContent'
import { projectModelOutput, type RuntimeTraceObservation } from '@/workbench/runtime/observation'
import { renderCopilotMarkdown } from './copilotMarkdown'
import { planningProfileText, planningProgressText, planningStageLabel, type CopilotConversationMessage } from './copilotConversation'

const props = withDefaults(defineProps<{ runId: string | null; status: string; plan?: CopilotInitialPlan | null; graphNodes?: WorkspaceGraphNode[]; tools?: CopilotToolActivity[]; traces?: RuntimeTraceObservation[]; messages?: CopilotConversationMessage[]; startedAt?: string | null; updatedAt?: string | null; waitingForApproval?: boolean; workspaceReview?: WorkspaceReviewProjection | null }>(), { plan: null, graphNodes: () => [], tools: () => [], traces: () => [], messages: () => [], waitingForApproval: false, workspaceReview: null })
const reviewNodes = computed(() => props.graphNodes.map(node => ({ nodeId: node.acgNodeId, name: node.name })))
const planObjectiveMarkup = computed(() => {
  // Pasted task headings can contain separated markers such as "# # 任务".
  const objective = (props.plan?.objective || '').replace(/^((?:#[ \t]*){1,6})(?=\S)/,
    marks => `${'#'.repeat((marks.match(/#/g) || []).length)} `)
  return renderCopilotMarkdown(objective)
})
const active = computed(() => ['pending', 'planning', 'running', 'retrying', 'waiting_review'].includes(props.status))
const emit = defineEmits<{ content: [hasContent: boolean]; 'inspect-agent': [instanceId: string] }>()
const runtime = shallowRef<RunRuntimeStore | null>(null)
const now = ref(Date.now())
const historyExpanded = ref(true)
watch(() => props.runId, () => { historyExpanded.value = true })
let attachedRunId: string | null = null
let suspended = false
let clock: ReturnType<typeof setInterval> | undefined
function disconnect() {
  if (runtime.value && attachedRunId) releaseRunRuntimeStore(attachedRunId, runtime.value)
  runtime.value = null
  attachedRunId = null
  if (clock) clearInterval(clock)
  clock = undefined
}
function connect() {
  if (suspended || !props.runId) { disconnect(); return }
  if (attachedRunId !== props.runId || !runtime.value) {
    disconnect()
    attachedRunId = props.runId
    // Terminal Runs fetch their durable display baseline once; their SSE
    // endpoint then closes. They need no ticking clock or polling loop.
    runtime.value = acquireRunRuntimeStore(props.runId)
  }
  if (clock) clearInterval(clock)
  clock = active.value ? setInterval(() => { now.value = Date.now() }, 1000) : undefined
}
watch(() => [props.runId, active.value], connect, { immediate: true })
onDeactivated(() => { suspended = true; disconnect() })
onActivated(() => { if (suspended) { suspended = false; connect() } })
onBeforeUnmount(disconnect)
interface WorkOutput { nodeId?: string; attemptId?: string | null; agentName?: string; agentRegistration?: NodeRuntimeState['agentRegistration']; modelName?: string | null; callId?: string; id: string; title: string; timestamp: string | null; text: string; running: boolean; failed: boolean; planning: boolean; stage?: string | null; state?: string; elapsedMs?: number | null; reasoning?: string; reasoningTruncated?: boolean; node?: NodeRuntimeState; approach?: CopilotInitialPlan['tasks'][number] }
const agentState = (agent: WorkOutput) => agent.node?.status?.toLowerCase() || 'unknown'
const agentStateLabel = (agent: WorkOutput) => ({ completed: '已完成', failed: '执行失败', cancelled: '已取消', running: '正在工作', queued: '等待执行资源', pending: '等待执行' } as Record<string, string>)[agentState(agent)] || '执行记录'
const outputStatus = (output: WorkOutput) => output.running
  ? output.reasoning && !output.text ? '正在思考' : output.node && !output.node.firstTokenAt && !output.node.chunkCount ? '等待正文' : '正在生成'
  : output.failed ? '生成已中断' : '生成记录'
const outputs = computed<WorkOutput[]>(() => Object.entries(runtime.value?.nodes || {}).filter(([, node]) => node.modelStartedAt || node.outputBuffer || node.lastActivityAt)
  .slice(-8).map(([id, node]) => ({ id: node.outputId || id, nodeId: id, attemptId: node.currentAttemptId, agentName: node.agentName, agentRegistration: node.agentRegistration, modelName: node.modelName, callId: node.callId, title: node.title || props.graphNodes.find(graphNode => graphNode.acgNodeId === id)?.name || '当前步骤', timestamp: node.modelStartedAt || node.queuedAt || node.lastActivityAt, text: streamingContent(node.outputBuffer, true), reasoning: node.reasoningBuffer, planning: false, node,
    approach: props.plan?.tasks.find(task => task.key === props.graphNodes.find(graphNode => graphNode.acgNodeId === id)?.semanticTaskKey),
    running: active.value && ['MODEL_STARTING', 'STREAMING'].includes(node.phase) && !['COMPLETED', 'FAILED', 'CANCELLED'].includes(node.status), failed: node.status === 'FAILED' })))
const pastOutputs = computed<WorkOutput[]>(() => (runtime.value?.outputHistory || []).map(item => ({ ...item, planning: item.kind === 'planning', running: false })))
const planningText = computed(() => planningContent(runtime.value?.planning.outputBuffer || ''))
const planningReasoning = computed(() => runtime.value?.planning.reasoningBuffer || '')
const planningOutputState = computed(() => {
  const planning = runtime.value?.planning
  if (planning?.status === 'FAILED') return 'interrupted'
  if (planning?.modelPhase === 'COMPLETED' || planning?.status === 'COMPLETED') return 'completed'
  return active.value && !props.plan ? 'streaming' : 'interrupted'
})
let outputCache = new Map<string, { text: string; html: string }>()
const outputMarkup = computed(() => {
  // Streaming a new paragraph should not reparse every earlier explanation.
  const next = new Map<string, { text: string; html: string }>()
  for (const output of [...pastOutputs.value, ...outputs.value]) {
    const previous = outputCache.get(output.id)
    if (previous?.text === output.text) { next.set(output.id, previous); continue }
    // Plain-text task reports also use Chinese section labels without Markdown
    // hashes. Keep these boundaries while allowing prose lines to flow naturally.
    const prose = output.text.replace(/^([一二三四五六七八九十百]+、[^\r\n。！？；]{1,32})$/gm, '\n\n$1\n\n')
    next.set(output.id, { text: output.text, html: renderCopilotMarkdown(prose) })
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
const reviewDiagnostic = computed(() => active.value && !props.waitingForApproval && props.workspaceReview?.status !== 'completed'
  && runtime.value?.workspaceReview?.status !== 'IDLE' ? runtime.value?.workspaceReview : null)
const statusText = computed(() => {
  if (props.waitingForApproval) return '等待你确认'
  if (reviewDiagnostic.value?.status === 'BLOCKED') return '仓库审查暂时受阻'
  if (reviewDiagnostic.value?.status === 'RETRYING') return '仓库审查正在重试'
  return ({ pending: '正在准备任务', planning: '正在规划', running: '正在执行', retrying: '正在恢复', waiting_review: '等待审核', failed: '本次运行未完成', completed: '本次运行已完成', cancelled: '本次运行已取消', superseded: '已由后续运行接替' } as Record<string, string>)[props.status] || '等待运行状态'
})
const planningMessage = computed(() => {
  const planning = runtime.value?.planning
  if (planning?.status === 'FAILED' || planningHistory.value.some(item => item.kind === 'failed')) return '本次规划未完成，下面保留已收到的规划内容与阶段记录。'
  if (planning?.status === 'COMPLETED') return '初步规划已生成，正在载入待确认版本。'
  const stage = planning?.stage || planning?.draft.stage
  return stage ? `正在整理规划：${planningStageLabel(stage)}` : props.status === 'running' ? '正在处理当前步骤，执行进展将在这里显示。' : '正在理解任务并形成初步规划，完成后会在这里供你确认。'
})
const approvalTimeFormatter = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric', hour12: false,
})
const approvalTime = (value: string) => {
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) ? approvalTimeFormatter.format(timestamp) : value
}
const activity = computed(() => {
  const items = new Map(props.tools.map(tool => [tool.executionId, { ...tool, id: tool.executionId, target: tool.target, resultPreview: tool.resultPreview }]))
  const operationKey = (stepId: string, attemptId: string, tool: string) => JSON.stringify([stepId, attemptId, tool])
  const completedAt = new Map<string, number>()
  for (const tool of props.tools) {
    if (!tool.stepId || !tool.attemptId || ['running', 'capacity_waiting'].includes(tool.status)) continue
    const time = Date.parse(tool.createdAt)
    if (!Number.isFinite(time)) continue
    const key = operationKey(tool.stepId, tool.attemptId, tool.tool)
    completedAt.set(key, Math.max(completedAt.get(key) ?? -Infinity, time))
  }
  for (const event of runtime.value?.activity.events || []) {
    if (!['tool.capacity_waiting', 'tool.execution_started', 'tool.execution_completed'].includes(event.eventType)) continue
    const p = event.payload || {}
    const legacyStartId = `${event.nodeId}:${event.attemptId}:${p.tool}`
    const startId = p.operationKey ? `${legacyStartId}:${p.operationKey}` : legacyStartId
    const id = String(p.executionId || startId)
    if (event.eventType !== 'tool.execution_completed') {
      const completionTime = completedAt.get(operationKey(event.nodeId || '', event.attemptId || '', p.tool || ''))
      // Legacy events have no operation identity; use receipt times only for them.
      // Parallel operations can share a tool and start before another one completes.
      if (items.has(id) && items.get(id)?.status !== 'capacity_waiting'
        || (!p.operationKey && completionTime !== undefined && Date.parse(event.timestamp || '') <= completionTime)) continue
    }
    if (event.eventType !== 'tool.capacity_waiting' && id !== startId) items.delete(startId)
    items.set(id, { id, executionId: p.executionId || '', tool: p.tool || '', status: event.eventType === 'tool.execution_completed' ? p.status || 'completed' : event.eventType === 'tool.capacity_waiting' ? 'capacity_waiting' : 'running', stepId: event.nodeId || '', attemptId: event.attemptId || undefined, createdAt: event.timestamp || '', receiptRef: p.receiptRef, target: p.target, resultPreview: p.resultPreview,
      approvalDecision: p.approvalDecision ?? items.get(id)?.approvalDecision })
  }
  // Approval evidence changes with tool activity, not the one-second run clock.
  return [...items.values()].slice(-100).map(item => ({ ...item,
    approvalTime: item.approvalDecision?.decidedAt ? approvalTime(item.approvalDecision.decidedAt) : '',
  }))
})
type ToolItem = typeof activity.value[number]
function toolGroupIcon(items: ToolItem[]) {
  const icons = items.map(item => /^(?:fs\.read|read_file)$/.test(item.tool) ? Document
    : /^(?:fs\.list|list_files)$/.test(item.tool) ? FolderOpened
    : /^(?:fs\.(?:write|patch)|write_file|patch_file)$/.test(item.tool) ? EditPen
    : /^(?:shell\.exec|command\.run|run_tests)$/.test(item.tool) ? Monitor : Tools)
  return icons.every(icon => icon === icons[0]) ? icons[0] : Tools
}
type ConversationEntry = { id: string; time: number } & (
  | { kind: 'progress'; items: Array<{ id: string; text: string; detail?: string | null }> }
  | { kind: 'message'; message: CopilotConversationMessage }
  | { kind: 'tools'; items: ToolItem[] }
  | { kind: 'output'; output: WorkOutput }
  | { kind: 'plan' | 'planning' | 'controls' }
)
const hasWorkContent = computed(() => Boolean(props.workspaceReview || reviewDiagnostic.value || planningText.value || planningReasoning.value || runtime.value?.planning.draft.nodes.length || planningProfile.value || planningHistory.value.length || outputs.value.length || pastOutputs.value.length || props.plan || activity.value.length))
const entries = computed(() => {
  const start = Date.parse(props.startedAt || '') || 0
  const time = (timestamp?: string | null) => {
    const parsed = Date.parse(timestamp || '')
    return Number.isFinite(parsed) ? parsed : start
  }
  const result: ConversationEntry[] = planningHistory.value
    .filter(item => !(props.plan && item.kind === 'completed') && !(planningProfile.value && item.kind === 'stage_completed' && item.stage === 'intent_profile'))
    .map(item => ({ id: `progress:${item.id}`, kind: 'progress', time: time(item.timestamp), items: [{ id: item.id, text: planningProgressText(item), detail: item.detail }] }))
  if (planningProfile.value && !planningHistory.value.some(item => item.kind === 'profile_resolved')) {
    result.push({ id: 'planning-profile', kind: 'progress', time: start, items: [{ id: 'planning-profile', text: planningProfileText(planningProfile.value) }] })
  }
  if (planningText.value || planningReasoning.value || runtime.value?.planning.outputId || !props.plan && (runtime.value?.planning.draft.nodes.length || active.value && (!outputs.value.length && !activity.value.length))) {
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
    else if (entry.kind === 'progress' && previous?.kind === 'progress') previous.items.push(...entry.items)
    else grouped.push(entry)
    return grouped
  }, [])
})
// Group contiguous work by the actual node attempt. Messages and other Agents
// retain their chronological positions; never merge separate attempts by name.
const workGroups = computed(() => {
  const result: Array<{ id: string; key?: string; agent?: WorkOutput; entries: ConversationEntry[] }> = []
  for (const entry of entries.value) {
    const output = entry.kind === 'output' && !entry.output.planning ? entry.output : undefined
    const tool = entry.kind === 'tools' ? entry.items[0] : undefined
    const nodeId = output?.nodeId || tool?.stepId
    const attemptId = output?.attemptId || tool?.attemptId
    const key = nodeId ? JSON.stringify([nodeId, attemptId || '']) : undefined
    const previous = result[result.length - 1]
    if (key && previous?.key === key) { previous.entries.push(entry); continue }
    const node = nodeId ? runtime.value?.nodes?.[nodeId] : undefined
    const agent = nodeId ? { id: nodeId, title: output?.title || node?.title || props.graphNodes.find(n => n.acgNodeId === nodeId)?.name || '步骤执行',
      agentName: output?.agentName || (node && node.currentAttemptId === attemptId ? node.agentName : undefined),
      agentRegistration: output?.agentRegistration || (node && node.currentAttemptId === attemptId ? node.agentRegistration : undefined),
      modelName: output?.modelName || (node && node.currentAttemptId === attemptId ? node.modelName : undefined),
      node: node?.currentAttemptId === attemptId ? node : undefined,
      text: '', timestamp: null, running: false, failed: false, planning: false } : undefined
    result.push({ id: entry.id, key, agent, entries: [entry] })
  }
  return result
})
const toolStatusLabel = (status: string) => ({ completed: '已完成', failed: '失败', running: '执行中', capacity_waiting: '等待执行资源', cancelled: '已取消' } as Record<string, string>)[status] || status
const toolGroupStatus = (items: ToolItem[]) => items.some(item => item.status === 'running') ? 'running' : items.some(item => item.status === 'capacity_waiting') ? 'capacity_waiting' : items.some(item => item.status === 'failed') ? 'failed' : items.every(item => item.status === 'completed') ? 'completed' : items[0].status
watch(() => [planningText.value, planningReasoning.value, runtime.value?.planning.draft.nodes, planningProfile.value, planningHistory.value, outputs.value, pastOutputs.value, props.plan, activity.value, props.workspaceReview, reviewDiagnostic.value], () => {
  emit('content', hasWorkContent.value)
}, { immediate: true })
const toolLabel = (tool: string) => ({ 'fs.read': '读取文件', read_file: '读取文件', 'fs.list': '查看目录', list_files: '查看目录', 'fs.write': '写入文件', write_file: '写入文件', 'fs.patch': '修改文件', patch_file: '修改文件', 'shell.exec': '运行命令', 'command.run': '运行命令', run_tests: '运行测试' } as Record<string, string>)[tool] || tool || '工具操作'
</script>
<style scoped>
.timeline-flow { display: contents; }
.agent-work { margin: 20px 0 28px; padding: 0; min-width: 0; }
.agent-work__heading { position: relative; display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-bottom: 5px; color: var(--wb-text-muted); font-size: 12px; line-height: 1.6; }
.agent-work__heading strong { color: var(--wb-text); font-weight: 600; overflow-wrap: anywhere; }
.agent-work__assignment { display: flex; flex-wrap: wrap; gap: 5px 10px; margin: 0 0 16px 24px; color: var(--wb-text-muted); font-size: 10px; overflow-wrap: anywhere; }
.agent-work__task { flex-basis: 100%; color: var(--wb-text-secondary); font-size: 12px; }
.agent-work__instance, .agent-work__model { font-family: var(--font-mono, monospace); }
.agent-work__pool-link { display: inline-flex; align-items: center; gap: 3px; margin-left: auto; padding: 2px 0 2px 6px; border: 0; background: transparent; color: var(--wb-text-muted); font: inherit; font-size: 10px; cursor: pointer; }
.agent-work__pool-link:hover { color: var(--wb-accent); }
.agent-work__pool-link:focus-visible { outline: 1px solid var(--wb-accent); outline-offset: 3px; }
.agent-work__pool-link svg { width: 10px; height: 10px; }
.agent-work__icon { width: 15px; height: 15px; flex: 0 0 15px; margin-right: 3px; }
.agent-work__heading.is-failed .agent-work__icon { color: var(--wb-danger); }
.agent-work__identity { position: relative; margin: 0 0 0 2px; }
.agent-work__identity > summary { display: flex; padding: 3px; list-style: none; }
.agent-work__identity > summary::-webkit-details-marker { display: none; }
.agent-work__identity > summary svg { width: 13px; height: 13px; }
.agent-work__identity > div { position: absolute; top: 100%; right: 0; z-index: 2; display: grid; gap: 6px; width: max-content; max-width: min(280px, 65vw); padding: 10px 12px; border: 1px solid var(--wb-border-soft); border-radius: 8px; background: var(--wb-surface-1); box-shadow: 0 4px 16px #0002; overflow-wrap: anywhere; }
.agent-work__identity small { font: 10px/1.6 var(--font-mono, monospace); }
.run-timeline__model { color: var(--wb-text-muted); font-size: 11px; }
.run-timeline__tool-result { max-height: 200px; overflow: auto; white-space: pre-wrap; font: 11px/1.6 var(--font-mono, monospace); }
.run-timeline__tool-target { overflow-wrap: anywhere; font-size: 12px; }
.run-timeline__auto-approved, .run-timeline__approval-summary { color: var(--wb-accent); white-space: nowrap; }
.run-timeline__approval-decision { border-top: 1px solid var(--wb-border-soft); padding-top: 6px; }
.run-timeline { min-width: 0; color: var(--wb-text-secondary); font-size: var(--cp-prose-size, 14px); line-height: var(--cp-prose-line-height, 1.75); text-wrap: pretty; }
.run-timeline__status { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 14px; margin: 0 0 22px; color: var(--wb-text-muted); font-size: 11px; }
.run-timeline__history-toggle { display: inline-flex; align-items: center; gap: 7px; min-height: 28px; padding: 0; border: 0; border-radius: 4px; background: transparent; color: inherit; font: inherit; cursor: pointer; }
.run-timeline__history-toggle:hover { color: var(--wb-text); }
.run-timeline__history-toggle:focus-visible, summary:focus-visible { outline: 1px solid var(--wb-accent); outline-offset: 3px; }
.run-timeline__state { display: inline-flex; align-items: center; gap: 6px; }
.run-timeline__review-error { overflow-wrap: anywhere; color: var(--wb-text-secondary); font-size: 10px; }
.run-timeline__dot { width: 5px; height: 5px; flex: 0 0 5px; background: var(--wb-accent); border-radius: 50%; }
.run-timeline__dot.is-active { animation: activity-pulse 1.8s ease-in-out infinite; }
.run-timeline__planning, .run-timeline__plan, .run-timeline__output { margin: 0 0 22px; }
.run-timeline__output { padding: 0; }
.run-timeline__output-heading { display: flex; align-items: baseline; gap: 10px; margin-bottom: 8px; color: var(--wb-text-muted); }
.run-timeline__output-heading h3 { margin: 0; }
.run-timeline__output-heading > small { flex-shrink: 0; color: var(--wb-text-muted); font-size: 11px; }
.run-timeline__approach { margin: 0 0 10px; }
.run-timeline__approach > summary { width: fit-content; font-size: 11px; }
.run-timeline__source-note { margin: 10px 0 0; color: var(--wb-text-muted); }
.run-timeline__source-note > summary { width: fit-content; font-size: 10px; }
.run-timeline__source-note > small { display: block; margin-top: 6px; }
.run-timeline__approach p { margin: 8px 0 0; font-size: 12px; }
p { margin: 0 0 12px; overflow-wrap: anywhere; }
p:last-child { margin-bottom: 0; }
h3 { margin: 0 0 12px; color: var(--wb-text); font-size: 13px; font-weight: 600; }
h3 small { margin-left: 7px; font-size: 10px; font-weight: 400; color: var(--wb-text-muted); }
.run-timeline__objective { white-space: normal; margin-bottom: 12px; }
details { margin: 10px 0; }
summary { cursor: pointer; color: var(--wb-text-muted); border-radius: 4px; font-size: 12px; transition: color 140ms var(--ease-out, ease); }
summary:hover { color: var(--wb-text); }
ol, ul { margin: 10px 0; padding-left: 20px; }
li { margin: 8px 0; overflow-wrap: anywhere; }
li p { margin: 6px 0; }
/* 待确认提示行与下方 conversational 正式控制卡片连成一张确认卡（见 FormalExecutionControls）。 */
.run-timeline__plan:has(> .run-timeline__confirm) { margin-bottom: 0; }
.run-timeline__confirm { display: flex; align-items: center; gap: 8px; margin: 16px 0 0; padding: 11px 16px 10px; border: 1px solid color-mix(in srgb, var(--wb-accent) 40%, var(--cp-border)); border-bottom: 0; border-radius: 12px 12px 0 0; background: color-mix(in srgb, var(--wb-accent) 5%, var(--wb-surface-section)); color: var(--wb-text); font-size: 12px; font-weight: 500; }
.run-timeline__confirm::before { content: ''; flex: 0 0 6px; width: 6px; height: 6px; border-radius: 50%; background: var(--wb-accent); animation: activity-pulse 1.8s ease-in-out infinite; }
.run-timeline__context, .run-timeline__draft-note { color: var(--wb-text-muted); font-size: 11px; }
.run-timeline__context { margin-bottom: 8px; }
.run-timeline__context small { margin-left: 8px; font-size: inherit; }
.run-timeline__draft-note { display: block; margin-top: 8px; }
.run-timeline__failure summary { color: var(--wb-danger); }
.run-timeline__failure p { margin-top: 8px; font: 11px/1.7 var(--font-mono, monospace); }
.run-timeline__tools { margin: 16px 0 22px; }
.run-timeline__tool { margin: 6px 0 6px 18px; }
.run-timeline__tools summary, .run-timeline__progress > summary { display: flex; align-items: center; flex-wrap: wrap; gap: 7px; min-height: 28px; list-style: none; }
.run-timeline__operation-summary { font-size: 13px; }
.run-timeline__operation-icon { width: 15px; height: 15px; flex: 0 0 15px; margin-right: 2px; }
.run-timeline__operation-summary > .run-timeline__chevron { opacity: .45; }
.run-timeline__operation-summary:hover > .run-timeline__chevron { opacity: 1; }
.run-timeline__tools[open] > summary { margin-bottom: 10px; }
.run-timeline__progress { margin: 0 0 16px; }
.run-timeline__progress-item { margin: 8px 0; padding-left: 22px; }
.run-timeline__progress-item :deep(.chat-recovery) { color: var(--wb-text-muted); font-size: 12px; }
.run-timeline__tools summary::-webkit-details-marker { display: none; }
.run-timeline__tools summary small { flex-shrink: 0; font-size: 10px; }
.run-timeline__chevron { width: 11px; height: 11px; flex: 0 0 11px; color: var(--wb-text-muted); transition: transform 160ms var(--ease-out, ease); }
.run-timeline__chevron.is-expanded, details[open] > summary > .run-timeline__chevron { transform: rotate(90deg); }
.run-timeline__tool-name { min-width: 0; overflow-wrap: anywhere; }
.run-timeline__flag { flex-shrink: 0; color: var(--wb-text-muted); font-size: 10px; }
.run-timeline__flag.is-failed { color: var(--wb-danger); }
.run-timeline__flag.is-running { color: var(--wb-accent); }
dl { margin: 6px 0 12px 18px; font-size: 11px; }
dl > div { display: grid; grid-template-columns: 58px minmax(0, 1fr); gap: 8px; align-items: baseline; }
dl > div + div { margin-top: 5px; }
dt { color: var(--wb-text-muted); }
dd { margin: 0; overflow-wrap: anywhere; font: 11px/1.6 var(--font-mono, monospace); }
.run-timeline__text.markdown-body { color: inherit; font-size: inherit; line-height: inherit; }
.run-timeline__text { overflow-wrap: anywhere; }
.run-timeline__text :deep(p) { margin: 0 0 var(--cp-paragraph-gap, .65em); }
.run-timeline__text :deep(ul), .run-timeline__text :deep(ol) { margin: var(--cp-paragraph-gap, .65em) 0; padding-left: 1.5em; }
.run-timeline__text :deep(li) { margin: var(--cp-list-item-gap, .2em) 0; }
.run-timeline__text :deep(p:first-child) { margin-top: 0; }
.run-timeline__text :deep(p:last-child) { margin-bottom: 0; }
.run-timeline__text :deep(pre) { max-width: 100%; overflow: auto; }
@keyframes activity-pulse { 50% { opacity: .35; } }
@media (prefers-reduced-motion: reduce) { .run-timeline__dot.is-active, .run-timeline__confirm::before { animation: none; } .run-timeline__chevron { transition: none; } }
</style>
