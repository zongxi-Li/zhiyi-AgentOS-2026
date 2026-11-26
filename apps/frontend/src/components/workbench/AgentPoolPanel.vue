<template>
  <section class="agent-pool" aria-label="Agent 执行池">
    <div v-if="run" class="pool-tabs" aria-label="执行池范围">
      <button type="button" :aria-pressed="scope === 'run'" @click="scope = 'run'">当前任务</button>
      <button type="button" :aria-pressed="scope === 'all'" @click="scope = 'all'">全部执行资源</button>
    </div>
    <section v-if="run && scope === 'run'" class="pool-list" aria-label="当前任务步骤">
      <p v-if="!run.steps.length" class="pool-state">等待任务步骤。</p>
      <details v-for="entry in runSteps" :key="entry.step.stepId" :open="entry.step.stepId === selectedStepId || entry.step.status === 'running' || !!entry.scheduling" class="pool-card pool-step" :class="`status-${entry.step.status}`">
        <summary><strong>{{ entry.step.name || entry.step.stepId }}</strong><span class="step-state">{{ stepLabel(entry.step.status, entry.scheduling?.status) }}</span></summary>
        <p v-if="entry.capabilities.length">所需能力 · {{ entry.capabilities.join('、') }}</p>
        <p v-if="entry.scheduling?.reason">{{ schedulingLabel(entry.scheduling.reason, entry.scheduling.capacityBlockers) }}</p>
        <template v-if="entry.binding">
          <p v-if="entry.binding.agentRegistration">
            Agent 实例 · {{ entry.binding.agentRegistration.instanceId }} · 第 {{ entry.binding.agentRegistration.generation }} 代
            <router-link :to="resourceLink(entry.binding.agentRegistration.resourceId)">查看实例</router-link>
          </p>
          <p>
            执行服务 · {{ hostName(entry.binding.resourceId) }}
            <router-link :to="resourceLink(entry.binding.resourceId)">查看执行服务</router-link>
          </p>
          <p>分配依据 · {{ selectionLabel(entry.binding) }}</p>
        </template>
        <details v-if="entry.history.length" class="pool-history">
          <summary>历史绑定 · {{ entry.history.length }} 次</summary>
          <p v-for="binding in entry.history" :key="binding.attemptId">
            <router-link v-if="binding.agentRegistration" :to="resourceLink(binding.agentRegistration.resourceId)">
              {{ binding.agentRegistration.instanceId }} · 第 {{ binding.agentRegistration.generation }} 代
            </router-link>
            <router-link :to="resourceLink(binding.resourceId)">{{ binding.resourceId }}</router-link>
          </p>
        </details>
      </details>
    </section>
    <template v-else>
    <header class="pool-summary">
      <div class="pool-summary__count"><strong>{{ snapshot?.total || 0 }}</strong><span>个执行实例</span><span v-if="remoteHosts.length" class="pool-summary__remote"> · {{ remoteHosts.length }} 个远程执行服务</span></div>
      <div class="pool-summary__stats"><span><b>{{ runningCount }}</b> 个可见运行步骤</span><span><b>{{ busyCount }}</b> 个实例占用中</span></div>
      <button class="refresh" type="button" :disabled="loading" @click="load">{{ loading ? '读取中' : '刷新' }}</button>
    </header>

    <div v-if="error" class="pool-state is-error" role="alert">{{ error }}<button type="button" @click="load">重试</button></div>
    <div v-else-if="loading && !snapshot" class="pool-state" role="status">正在读取执行池…</div>
    <div v-else-if="!snapshot?.instances.length && !remoteHosts.length" class="pool-state"><strong>当前没有可观察的执行资源</strong></div>
    <div v-else class="pool-list">
      <p v-if="selectedInstanceId && !snapshot.instances.some(instance => instance.registration.instanceId === selectedInstanceId)" class="pool-selection-note">该执行记录对应的实例 {{ selectedInstanceId }} 当前不在执行池中，以下为当前可观测实例。</p>
      <article v-for="instance in displayedInstances" :key="instance.resourceId" class="pool-card" :class="{ 'is-busy': instance.activeSlots > 0, 'is-draining': instance.draining, 'is-selected': instance.registration.instanceId === selectedInstanceId }" :aria-label="instance.registration.instanceId === selectedInstanceId ? '当前执行记录对应的 Agent 实例' : undefined">
        <div class="pool-card__head">
          <span class="agent-signal" :class="signalClass(instance)"></span>
          <div class="agent-title"><strong>{{ instance.agentName }}</strong><small>{{ instance.agentId }} · {{ instance.registration.instanceId }} · gen {{ instance.registration.generation }}</small></div>
          <span class="agent-state" :class="stateClass(instance)">{{ stateLabel(instance) }}</span>
        </div>
        <div class="pool-card__meta"><span>{{ instance.host.environment }} · {{ instance.host.displayName }}</span><span>{{ instance.activeSlots }}/{{ instance.capacity }} 槽位</span></div>
        <div class="pool-links"><router-link :to="resourceLink(instance.resourceId)">查看实例</router-link><router-link :to="resourceLink(instance.host.runtimeId)">查看宿主</router-link></div>
        <div class="capabilities"><span v-for="capability in instance.capabilities.slice(0, 4)" :key="capability">{{ capability }}</span><em v-if="instance.capabilities.length > 4">+{{ instance.capabilities.length - 4 }}</em></div>
        <div v-if="instance.activeSteps.length" class="active-steps">
          <div class="active-steps__label"><span class="pulse"></span>正在执行</div>
          <button v-for="step in instance.activeSteps" :key="`${step.runId}:${step.stepId}`" type="button" class="active-step" @click="$emit('select-run', step.runId)">
            <span><strong>{{ step.stepName || step.stepId }}</strong><small>{{ step.runId }} · {{ formatStarted(step.startedAt) }}</small></span><span class="step-arrow">↗</span>
          </button>
        </div>
        <div v-else class="idle-note">空闲 · 健康检查 {{ instance.health.healthy ? '正常' : '待确认' }}</div>
      </article>
      <article v-for="host in remoteHosts" :key="host.resourceId" class="pool-card">
        <div class="pool-card__head"><strong>{{ host.displayName || host.resourceId }}</strong><span class="agent-state" :class="stateClass(host)">{{ stateLabel(host) }}</span></div>
        <div class="pool-card__meta"><span>{{ host.environment }} · 远程执行服务</span><span>{{ host.activeSlots }}/{{ host.capacity }} 槽位</span></div>
        <div class="pool-links"><router-link :to="resourceLink(host.resourceId)">查看执行服务</router-link></div>
        <div v-if="host.activeSteps.length" class="active-steps">
          <button v-for="step in host.activeSteps" :key="`${step.runId}:${step.stepId}`" type="button" class="active-step" @click="$emit('select-run', step.runId)">
            <span><strong>{{ step.stepName || step.stepId }}</strong><small>{{ step.runId }} · {{ formatStarted(step.startedAt) }}</small></span><span class="step-arrow">↗</span>
          </button>
        </div>
      </article>
    </div>
    <footer v-if="snapshot" class="pool-foot">观测于 {{ formatObserved(snapshot.observedAt) }}</footer>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { agentosApi, type AgentPoolInstance, type AgentPoolSnapshot } from '@/services/api/agentos'
