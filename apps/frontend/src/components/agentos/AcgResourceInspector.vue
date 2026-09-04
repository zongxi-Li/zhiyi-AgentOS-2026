<template>
  <div class="resource-panel">
    <ResourceSection title="API 能力" :meta="capabilitySource">
      <dl class="capability-grid">
        <div><dt>模型</dt><dd>{{ usage?.capability?.model || 'API 未声明' }}</dd></div>
        <div><dt>版本</dt><dd>{{ usage?.capability?.version || usage?.capability?.revision || '未知' }}</dd></div>
        <div><dt>上下文</dt><dd>{{ tokens(usage?.capability?.contextWindowTokens, 'API 未声明') }}</dd></div>
        <div><dt>最大输出</dt><dd>{{ tokens(usage?.capability?.maxOutputTokens, 'API 未声明') }}</dd></div>
      </dl>
    </ResourceSection>

    <ResourceSection title="Run 用量" :meta="`${usage?.usage?.callCount ?? 0} 次调用`">
      <div class="metric-grid">
        <div><span>输入</span><strong>{{ observedTokens(usage?.usage?.inputTokens) }}</strong></div>
        <div><span>输出</span><strong>{{ observedTokens(usage?.usage?.outputTokens) }}</strong></div>
        <div><span>缓存读取</span><strong>{{ observedTokens(usage?.usage?.cacheReadTokens) }}</strong></div>
        <div><span>推理</span><strong>{{ observedTokens(usage?.usage?.reasoningTokens) }}</strong></div>
        <div><span>总 Token</span><strong>{{ observedTokens(usage?.usage?.totalTokens) }}</strong></div>
        <div><span>总耗时</span><strong>{{ usage?.usage?.callCount ? `${usage.usage.latencyMs.toLocaleString()} ms` : '未观测' }}</strong></div>
      </div>
      <p class="resource-note">推理 Token 已包含在供应商输出明细中，不重复计入总 Token。</p>
    </ResourceSection>

    <ResourceSection title="上下文压力" :meta="pressureLabel">
      <div class="pressure-card" :class="{ unknown: !hasPressure }">
        <div class="pressure-card__top">
          <div class="pressure-reading">
            <span>当前输入</span>
            <strong>{{ tokens(currentInputTokens, '未观测') }}<small v-if="contextWindow"> / {{ tokens(contextWindow) }}</small><small v-else> Token</small></strong>
          </div>
          <span class="pressure-badge">{{ currentPressureLabel }}</span>
        </div>
        <div class="pressure-track"><i :style="pressureStyle"></i></div>
        <div class="pressure-card__meta">
          <span>峰值 {{ percent(usage?.contextPressure?.peak, '未计算') }}<small v-if="peakInputTokens != null"> · {{ tokens(peakInputTokens) }} Token</small></span>
          <span>上限 {{ tokens(contextWindow, '未声明') }}</span>
        </div>
      </div>
      <p class="resource-note">{{ pressureNote }}</p>
    </ResourceSection>

    <ResourceSection title="组合进度" :meta="assemblyLabel">
      <ul class="progress-list">
        <li><span>材料分块</span><b>{{ usage?.composition.materialFragmentCount ?? '—' }}</b></li>
        <li><span>任务</span><b>{{ usage?.composition.completedTaskCount ?? 0 }}/{{ usage?.composition.taskCount ?? 0 }}</b></li>
        <li><span>持久化结果</span><b>{{ usage?.composition.persistedResultFragmentCount ?? 0 }}</b></li>
        <li><span>汇聚 Manifest</span><b>{{ usage?.composition.reducerManifestCount ?? 0 }}</b></li>
        <li><span>章节</span><b>{{ usage?.composition.chapterCount ?? 0 }}</b></li>
      </ul>
    </ResourceSection>

    <ResourceSection title="调用明细" :meta="`${total} 条`">
      <p v-if="loading && !calls.length" class="resource-empty">正在读取调用账本…</p>
      <p v-else-if="loadError && !calls.length" class="resource-empty">{{ loadError }}</p>
      <p v-else-if="!calls.length" class="resource-empty">暂无模型调用记录</p>
      <div v-else class="call-list">
        <article v-for="call in calls" :key="call.callId">
          <header><strong>{{ call.stepId || '规划调用' }}</strong><span>{{ call.finishReason || '完成' }}</span></header>
          <p>{{ call.model || call.provider || '未知模型' }} · {{ call.latencyMs }}ms</p>
          <small>输入 {{ tokens(call.usage.inputTokens) }} · 输出 {{ tokens(call.usage.outputTokens) }} · {{ call.outputPolicy }}</small>
        </article>
      </div>
      <button v-if="nextCursor" class="load-more" type="button" :disabled="loading" @click="loadMore">{{ loading ? '读取中…' : '继续加载' }}</button>
    </ResourceSection>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onBeforeUnmount, onMounted, ref, watch, type PropType } from 'vue'
