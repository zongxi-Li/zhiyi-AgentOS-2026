<template>
  <div class="run-timeline" aria-label="任务执行时间线">
    <p v-if="active || plan || activity.length" class="run-timeline__status" role="status">
      <span class="run-timeline__dot" :class="{ 'is-active': active && !waitingForApproval }" />
      {{ statusText }}<span v-if="elapsed"> · {{ elapsed }}</span>
    </p>
    <article v-if="plan" class="run-timeline__plan">
      <h3>初步规划 <small>版本 {{ plan.planVersion }}</small></h3>
      <p v-if="plan.tasks[0]?.rationale">{{ plan.tasks[0].rationale }}</p>
      <details v-if="plan.objective"><summary>任务目标</summary><p class="run-timeline__objective">{{ plan.objective }}</p></details>
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
      <p v-if="['pending', 'planning'].includes(status)" class="run-timeline__confirm">请检查规划，再通过下方按钮确认继续。</p>
    </article>
    <article v-else-if="active" class="run-timeline__planning">
      <p>{{ planningMessage }}</p>
      <details v-if="runtime?.planning.draft.nodes.length"><summary>正在形成的计划 · {{ runtime.planning.draft.nodes.length }} 个步骤</summary>
        <ul><li v-for="node in runtime.planning.draft.nodes" :key="node.key">{{ node.title }}<p v-if="node.rationale">{{ node.rationale }}</p></li></ul>
      </details>
    </article>
    <slot name="controls" />
    <div v-if="activity.length" class="run-timeline__tools">
      <details v-for="item in activity" :key="item.id" class="run-timeline__tool">
        <summary>
          <span class="run-timeline__chevron" aria-hidden="true">›</span>
          <span class="run-timeline__tool-name">{{ toolLabel(item.tool) }}</span>
          <small class="run-timeline__flag" :class="`is-${item.status}`">{{ item.status === 'completed' ? '已完成' : item.status === 'failed' ? '失败' : '执行中' }}</small>
        </summary>
        <dl><div v-if="item.stepId"><dt>步骤</dt><dd>{{ item.stepId }}</dd></div><div v-if="item.executionId"><dt>执行记录</dt><dd>{{ item.executionId }}</dd></div><div v-if="item.receiptRef"><dt>结果凭据</dt><dd>{{ item.receiptRef }}</dd></div></dl>
      </details>
    </div>
    <slot name="approvals" />
    <div v-if="outputs.length" class="run-timeline__outputs">
      <details v-for="output in outputs" :key="output.id" class="run-timeline__output" :open="output.running">
        <summary>{{ output.title }} <small>{{ output.running ? '正在生成' : output.failed ? '生成已中断' : '生成片段' }}</small></summary>
        <div v-if="output.text" class="run-timeline__text" v-html="renderMarkdown(output.text)"></div>
        <p v-else>正在等待模型正文…</p>
        <small v-if="!output.running">这是本次接收的生成片段，完整结果以步骤交付为准。</small>
      </details>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, shallowRef, watch, ref } from 'vue'
import type { CopilotInitialPlan, CopilotToolActivity } from '@/services/api/agentos/api/copilot'
import { acquireRunRuntimeStore, releaseRunRuntimeStore, type RunRuntimeStore } from '@/workbench/runtime/runtimeEvents'
import { streamingContent } from '@/workbench/runtime/streamingContent'
import { renderMarkdown } from '@/utils/markdown'

