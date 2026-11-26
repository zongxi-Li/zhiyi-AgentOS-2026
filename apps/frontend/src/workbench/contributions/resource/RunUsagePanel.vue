<template>
  <InspectorSection title="任务用量" :badge="loading ? '更新中' : usage ? '当前运行' : '未观测'">
    <div class="usage-panel" aria-label="当前任务资源统计" :aria-busy="loading || callsLoading">
      <p v-if="error" class="usage-note" role="status">{{ error }}</p>
      <div class="usage-summary">
        <div class="usage-total"><span>累计已观测 Token</span><strong>{{ number(summary?.usageReportedCalls === 0 && summary?.callCount ? null : summary?.totalTokens) }}</strong><small>当前运行的模型消耗<span v-if="summary?.usageMissingCalls"> · {{ summary.usageMissingCalls }} 次调用未返回用量</span></small></div>
        <div class="usage-current"><span>最近一次上下文输入</span><strong>{{ number(context?.inputTokens) }}</strong><small>{{ context?.measurement === 'provider' ? '供应商实测' : context?.measurement === 'estimate' ? '估算，不用于计费' : '未观测' }}<template v-if="context?.contextWindowTokens"> · 窗口 {{ number(context.contextWindowTokens) }}</template></small></div>
        <div><span>模型调用记录</span><strong>{{ number(summary?.callCount) }}</strong><small>{{ number(summary?.retryCount) }} 次重试</small></div>
        <div>
          <span>Run 缓存命中率</span><strong>{{ formatRatio(summary?.cacheHitRatio) }}</strong>
          <small v-if="summary?.cacheUsageReportedCalls != null">已观测 {{ summary.cacheUsageReportedCalls }}/{{ summary.callCount }} 次调用</small>
          <small v-else>缓存读取 / 输入 Token</small>
        </div>
      </div>

      <dl v-if="usage?.cacheScopes?.length" class="token-legend" aria-label="各阶段缓存命中率">
        <div v-for="item in usage.cacheScopes" :key="item.scope">
          <dt>{{ scopeLabels[item.scope] ?? item.scope }}</dt>
          <dd>{{ formatRatio(item.cacheHitRatio) }} · 已观测 {{ item.cacheUsageReportedCalls }}/{{ item.callCount }} 次调用</dd>
        </div>
      </dl>

      <div class="usage-chart">
        <header><strong>Token 构成</strong><span>输入 + 输出</span></header>
        <div class="token-track" role="img" :aria-label="segments.map(s => `${s.label} ${number(s.value)}`).join('，')">
          <i v-for="segment in segments" :key="segment.label" :class="segment.tone" :style="{ width: `${segment.width}%` }" :title="`${segment.label}：${number(segment.value)} Token`"></i>
        </div>
        <dl class="token-legend">
          <div v-for="segment in segments" :key="segment.label"><dt><i :class="segment.tone"></i>{{ segment.label }}</dt><dd>{{ number(segment.value) }}</dd></div>
        </dl>
      </div>

      <div class="usage-chart">
        <header><strong>模型使用情况</strong><span>{{ models.length }} 个模型</span></header>
        <p v-if="callsError" class="usage-note" role="status">{{ callsError }}</p>
        <p v-else-if="!models.length" class="usage-note">{{ callsLoading ? '正在读取模型调用记录…' : '暂无模型调用记录' }}</p>
        <article v-for="model in models" :key="model.key" class="model-usage">
          <header><strong>{{ model.model }}</strong><span>{{ model.calls }} 次调用</span></header>
          <div class="model-usage__meta"><span>{{ model.provider }}</span><b>{{ number(model.tokens) }} Token <small>· {{ model.share.toFixed(1) }}%</small></b></div>
          <div class="model-track"><i :style="{ width: `${model.share}%` }"></i></div>
        </article>
      </div>
    </div>
  </InspectorSection>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import InspectorSection from '@/components/workbench/InspectorSection.vue'