import type { WorkflowRun } from '@/services/api/agentos'
import type { AgentPoolHost, StepResourceBinding } from '@/services/api/agentos/types/agentPool'

defineEmits<{ 'select-run': [runId: string] }>()
const props = defineProps<{ selectedInstanceId?: string | null; selectedStepId?: string | null; run?: WorkflowRun | null }>()
const snapshot = ref<AgentPoolSnapshot | null>(null)
const scope = ref<'run' | 'all'>('run')
// 只在 Run 或选中步骤真正变化时回到「当前任务」。
// 不能用 `() => [runId, stepId]`：轮询会换新的 run 对象，getter 每次返回新数组，
// 引用比较必然触发，用户切到「全部执行资源」后过几秒就会被重置。
watch(
  [() => props.run?.runId, () => props.selectedStepId],
  () => { if (props.run) scope.value = 'run' },
)
const remoteHosts = computed(() => snapshot.value?.hosts?.filter(host => host.remote) || [])
const runSteps = computed(() => {
  const state = props.run?.executionState
  const historyByStep = new Map<string, StepResourceBinding[]>()
  for (const decision of state?.schedulingDecisions || []) {
    if (!decision.binding) continue
    const entries = historyByStep.get(decision.stepId) || []
    entries.push(decision.binding)
    historyByStep.set(decision.stepId, entries)
  }
  return (props.run?.steps || []).map(step => {
    const scheduling = state?.schedulingStates?.[step.stepId]
      || (step.status === 'failed' ? state?.schedulingFailures?.[step.stepId] : undefined)
    const allocated = state?.executionBindings?.[step.stepId]
    const binding = scheduling ? undefined : allocated
    const capabilities = state?.bindingRequirements?.[step.stepId]?.requiredCapabilities || (step.capability ? [step.capability] : [])
    return { step, scheduling, binding, capabilities,
      history: (historyByStep.get(step.stepId) || []).filter(item => item.attemptId !== binding?.attemptId).reverse() }
  })
})
const resourceLink = (resourceId: string) => ({ path: '/agentos/resources', query: { resourceId } })
const hostName = (resourceId: string) => snapshot.value?.hosts?.find(host => host.resourceId === resourceId)?.displayName || resourceId
const stepStatuses: Record<string, string> = { pending: '待执行', running: '执行中', completed: '已完成', succeeded: '已完成', failed: '失败', cancelled: '已取消', skipped: '已跳过', skipped_by_condition: '已跳过', waiting_review: '待审核', retrying: '重试中' }
const stepLabel = (status: string, scheduling?: string) => scheduling === 'queued' ? '排队中' : scheduling === 'rejected' ? '无法分配' : stepStatuses[status] || status
function schedulingLabel(reason: string, blockers?: string[]) {
  if (reason === 'NO_ELIGIBLE_RESOURCE') return '没有满足此步骤要求的执行资源。'
  if (reason === 'NO_MODEL_ENDPOINT') return '没有符合要求的模型端点。'
  if (reason !== 'NO_CAPACITY') return reason
  const labels: Record<string, string> = { HOST_CAPACITY: '宿主槽位已满', INSTANCE_CAPACITY: '实例槽位已满', RESOURCE_CHANGED: '资源状态正在变化' }
  return blockers?.length ? blockers.map(blocker => labels[blocker] || blocker).join(' · ') : '等待可用槽位。'
}
function selectionLabel(binding: StepResourceBinding) {
  if (!binding.metadata) return '已记录执行绑定。'
  return [
    binding.metadata.agentRoleMatched === true ? `匹配角色偏好${binding.metadata.agentRole ? `（${binding.metadata.agentRole}）` : ''}` : null,
    Number.isFinite(binding.metadata.score) ? `宿主调度评分 ${binding.metadata.score!.toFixed(2)}` : null,
  ].filter(Boolean).join(' · ') || '已记录执行绑定。'
}
const displayedInstances = computed(() => {
  const instances = snapshot.value?.instances || []
  const selected = instances.find(instance => instance.registration.instanceId === props.selectedInstanceId)
  return selected ? [selected, ...instances.filter(instance => instance !== selected)] : instances
})
const loading = ref(false)
const error = ref('')
let timer: ReturnType<typeof setInterval> | undefined
let controller: AbortController | undefined
const runningCount = computed(() => [...(snapshot.value?.instances || []), ...remoteHosts.value].reduce((total, item) => total + item.activeSteps.length, 0))
const busyCount = computed(() => snapshot.value?.instances.filter(item => item.activeSlots > 0).length || 0)

