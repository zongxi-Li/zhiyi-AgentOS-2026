<template>
  <section class="agent-pool" aria-label="Agent 执行池">
    <header class="pool-summary">
      <div><span class="pool-kicker">LIVE EXECUTION POOL</span><strong>{{ snapshot?.total || 0 }}</strong><span>个执行实例</span></div>
      <div class="pool-summary__stats"><span><b>{{ runningCount }}</b> 并行任务</span><span><b>{{ busyCount }}</b> 个实例占用中</span></div>
      <button class="refresh" type="button" :disabled="loading" @click="load">{{ loading ? '读取中' : '刷新' }}</button>
    </header>

    <div v-if="error" class="pool-state is-error" role="alert">{{ error }}<button type="button" @click="load">重试</button></div>
    <div v-else-if="loading && !snapshot" class="pool-state" role="status">正在读取执行池…</div>
    <div v-else-if="!snapshot?.instances.length" class="pool-state"><strong>当前没有可观察的执行实例</strong><span>AgentPool 会在服务完成本地装配后显示实例。</span></div>
    <div v-else class="pool-list">
      <article v-for="instance in snapshot.instances" :key="instance.resourceId" class="pool-card" :class="{ 'is-busy': instance.activeSlots > 0, 'is-draining': instance.draining }">
        <div class="pool-card__head">
          <span class="agent-signal" :class="signalClass(instance)"></span>
          <div class="agent-title"><strong>{{ instance.agentName }}</strong><small>{{ instance.agentId }} · gen {{ instance.registration.generation }}</small></div>
          <span class="agent-state">{{ stateLabel(instance) }}</span>
        </div>
        <div class="pool-card__meta"><span>{{ instance.host.environment }} · {{ instance.host.displayName }}</span><span>{{ instance.activeSlots }}/{{ instance.capacity }} 槽位</span></div>
        <div class="capabilities"><span v-for="capability in instance.capabilities.slice(0, 4)" :key="capability">{{ capability }}</span><em v-if="instance.capabilities.length > 4">+{{ instance.capabilities.length - 4 }}</em></div>
        <div v-if="instance.activeSteps.length" class="active-steps">
          <div class="active-steps__label"><span class="pulse"></span>正在执行</div>
          <button v-for="step in instance.activeSteps" :key="`${step.runId}:${step.stepId}`" type="button" class="active-step" @click="$emit('select-run', step.runId)">
            <span><strong>{{ step.stepName || step.stepId }}</strong><small>{{ step.runId }} · {{ formatStarted(step.startedAt) }}</small></span><span class="step-arrow">↗</span>
          </button>
        </div>
        <div v-else class="idle-note">空闲 · 健康检查 {{ instance.health.healthy ? '正常' : '待确认' }}</div>
      </article>
    </div>
    <footer v-if="snapshot" class="pool-foot">观测于 {{ formatObserved(snapshot.observedAt) }} · 任务只显示当前用户可见的运行实例</footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { agentosApi, type AgentPoolInstance, type AgentPoolSnapshot } from '@/services/api/agentos'

defineEmits<{ 'select-run': [runId: string] }>()
const snapshot = ref<AgentPoolSnapshot | null>(null)
const loading = ref(false)
const error = ref('')
let timer: ReturnType<typeof setInterval> | undefined
let controller: AbortController | undefined
const runningCount = computed(() => snapshot.value?.instances.reduce((total, item) => total + item.activeSteps.length, 0) || 0)
const busyCount = computed(() => snapshot.value?.instances.filter(item => item.activeSlots > 0).length || 0)