import { workflowApi, type ModelCallUsage, type RunResourceUsage } from '@/services/api/workflow'

const props = defineProps<{ runId: string | null; runStatus?: string | null }>()
const usage = ref<RunResourceUsage | null>(null)
const calls = ref<ModelCallUsage[]>([])
const loading = ref(false)
const callsLoading = ref(false)
const error = ref('')
const callsError = ref('')
let generation = 0
let controller: AbortController | null = null
let timer: ReturnType<typeof setTimeout> | null = null
const summary = computed(() => usage.value?.usage)
const context = computed(() => usage.value?.contextPressure.latestRequest)
const number = (value?: number | null) => value == null ? '—' : value.toLocaleString('zh-CN')
const scopeLabels: Record<string, string> = { planning: '规划器', node: '执行 Agent', copilot: 'Copilot' }
const formatRatio = (ratio?: number | null) =>
  ratio == null || !Number.isFinite(ratio) || ratio < 0 || ratio > 1 ? '未观测' : `${(ratio * 100).toFixed(1)}%`
const segments = computed(() => {
  const input = summary.value?.inputTokens
  const measured = summary.value?.cacheMeasuredInputTokens ?? input
  const cached = measured == null ? undefined : Math.min(measured,
    summary.value?.cacheMeasuredReadTokens ?? summary.value?.cacheReadTokens ?? 0)
  const unknown = input == null ? 0 : Math.max(0, input - (measured ?? 0))
  const output = summary.value?.outputTokens
  const total = (input ?? 0) + (output ?? 0)
  return [
    { label: '输入 · 命中缓存', value: cached, tone: 'is-cached' },
    { label: '输入 · 未命中', value: measured == null ? undefined : measured - (cached ?? 0), tone: 'is-input' },
    ...(unknown ? [{ label: '输入 · 缓存状态未知', value: unknown, tone: 'is-unknown' }] : []),
    { label: '输出', value: output, tone: 'is-output' }
  ].map(segment => ({ ...segment, width: total ? (segment.value ?? 0) / total * 100 : 0 }))
})
const models = computed(() => {
  const grouped = new Map<string, { key: string; model: string; provider: string; calls: number; tokens: number }>()
  for (const call of calls.value) {
    const model = call.model || '未记录模型'
    const provider = call.provider || '未记录供应商'
    const key = JSON.stringify([provider, model])
    const item = grouped.get(key) || { key, model, provider, calls: 0, tokens: 0 }
    item.calls++
    item.tokens += call.usage.totalTokens
    grouped.set(key, item)
  }
  const total = [...grouped.values()].reduce((sum, item) => sum + item.tokens, 0)
  return [...grouped.values()].sort((a, b) => b.tokens - a.tokens).map(item => ({ ...item, share: total ? item.tokens / total * 100 : 0 }))
})