import { workflowApi, type ModelCallUsage, type RunResourceUsage } from '@/services/api/workflow'

const props = defineProps<{ runId: string; usage?: RunResourceUsage | null }>()
const calls = ref<ModelCallUsage[]>([])
const nextCursor = ref<string | null>(null)
const total = ref(0)
const loading = ref(false)
const loadError = ref('')
let requestGeneration = 0
let activeController: AbortController | null = null

const ResourceSection = defineComponent({
  props: { title: { type: String, required: true }, meta: { type: String as PropType<string>, default: '' } },
  setup(sectionProps, { slots }) {
    return () => h('section', { class: 'resource-section' }, [
      h('header', [h('strong', sectionProps.title), h('span', sectionProps.meta)]),
      slots.default?.()
    ])
  }
})
const tokens = (value?: number | null, empty = '—') => value === null || value === undefined ? empty : value.toLocaleString()
const observedTokens = (value?: number | null) => props.usage?.usage?.callCount ? tokens(value) : '未观测'
const percent = (value?: number | null, empty = '—') => value === null || value === undefined ? empty : `${Math.round(value * 100)}%`
const capabilitySource = computed(() => ({
  provider_reported: 'API 报告', adapter_declared: '适配器声明', runtime_observed: '运行观测', unknown: '未知'
}[props.usage?.capability?.source || 'unknown']))
const contextWindow = computed(() => props.usage?.contextPressure?.contextWindowTokens ?? props.usage?.capability?.contextWindowTokens ?? null)
const currentInputTokens = computed(() => props.usage?.contextPressure?.currentInputTokens ?? null)
const peakInputTokens = computed(() => props.usage?.contextPressure?.peakInputTokens ?? null)
const hasPressure = computed(() => props.usage?.contextPressure?.current != null || props.usage?.contextPressure?.peak != null)
const pressureLabel = computed(() => hasPressure.value ? `${Math.round((props.usage?.contextPressure?.peak || 0) * 100)}% 峰值` : contextWindow.value ? '等待调用' : '上限未声明')
const currentPressureLabel = computed(() => props.usage?.contextPressure?.current == null ? '未计算' : `当前 ${Math.round(props.usage.contextPressure.current * 100)}%`)
const pressureStyle = computed(() => ({ width: `${Math.round((props.usage?.contextPressure?.peak || 0) * 100)}%` }))
const pressureNote = computed(() => {
  if (!contextWindow.value) return currentInputTokens.value == null
    ? '等待模型调用数据；模型未声明上下文上限，暂不计算压力比例。'
    : '已记录调用输入 Token，但模型未声明上下文上限，暂不计算压力比例。'
  return '按每次调用输入 Token ÷ 上下文上限计算，多个活动节点取峰值。'
})
const assemblyLabel = computed(() => props.usage?.composition?.assemblyComplete ? '已装配' : '进行中')

async function load(reset = false) {
  if (!props.runId || loading.value) return
  const generation = ++requestGeneration
  activeController?.abort()
  const controller = new AbortController()
  activeController = controller
  loading.value = true
  loadError.value = ''
  try {
    const result = await workflowApi.listRunResourceCalls(
      props.runId,
      { cursor: reset ? undefined : nextCursor.value || undefined, pageSize: 20 },
      { signal: controller.signal }
    )
    if (generation !== requestGeneration) return
    calls.value = reset ? result.items : [...calls.value, ...result.items]
    nextCursor.value = result.nextCursor || null
    total.value = result.total
  } catch {
    if (generation !== requestGeneration || controller.signal.aborted) return
    // 资源账本是只读辅助投影，短暂不可用不得污染主运行视图或产生未处理 Promise。
    loadError.value = '调用账本暂时不可用'
  } finally {
    if (generation === requestGeneration) {
      loading.value = false
      activeController = null
    }
  }
}
const loadMore = () => load(false)
watch(() => props.runId, () => {
  requestGeneration += 1
  activeController?.abort()
  activeController = null
  loading.value = false
  calls.value = []
  nextCursor.value = null
  loadError.value = ''
  void load(true)
})
// 执行中 usage 由上层周期刷新，调用总数增长超过已载入条目时重拉首页，
// 保证抽屉打开状态下明细随新模型调用实时生长。
watch(() => props.usage?.usage.callCount ?? 0, (callCount) => {
  if (!props.runId || loading.value) return
  if (callCount > calls.value.length) void load(true)
})
onMounted(() => { void load(true) })
onBeforeUnmount(() => {
  requestGeneration += 1
  activeController?.abort()
  activeController = null
})
</script>