const props = withDefaults(defineProps<{ runId: string | null; status: string; plan?: CopilotInitialPlan | null; tools?: CopilotToolActivity[]; startedAt?: string | null; updatedAt?: string | null; waitingForApproval?: boolean }>(), { plan: null, tools: () => [], waitingForApproval: false })
const active = computed(() => ['pending', 'planning', 'running', 'retrying', 'waiting_review'].includes(props.status))
const emit = defineEmits<{ content: [] }>()
const runtime = shallowRef<RunRuntimeStore | null>(null)
const now = ref(Date.now())
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
const outputs = computed(() => Object.entries(runtime.value?.nodes || {}).filter(([, node]) => node.modelStartedAt || node.outputBuffer)
  .slice(-8).map(([id, node]) => ({ id, title: node.title || id, text: streamingContent(node.outputBuffer),
    running: active.value && !['COMPLETED', 'FAILED', 'CANCELLED'].includes(node.status), failed: node.status === 'FAILED' })))
watch(() => outputs.value.map(output => `${output.id}:${output.running}:${output.text}`).join('\0'), () => emit('content'))
const elapsed = computed(() => {
  if (!props.startedAt) return ''
  const end = active.value ? now.value : Date.parse(props.updatedAt || '')
  const seconds = Math.floor((end - Date.parse(props.startedAt)) / 1000)
  if (!Number.isFinite(seconds) || seconds < 0) return ''
  return seconds < 60 ? `${seconds} 秒` : `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`
})
const statusText = computed(() => props.waitingForApproval ? '等待你确认' : ({ pending: '正在准备任务', planning: '正在规划', running: '正在执行', retrying: '正在恢复', waiting_review: '等待审核', failed: '本次运行未完成', completed: '本次运行已完成', cancelled: '本次运行已取消', superseded: '已由后续运行接替' } as Record<string, string>)[props.status] || '等待运行状态')
const planningMessage = computed(() => runtime.value?.planning.stage ? `正在整理规划：${({ profile: '理解目标与约束', tasks: '拆分任务步骤', relations: '梳理步骤依赖', coverage: '检查交付覆盖' } as Record<string, string>)[runtime.value.planning.stage] || '形成执行方案'}` : props.status === 'running' ? '正在处理当前步骤，执行进展将在这里显示。' : '正在理解任务并形成初步规划，完成后会在这里供你确认。')
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
    items.set(id, { id, executionId: p.executionId || '', tool: p.tool || '', status: event.eventType === 'tool.execution_completed' ? p.status || 'completed' : 'running', stepId: event.nodeId || '', createdAt: event.timestamp || '', receiptRef: p.receiptRef })
  }
  return [...items.values()].slice(-100)
})
const toolLabel = (tool: string) => ({ 'fs.read': '读取文件', read_file: '读取文件', 'fs.list': '查看目录', list_files: '查看目录', 'fs.write': '写入文件', write_file: '写入文件', 'fs.patch': '修改文件', patch_file: '修改文件', 'shell.exec': '运行命令', run_tests: '运行测试' } as Record<string, string>)[tool] || tool || '工具操作'
</script>
<style scoped>
.run-timeline { min-width: 0; margin-bottom: 18px; color: var(--wb-text-secondary); font-size: 12px; line-height: 1.75; }
.run-timeline__status { display: flex; align-items: center; gap: 7px; color: var(--wb-text-muted); margin: 0 0 14px; font-size: 11px; }
.run-timeline__dot { width: 6px; height: 6px; flex: 0 0 6px; background: var(--wb-text-muted); border-radius: 50%; }
.run-timeline__dot.is-active { background: var(--wb-accent); animation: activity-pulse 1.8s ease-in-out infinite; }
h3 { margin: 0 0 10px; color: var(--wb-text); font-size: 14px; font-weight: 600; }
h3 small { margin-left: 7px; font-size: 10px; font-weight: 400; color: var(--wb-text-muted); }
.run-timeline__plan { margin-bottom: 14px; padding: 13px 14px 5px; background: var(--wb-surface-section); border: 1px solid var(--wb-border-soft); border-radius: 10px; }
.run-timeline__objective { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0 0 12px; }
details { margin: 9px 0; }
summary { cursor: pointer; color: var(--wb-text-secondary); border-radius: 6px; transition: color 140ms var(--ease-out, ease); }
summary:hover { color: var(--wb-text); }
summary:focus-visible { outline: 1px solid var(--wb-accent); outline-offset: 3px; }
ol, ul { margin: 8px 0; padding-left: 19px; }
li { margin: 5px 0; overflow-wrap: anywhere; }
li p { margin: 6px 0; }
.run-timeline__confirm { color: var(--wb-accent); }
/* 工具调用行：可点卡片行 + 语义状态徽章 + 凭据内嵌面板 */
.run-timeline__tools { margin-top: 14px; border-top: 1px solid var(--wb-border-soft); padding-top: 8px; }
.run-timeline__tool { margin: 2px 0; }
.run-timeline__tool summary { display: flex; align-items: center; gap: 8px; list-style: none; padding: 6px 8px; border-radius: var(--wb-radius-md); font-size: 12px; color: var(--wb-text-secondary); transition: background-color 140ms var(--ease-out, ease), color 140ms var(--ease-out, ease); }
.run-timeline__tool summary::-webkit-details-marker { display: none; }
.run-timeline__tool summary:hover { background: var(--wb-hover); color: var(--wb-text); }
.run-timeline__chevron { flex-shrink: 0; color: var(--wb-text-muted); font-size: 11px; line-height: 1; transition: transform 160ms var(--ease-out, ease); }
.run-timeline__tool[open] .run-timeline__chevron { transform: rotate(90deg); }
.run-timeline__tool-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.run-timeline__flag { display: inline-flex; align-items: center; gap: 5px; flex-shrink: 0; margin-left: auto; padding: 1px 8px; border: 1px solid var(--wb-border-soft); border-radius: 999px; background: var(--wb-surface-section); color: var(--wb-text-muted); font-size: 10px; line-height: 1.7; }
.run-timeline__flag.is-completed { color: var(--wb-success); border-color: color-mix(in srgb, var(--wb-success) 30%, transparent); background: color-mix(in srgb, var(--wb-success) 10%, transparent); }
.run-timeline__flag.is-failed { color: var(--wb-danger); border-color: color-mix(in srgb, var(--wb-danger) 32%, transparent); background: color-mix(in srgb, var(--wb-danger) 10%, transparent); }
.run-timeline__flag.is-running { color: var(--wb-accent); border-color: color-mix(in srgb, var(--wb-accent) 30%, transparent); background: color-mix(in srgb, var(--wb-accent) 9%, transparent); }
.run-timeline__flag.is-running::before { content: ''; width: 5px; height: 5px; flex: 0 0 5px; border-radius: 50%; background: currentColor; animation: activity-pulse 1.8s ease-in-out infinite; }
dl { margin: 4px 8px 8px 26px; padding: 9px 12px; background: color-mix(in srgb, var(--bg-input) 60%, transparent); border-radius: var(--wb-radius-md); font-size: 11px; }
dl > div { display: grid; grid-template-columns: 58px minmax(0, 1fr); gap: 8px; align-items: baseline; }
dl > div + div { margin-top: 6px; }
dt { color: var(--wb-text-muted); font-size: 10px; }
dd { margin: 0; overflow-wrap: anywhere; font: 11px/1.6 var(--font-mono, monospace); color: var(--wb-text-secondary); }
@keyframes activity-pulse { 50% { opacity: .35; } }
@media (prefers-reduced-motion: reduce) { .run-timeline__dot.is-active, .run-timeline__flag.is-running::before { animation: none; } }
.run-timeline__outputs { margin-top: 16px; }
.run-timeline__output { padding: 10px 0; border-top: 1px solid var(--wb-border-soft); }
.run-timeline__output summary { display: flex; gap: 8px; align-items: baseline; }
.run-timeline__output small { color: var(--wb-text-muted); font-size: 10px; }
.run-timeline__text { overflow-wrap: anywhere; }
.run-timeline__text :deep(pre) { max-width: 100%; overflow: auto; }
</style>