function stop() {
  generation++
  controller?.abort()
  if (timer) clearTimeout(timer)
  timer = null
}
async function refresh() {
  const runId = props.runId
  if (!runId) return
  const current = ++generation
  controller = new AbortController()
  const signal = controller.signal
  loading.value = true
  callsLoading.value = true
  const callsRequest = async () => {
    const items = new Map<string, ModelCallUsage>()
    const cursors = new Set<string>()
    let cursor: string | undefined
    do {
      const page = await workflowApi.listRunResourceCalls(runId, { cursor, pageSize: 100 }, { signal })
      for (const item of page.items) items.set(item.callId, item)
      cursor = page.nextCursor || undefined
      if (cursor && cursors.has(cursor)) throw new Error('Repeated cursor')
      if (cursor) cursors.add(cursor)
    } while (cursor && !signal.aborted)
    return [...items.values()]
  }
  // Summary and ledger have independent latency. Publish each as soon as it
  // arrives; a long paginated ledger must not hold token/cache totals hostage.
  await Promise.allSettled([
    workflowApi.getRunResourceUsage(runId, { signal }).then(result => {
      if (current !== generation) return
      usage.value = result
      error.value = ''
    }, () => {
      if (current === generation) error.value = usage.value ? '用量更新失败，显示上次统计。' : '暂时无法读取任务用量。'
    }).finally(() => { if (current === generation) loading.value = false }),
    callsRequest().then(result => {
      if (current !== generation) return
      calls.value = result
      callsError.value = ''
    }, () => {
      if (current === generation) callsError.value = calls.value.length ? '模型明细更新失败，显示上次统计。' : '暂时无法读取模型调用明细。'
    }).finally(() => { if (current === generation) callsLoading.value = false })
  ])
  if (current !== generation) return
  if (!['completed', 'succeeded', 'superseded', 'failed', 'cancelled', 'canceled', 'interrupted'].includes(props.runStatus || '')) {
    timer = setTimeout(() => void refresh(), 15000)
  }
}
watch(() => props.runId, () => {
  stop()
  usage.value = null
  calls.value = []
  error.value = ''
  callsError.value = ''
  loading.value = false
  callsLoading.value = false
  void refresh()
}, { immediate: true })
watch(() => props.runStatus, () => { stop(); void refresh() })
onBeforeUnmount(stop)
</script>

<style scoped>
.usage-panel { container-type: inline-size; display: grid; gap: 16px; padding-top: 4px; color: var(--wb-text); }
.usage-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.usage-summary > div { display: grid; gap: 7px; min-width: 0; padding: 12px; border-radius: var(--radius-card, 8px); background: var(--wb-surface-2, var(--bg-input)); }
.usage-summary .usage-total { grid-column: 1 / -1; }
.usage-summary span, .usage-summary small { color: var(--wb-text-muted); font-size: 10px; }
.usage-summary strong { font: 20px var(--font-mono, monospace); font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.usage-total strong { font-size: 30px; letter-spacing: -.04em; }
.usage-chart { display: grid; gap: 12px; }
.usage-chart header { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.usage-chart header strong { font-size: 11px; overflow-wrap: anywhere; }
.usage-chart header span { flex-shrink: 0; color: var(--wb-text-muted); font-size: 10px; }
.token-track, .model-track { display: flex; height: 12px; overflow: hidden; border-radius: 4px; background: var(--wb-border-soft); }
.token-track i, .model-track i { display: block; height: 100%; }
.is-cached { background: color-mix(in srgb, var(--primary-color) 35%, var(--wb-text)); }
.is-input { background: color-mix(in srgb, var(--primary-color) 65%, var(--wb-text)); }
.is-unknown { background: var(--wb-text-secondary); }
.is-output, .model-track i { background: var(--primary-color); }
.token-legend { display: grid; gap: 8px; margin: 0; font-size: 10px; }
.token-legend > div { display: flex; justify-content: space-between; gap: 10px; }
.token-legend dt { display: flex; align-items: center; gap: 6px; color: var(--wb-text-secondary); }
.token-legend dt i { width: 7px; height: 7px; border-radius: 2px; }
.token-legend dd { margin: 0; font-family: var(--font-mono, monospace); }
.usage-note { margin: 0; color: var(--wb-text-muted); font-size: 10px; line-height: 1.6; text-wrap: pretty; }
.model-usage { display: grid; gap: 8px; padding: 12px; border-radius: var(--radius-card, 8px); background: var(--wb-surface-2, var(--bg-input)); }
.model-usage__meta { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px; font-size: 10px; }
.model-usage__meta span, .model-usage__meta small { color: var(--wb-text-muted); overflow-wrap: anywhere; }
.model-usage__meta b { font-weight: 500; font-variant-numeric: tabular-nums; }
.model-track { height: 4px; }
@container (max-width: 220px) { .usage-summary { grid-template-columns: 1fr; } }
</style>