async function load() {
  if (loading.value) return
  controller = new AbortController(); const current = controller
  loading.value = true; error.value = ''
  try { const next = await agentosApi.getAgentPool({ signal: current.signal }); if (controller === current) snapshot.value = next }
  catch (err: any) { if (!current.signal.aborted && controller === current) error.value = err?.response?.status === 401 ? '请先登录后查看执行池。' : '暂时无法读取执行池状态。' }
  finally { if (controller === current) loading.value = false }
}
function signalClass(item: AgentPoolInstance) {
  if (item.outcomeUnknown) return 'is-unknown'
  if (item.draining) return 'is-draining'
  if (!item.enabled) return 'is-muted'
  if (item.activeSlots) return 'is-busy'
  return item.health.healthy ? 'is-ready' : 'is-waiting'
}
function stateLabel(item: AgentPoolHost | AgentPoolInstance) { return 'outcomeUnknown' in item && item.outcomeUnknown ? '结果待核对' : item.draining ? '排空中' : !item.enabled ? '已停用' : item.activeSlots ? '执行中' : item.health.healthy ? '就绪' : '待检测' }
function stateClass(item: AgentPoolHost | AgentPoolInstance) {
  if ('outcomeUnknown' in item && item.outcomeUnknown) return 'is-unknown'
  if (item.draining) return 'is-draining'
  if (!item.enabled) return 'is-off'
  if (item.activeSlots) return 'is-busy'
  return item.health.healthy ? 'is-ready' : 'is-waiting'
}
function formatObserved(value: string) { return value ? new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—' }
function formatStarted(value?: string | null) { return value ? new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '刚刚' }
onMounted(() => { void load(); timer = setInterval(() => { if (!document.hidden) void load() }, 4000) })
onBeforeUnmount(() => { controller?.abort(); if (timer) clearInterval(timer) })
</script>

<style scoped>
.agent-pool { display:flex; flex-direction:column; width:100%; height:100%; min-height:0; color:var(--wb-text); background:var(--wb-surface-1); font-family:var(--font-sans,sans-serif); --pool-border:var(--wb-border-soft); }
button { font:inherit; cursor:pointer; }
button:focus-visible { outline:2px solid var(--wb-accent); outline-offset:2px; }
/* 范围切换：分段胶囊，和下方列表左缘对齐。 */
.pool-tabs { display:inline-flex; align-self:flex-start; gap:2px; margin:12px 14px 0; padding:3px; border:1px solid var(--pool-border); border-radius:9px; background:var(--wb-surface-inset); }
.pool-tabs button { padding:5px 12px; border:0; border-radius:7px; background:transparent; color:var(--wb-text-muted); font-size:11px; line-height:1.45; transition:color .16s, background-color .16s, box-shadow .16s; }
.pool-tabs button:hover { color:var(--wb-text); }
.pool-tabs button[aria-pressed="true"] { color:var(--wb-text); background:var(--wb-surface-section); box-shadow:0 1px 2px rgba(0,0,0,.28), inset 0 0 0 1px color-mix(in srgb,var(--wb-text-muted) 18%,transparent); }

/* 摘要：大数字 + 右对齐统计 + 刷新。 */
.pool-summary { display:flex; flex-wrap:wrap; align-items:center; gap:8px 12px; padding:12px 16px 11px; border-bottom:1px solid var(--pool-border); }
.pool-summary__count { display:flex; flex-wrap:wrap; align-items:baseline; gap:0 5px; min-width:0; }
.pool-summary__count strong { font:600 26px/1 var(--font-mono,monospace); letter-spacing:-.03em; }
.pool-summary__count > span { color:var(--wb-text-muted); font-size:11px; }
.pool-summary__remote { color:var(--wb-text-secondary) !important; }
.pool-summary__stats { margin-left:auto; display:grid; gap:1px; color:var(--wb-text-muted); font-size:10px; text-align:right; }
.pool-summary__stats b { color:var(--wb-text); font:600 11px var(--font-mono,monospace); }
.refresh { display:inline-flex; align-items:center; gap:5px; flex:0 0 auto; padding:5px 9px; border:1px solid var(--pool-border); border-radius:7px; background:var(--wb-surface-section); color:var(--wb-text-secondary); font-size:10px; transition:color .16s, border-color .16s; }
.refresh:hover:not(:disabled) { color:var(--wb-text); border-color:color-mix(in srgb,var(--wb-accent) 40%,var(--pool-border)); }
.refresh:disabled { color:var(--wb-text-muted); cursor:default; }
.refresh:disabled::before { content:''; width:8px; height:8px; border:1.5px solid currentColor; border-right-color:transparent; border-radius:50%; animation:spin .9s linear infinite; }

/* 列表容器：卡片之间用 gap 控制间距，滚动条只在列表内出现。 */
.pool-list { flex:1; min-height:0; overflow:auto; padding:12px 14px 16px; display:flex; flex-direction:column; gap:8px; }
.pool-selection-note { margin:0; padding:9px 11px; border:1px dashed var(--pool-border); border-radius:9px; color:var(--wb-text-muted); font-size:10px; line-height:1.6; overflow-wrap:anywhere; }
.pool-card { padding:12px; border:1px solid var(--pool-border); border-radius:11px; background:var(--wb-surface-section); }
.pool-card.is-busy { border-color:color-mix(in srgb,var(--wb-accent) 38%,var(--pool-border)); box-shadow:inset 2px 0 0 color-mix(in srgb,var(--wb-accent) 55%,transparent); }
.pool-card.is-selected { border-color:color-mix(in srgb,var(--wb-accent) 65%,var(--pool-border)); box-shadow:0 0 0 1px color-mix(in srgb,var(--wb-accent) 30%,transparent); }
.pool-card.is-draining { opacity:.78; }

/* 当前任务：步骤卡。状态点、名称、状态胶囊、展开箭头放在同一条基线上。 */
.pool-step { padding:0; overflow:hidden; }
.pool-step > summary { display:flex; align-items:center; gap:9px; padding:11px 12px; cursor:pointer; list-style:none; }
.pool-step > summary::-webkit-details-marker { display:none; }
.pool-step > summary::before { content:''; width:6px; height:6px; flex:0 0 auto; border-radius:50%; background:var(--wb-text-muted); box-shadow:0 0 0 3px color-mix(in srgb,var(--wb-text-muted) 14%,transparent); }
.pool-step > summary strong { flex:1; min-width:0; color:var(--wb-text); font-size:12px; font-weight:600; line-height:1.5; overflow-wrap:anywhere; }
.step-state { flex:0 0 auto; padding:2px 7px; border-radius:999px; background:color-mix(in srgb,var(--wb-text-muted) 12%,transparent); color:var(--wb-text-muted); font-size:10px; line-height:1.5; white-space:nowrap; }
.pool-step > summary::after { content:''; width:6px; height:6px; flex:0 0 auto; margin-left:1px; border-right:1.5px solid var(--wb-text-muted); border-bottom:1.5px solid var(--wb-text-muted); transform:rotate(-45deg); transition:transform .18s ease; }
.pool-step[open] > summary::after { transform:rotate(45deg); }
.pool-step[open] > summary { background:color-mix(in srgb,var(--wb-surface-inset) 55%,transparent); }
.status-completed > summary::before { background:var(--wb-success); box-shadow:0 0 0 3px color-mix(in srgb,var(--wb-success) 14%,transparent); }
.status-completed .step-state { background:color-mix(in srgb,var(--wb-success) 13%,transparent); color:var(--wb-success); }
.status-failed > summary::before { background:var(--wb-danger); box-shadow:0 0 0 3px color-mix(in srgb,var(--wb-danger) 14%,transparent); }
.status-failed .step-state { background:color-mix(in srgb,var(--wb-danger) 13%,transparent); color:var(--wb-danger); }
.status-cancelled > summary::before,
.status-skipped > summary::before,
.status-skipped_by_condition > summary::before { background:var(--wb-text-muted); }
.status-running > summary::before { background:var(--wb-accent); box-shadow:0 0 0 3px color-mix(in srgb,var(--wb-accent) 16%,transparent); animation:pulse 1.5s ease-in-out infinite; }
.status-running .step-state { background:color-mix(in srgb,var(--wb-accent) 14%,transparent); color:var(--wb-accent); }
.status-waiting_review > summary::before,
.status-retrying > summary::before { background:var(--wb-warning); box-shadow:0 0 0 3px color-mix(in srgb,var(--wb-warning) 14%,transparent); }
.status-waiting_review .step-state,
.status-retrying .step-state { background:color-mix(in srgb,var(--wb-warning) 14%,transparent); color:var(--wb-warning); }
.pool-step > p { margin:0; padding:0 12px 10px 27px; color:var(--wb-text-muted); font-size:10.5px; line-height:1.65; overflow-wrap:anywhere; }
.pool-step a { color:var(--wb-accent); text-decoration:none; }
.pool-step a:hover { text-decoration:underline; text-underline-offset:2px; }
.pool-step a + a { margin-inline-start:8px; }
.pool-history { margin:0 12px 11px 27px; padding-top:9px; border-top:1px solid var(--pool-border); }
.pool-history summary { cursor:pointer; color:var(--wb-text-muted); font-size:10px; }
.pool-history p { margin:5px 0 0; color:var(--wb-text-secondary); font-size:10px; line-height:1.6; overflow-wrap:anywhere; }

/* 全部执行资源：实例卡。 */
.pool-card__head,.pool-card__meta { display:flex; align-items:center; gap:8px; }
.pool-card__head { min-width:0; }
.agent-signal { width:7px; height:7px; flex:0 0 auto; border-radius:50%; background:var(--wb-text-muted); }
.agent-signal.is-ready { background:var(--wb-success); box-shadow:0 0 0 3px color-mix(in srgb,var(--wb-success) 15%,transparent); }
.agent-signal.is-busy { background:var(--wb-accent); box-shadow:0 0 0 3px color-mix(in srgb,var(--wb-accent) 16%,transparent); }
.agent-signal.is-waiting { background:var(--wb-warning); box-shadow:0 0 0 3px color-mix(in srgb,var(--wb-warning) 14%,transparent); }
.agent-signal.is-draining { background:var(--wb-warning); }
.agent-signal.is-unknown { background:var(--wb-danger); }
.agent-signal.is-muted { background:var(--wb-text-muted); }
.agent-title { display:grid; gap:1px; min-width:0; }
.agent-title strong { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:12px; font-weight:600; }
.agent-title small { color:var(--wb-text-muted); font:9px var(--font-mono,monospace); overflow-wrap:anywhere; }
.agent-state { margin-left:auto; padding:2px 7px; border:1px solid var(--pool-border); border-radius:999px; background:var(--wb-surface-inset); color:var(--wb-text-secondary); font-size:9.5px; white-space:nowrap; }
.agent-state.is-ready { border-color:color-mix(in srgb,var(--wb-success) 30%,transparent); background:color-mix(in srgb,var(--wb-success) 12%,transparent); color:var(--wb-success); }
.agent-state.is-busy { border-color:color-mix(in srgb,var(--wb-accent) 34%,transparent); background:color-mix(in srgb,var(--wb-accent) 13%,transparent); color:var(--wb-accent); }
.agent-state.is-waiting,
.agent-state.is-draining { border-color:color-mix(in srgb,var(--wb-warning) 30%,transparent); background:color-mix(in srgb,var(--wb-warning) 12%,transparent); color:var(--wb-warning); }
.agent-state.is-unknown { border-color:color-mix(in srgb,var(--wb-danger) 30%,transparent); background:color-mix(in srgb,var(--wb-danger) 12%,transparent); color:var(--wb-danger); }
.pool-card__meta { justify-content:space-between; margin:10px 0 9px 15px; color:var(--wb-text-muted); font-size:10px; }
.pool-links { display:flex; flex-wrap:wrap; gap:6px; margin-left:15px; }
.pool-links a { padding:3px 8px; border:1px solid transparent; border-radius:6px; background:transparent; color:var(--wb-text-secondary); font-size:10px; text-decoration:none; transition:color .16s, border-color .16s, background-color .16s; }
.pool-links a:hover { color:var(--wb-accent); border-color:color-mix(in srgb,var(--wb-accent) 30%,transparent); background:var(--wb-accent-soft); }
.capabilities { display:flex; flex-wrap:wrap; gap:4px; margin:9px 0 0 15px; }
.capabilities span,.capabilities em { padding:2px 6px; border:0; border-radius:5px; background:color-mix(in srgb,var(--wb-surface-inset) 85%,transparent); color:var(--wb-text-muted); font:9px var(--font-mono,monospace); }
.capabilities em { color:var(--wb-text-secondary); font-style:normal; }
.active-steps { margin:11px 0 0 15px; padding-top:9px; border-top:1px solid var(--pool-border); }
.active-steps__label { display:flex; align-items:center; gap:5px; margin-bottom:5px; color:var(--wb-success); font-size:10px; }
.pulse { width:5px; height:5px; border-radius:50%; background:currentColor; animation:pulse 1.5s ease-in-out infinite; }
.active-step { display:flex; align-items:center; justify-content:space-between; width:100%; padding:7px 8px; margin:0 -8px; border:0; border-radius:7px; background:transparent; color:inherit; text-align:left; }
.active-step:hover { background:var(--wb-surface-inset); }
.active-step:hover strong { color:var(--wb-accent); }
.active-step span:first-child { display:grid; gap:2px; min-width:0; }
.active-step strong { font-size:11px; font-weight:500; }
.active-step small { color:var(--wb-text-muted); font:9px var(--font-mono,monospace); }
.step-arrow { color:var(--wb-text-muted); }
.idle-note { display:flex; align-items:center; gap:6px; margin:11px 0 0 15px; padding-top:9px; border-top:1px solid var(--pool-border); color:var(--wb-text-muted); font-size:10px; }
.idle-note::before { content:''; width:5px; height:5px; border-radius:50%; background:currentColor; opacity:.7; }

.pool-state { display:grid; flex:1; place-content:center; gap:6px; padding:20px; color:var(--wb-text-muted); font-size:11px; text-align:center; }
.pool-state strong { color:var(--wb-text); font-size:12px; }
.pool-state button { margin:auto; border:0; background:transparent; color:var(--wb-accent); }
.pool-state.is-error { color:var(--wb-danger); }
.pool-foot { padding:8px 16px 10px; border-top:1px solid var(--pool-border); color:var(--wb-text-muted); font-size:9px; letter-spacing:.02em; }
@keyframes pulse { 0%,100% { opacity:.35; transform:scale(.8); } 50% { opacity:1; transform:scale(1.15); } }
@keyframes spin { to { transform:rotate(360deg); } }
</style>
