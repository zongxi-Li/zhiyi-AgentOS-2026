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

    <ResourceSection title="Run 用量" :meta="`${usage?.usage.callCount ?? 0} 次调用`">
      <div class="metric-grid">
        <div><span>输入</span><strong>{{ tokens(usage?.usage.inputTokens) }}</strong></div>
        <div><span>输出</span><strong>{{ tokens(usage?.usage.outputTokens) }}</strong></div>
        <div><span>缓存读取</span><strong>{{ tokens(usage?.usage.cacheReadTokens) }}</strong></div>
        <div><span>推理</span><strong>{{ tokens(usage?.usage.reasoningTokens) }}</strong></div>
      </div>
      <p class="resource-note">推理 Token 已包含在供应商输出明细中，不重复计入总 Token。</p>
    </ResourceSection>

    <ResourceSection title="上下文压力" :meta="pressureLabel">
      <div class="pressure-track" :class="{ unknown: usage?.contextPressure.peak == null }"><i :style="pressureStyle"></i></div>
      <p class="resource-note">多个活动节点展示单次调用峰值，不做错误累加。</p>
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
import { computed, defineComponent, h, onMounted, ref, watch, type PropType } from 'vue'
import { workflowApi, type ModelCallUsage, type RunResourceUsage } from '@/services/api/workflow'

const props = defineProps<{ runId: string; usage?: RunResourceUsage | null }>()
const calls = ref<ModelCallUsage[]>([])
const nextCursor = ref<string | null>(null)
const total = ref(0)
const loading = ref(false)
const loadError = ref('')

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
const capabilitySource = computed(() => ({
  provider_reported: 'API 报告', adapter_declared: '适配器声明', runtime_observed: '运行观测', unknown: '未知'
}[props.usage?.capability?.source || 'unknown']))
const pressureLabel = computed(() => props.usage?.contextPressure.peak == null ? 'API 未声明' : `${Math.round(props.usage.contextPressure.peak * 100)}% 峰值`)
const pressureStyle = computed(() => ({ width: `${Math.round((props.usage?.contextPressure.peak || 0) * 100)}%` }))
const assemblyLabel = computed(() => props.usage?.composition.assemblyComplete ? '已装配' : '进行中')

async function load(reset = false) {
  if (!props.runId || loading.value) return
  loading.value = true
  loadError.value = ''
  try {
    const result = await workflowApi.listRunResourceCalls(props.runId, { cursor: reset ? undefined : nextCursor.value || undefined, pageSize: 20 })
    calls.value = reset ? result.items : [...calls.value, ...result.items]
    nextCursor.value = result.nextCursor || null
    total.value = result.total
  } catch {
    // 资源账本是只读辅助投影，短暂不可用不得污染主运行视图或产生未处理 Promise。
    loadError.value = '调用账本暂时不可用'
  } finally {
    loading.value = false
  }
}
const loadMore = () => load(false)
watch(() => props.runId, () => { calls.value = []; nextCursor.value = null; loadError.value = ''; void load(true) })
onMounted(() => { void load(true) })
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
.pressure-track { height: 6px; overflow: hidden; border-radius: 999px; background: var(--bg-input); }
.pressure-track i { display: block; height: 100%; border-radius: inherit; background: var(--primary-color); transition: width 150ms ease; }
.pressure-track.unknown i { width: 0 !important; }
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