async function load() {
  controller?.abort(); controller = new AbortController(); const current = controller
  loading.value = true; error.value = ''
  try { const next = await agentosApi.getAgentPool({ signal: current.signal }); if (controller === current) snapshot.value = next }
  catch (err: any) { if (!current.signal.aborted && controller === current) error.value = err?.response?.status === 401 ? '请先登录后查看执行池。' : '暂时无法读取执行池状态。' }
  finally { if (controller === current) loading.value = false }
}
function signalClass(item: AgentPoolInstance) { return item.outcomeUnknown ? 'is-unknown' : item.draining ? 'is-draining' : item.health.healthy && item.enabled ? 'is-ready' : 'is-muted' }
function stateLabel(item: AgentPoolInstance) { return item.outcomeUnknown ? '结果待核对' : item.draining ? '排空中' : !item.enabled ? '已停用' : item.activeSlots ? '执行中' : item.health.healthy ? '就绪' : '待检测' }
function formatObserved(value: string) { return value ? new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—' }
function formatStarted(value?: string | null) { return value ? new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '刚刚' }
onMounted(() => { void load(); timer = setInterval(() => { if (!document.hidden) void load() }, 4000) })
onBeforeUnmount(() => { controller?.abort(); if (timer) clearInterval(timer) })
</script>

<style scoped>
.agent-pool { display:flex; flex-direction:column; width:100%; height:100%; min-height:0; color:var(--wb-text); background:var(--wb-surface-1); font-family:var(--font-sans,sans-serif); --pool-border:var(--wb-border-soft); }
button { font:inherit; cursor:pointer; }
button:focus-visible { outline:2px solid var(--wb-accent); outline-offset:2px; }
.pool-summary { display:grid; grid-template-columns:1fr auto auto; gap:12px; align-items:center; padding:14px 16px 12px; border-bottom:1px solid var(--pool-border); }
.pool-summary > div:first-child { display:grid; grid-template-columns:auto auto; gap:4px 8px; align-items:baseline; }
.pool-kicker { grid-column:1/-1; color:var(--wb-accent); font:9px var(--font-mono,monospace); letter-spacing:.04em; }
.pool-summary strong { font:500 30px/1 var(--font-mono,monospace); }
.pool-summary > div:first-child > span:last-child { color:var(--wb-text-secondary); font-size:11px; }
.pool-summary__stats { display:grid; gap:3px; color:var(--wb-text-muted); font-size:10px; text-align:right; }
.pool-summary__stats b { color:var(--wb-text); font:500 12px var(--font-mono,monospace); }
.refresh { padding:5px 8px; border:1px solid var(--pool-border); border-radius:5px; background:transparent; color:var(--wb-text-secondary); font-size:10px; }
.pool-list { flex:1; min-height:0; overflow:auto; padding:14px 16px; }
.pool-card { margin-bottom:10px; padding:12px; border:1px solid var(--pool-border); border-radius:9px; background:var(--wb-surface-section); }
.pool-card.is-busy { border-color:color-mix(in srgb,var(--wb-accent) 45%,var(--pool-border)); }
.pool-card.is-draining { opacity:.76; }
.pool-card__head,.pool-card__meta { display:flex; align-items:center; gap:8px; }
.pool-card__head { min-width:0; }
.agent-signal { width:7px; height:7px; flex:0 0 auto; border-radius:50%; background:var(--wb-text-muted); }
.agent-signal.is-ready,.agent-signal.is-busy { background:var(--wb-success); box-shadow:0 0 0 3px color-mix(in srgb,var(--wb-success) 15%,transparent); }
.agent-signal.is-draining { background:var(--wb-warning); }.agent-signal.is-unknown { background:var(--wb-danger); }.agent-signal.is-muted { background:var(--wb-text-muted); }
.agent-title { display:grid; min-width:0; }.agent-title strong { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:12px; }.agent-title small { color:var(--wb-text-muted); font:9px var(--font-mono,monospace); }
.agent-state { margin-left:auto; color:var(--wb-text-secondary); font-size:10px; white-space:nowrap; }
.pool-card__meta { justify-content:space-between; margin:10px 0 8px 15px; color:var(--wb-text-muted); font-size:10px; }
.capabilities { display:flex; flex-wrap:wrap; gap:4px; margin-left:15px; }.capabilities span,.capabilities em { padding:3px 5px; border-radius:4px; background:var(--wb-surface-inset); color:var(--wb-text-secondary); font:9px var(--font-mono,monospace); }.capabilities em { color:var(--wb-text-muted); font-style:normal; }
.active-steps { margin:11px 0 0 15px; padding-top:9px; border-top:1px solid var(--pool-border); }.active-steps__label { display:flex; align-items:center; gap:5px; margin-bottom:5px; color:var(--wb-success); font-size:10px; }.pulse { width:5px; height:5px; border-radius:50%; background:currentColor; animation:pulse 1.5s ease-in-out infinite; }
.active-step { display:flex; justify-content:space-between; width:100%; padding:6px 0; border:0; background:transparent; color:inherit; text-align:left; }.active-step:hover strong { color:var(--wb-accent); }.active-step span:first-child { display:grid; gap:2px; }.active-step strong { font-size:11px; font-weight:500; }.active-step small { color:var(--wb-text-muted); font:9px var(--font-mono,monospace); }.step-arrow { color:var(--wb-text-muted); }
.idle-note { margin:11px 0 0 15px; padding-top:9px; border-top:1px solid var(--pool-border); color:var(--wb-text-muted); font-size:10px; }
.pool-state { display:grid; flex:1; place-content:center; gap:6px; padding:20px; color:var(--wb-text-muted); font-size:11px; text-align:center; }.pool-state strong { color:var(--wb-text); font-size:12px; }.pool-state button { margin:auto; border:0; background:transparent; color:var(--wb-accent); }.pool-state.is-error { color:var(--wb-danger); }
.pool-foot { padding:8px 16px 10px; border-top:1px solid var(--pool-border); color:var(--wb-text-muted); font-size:9px; }
@keyframes pulse { 0%,100% { opacity:.35; transform:scale(.8); } 50% { opacity:1; transform:scale(1.15); } }
</style>