<style scoped>
.resource-panel { display: grid; gap: 0; color: var(--text-primary); }
.resource-section { display: grid; gap: 10px; padding: 12px 2px; border-bottom: 1px solid var(--border-light); }
.resource-section > :deep(header) { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.resource-section > :deep(header strong) { font-size: 12px; }
.resource-section > :deep(header span) { color: var(--text-secondary); font-size: 10px; }
.capability-grid, .metric-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; margin: 0; }
.capability-grid > div, .metric-grid > div { min-width: 0; padding: 9px 10px; border: 1px solid var(--border-light); border-radius: var(--radius-card); background: var(--bg-input); }
dt, .metric-grid span { color: var(--text-secondary); font-size: 9px; }
dd, .metric-grid strong { display: block; overflow-wrap: anywhere; margin: 4px 0 0; font-size: 12px; font-weight: 700; }
.resource-note { margin: 0; color: var(--text-secondary); font-size: 9px; line-height: 1.5; text-wrap: pretty; }
.pressure-card { display: grid; gap: 9px; padding: 11px 12px; border: 1px solid var(--primary-line); border-radius: var(--radius-card); background: color-mix(in srgb, var(--primary-fade) 58%, var(--surface-solid)); }
.pressure-card.unknown { border-color: var(--border-light); background: var(--bg-input); }
.pressure-card__top, .pressure-card__meta { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.pressure-reading { display: grid; gap: 3px; min-width: 0; }
.pressure-reading span, .pressure-card__meta { color: var(--text-secondary); font-size: 9px; }
.pressure-card__meta small { color: inherit; font-size: inherit; }
.pressure-reading strong { color: var(--text-primary); font-size: 15px; font-weight: 800; letter-spacing: -.01em; }
.pressure-reading strong small { color: var(--text-secondary); font-size: 10px; font-weight: 600; }
.pressure-badge { flex: 0 0 auto; padding: 5px 8px; border-radius: var(--radius-full); background: var(--primary-fade); color: var(--primary-color); font-size: 9px; font-weight: 700; }
.pressure-card.unknown .pressure-badge { background: var(--surface-solid); color: var(--text-muted); }
.pressure-track { height: 7px; overflow: hidden; border-radius: 999px; background: color-mix(in srgb, var(--surface-solid) 68%, var(--border-light)); }
.pressure-track i { display: block; height: 100%; border-radius: inherit; background: var(--primary-color); transition: width 150ms ease; }
.pressure-card.unknown .pressure-track i { width: 0 !important; }
.progress-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; margin: 0; padding: 0; list-style: none; }
.progress-list li { display: flex; justify-content: space-between; gap: 8px; padding: 8px 9px; border-radius: var(--radius-control); background: var(--bg-input); font-size: 10px; }
.call-list { display: grid; gap: 7px; }
.call-list article { padding: 9px 10px; border: 1px solid var(--border-light); border-radius: var(--radius-card); background: var(--bg-input); }
.call-list header { display: flex; justify-content: space-between; gap: 8px; }
.call-list strong { overflow-wrap: anywhere; font-size: 10px; }
.call-list header span, .call-list p, .call-list small { color: var(--text-secondary); font-size: 9px; }
.call-list p { margin: 5px 0; }
.load-more { width: 100%; min-height: 32px; border: 1px solid var(--border-light); border-radius: var(--radius-control); background: var(--surface-solid); color: var(--primary-color); font: inherit; font-size: 10px; cursor: pointer; }
.load-more:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
.resource-empty { margin: 0; padding: 12px; border: 1px dashed var(--border-light); border-radius: var(--radius-card); color: var(--text-secondary); font-size: 10px; text-align: center; }
@media (prefers-reduced-motion: reduce) { .pressure-track i { transition: none; } }
</style>
