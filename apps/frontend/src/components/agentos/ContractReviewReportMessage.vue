<template>
  <article class="contract-review-report-message">
    <header class="report-header">
      <div class="report-header__identity">
        <span class="report-header__icon"><el-icon><Document /></el-icon></span>
        <div>
          <p class="report-header__eyebrow">审查结论</p>
          <h2>合同审查报告</h2>
        </div>
      </div>
      <span class="report-status">已生成</span>
    </header>

    <nav class="report-tabs" aria-label="合同审查结果视图">
      <button class="report-tab" :class="{ active: activeView === 'report' }" type="button" @click="activeView = 'report'">
        <el-icon><Document /></el-icon>
        审查报告
      </button>
      <button class="report-tab report-tab--risk" :class="{ active: activeView === 'risks' }" type="button" @click="activeView = 'risks'">
        <el-icon><Warning /></el-icon>
        风险点
        <span v-if="riskCounts.total">{{ riskCounts.total }}</span>
      </button>
      <button class="report-tab" :class="{ active: activeView === 'details' }" type="button" @click="activeView = 'details'">
        分步结论
      </button>
    </nav>

    <template v-if="activeView === 'report'">
      <div v-if="riskCounts.total" class="risk-summary" aria-label="风险摘要">
        <span class="risk-summary__label">识别到 {{ riskCounts.total }} 项风险</span>
        <span v-if="riskCounts.high" class="risk-count risk-count--high">高 {{ riskCounts.high }}</span>
        <span v-if="riskCounts.medium" class="risk-count risk-count--medium">中 {{ riskCounts.medium }}</span>
        <span v-if="riskCounts.low" class="risk-count risk-count--low">低 {{ riskCounts.low }}</span>
      </div>

      <div class="report-content markdown-body" v-html="renderedReport" />

    </template>

    <ContractRiskPanel v-else-if="activeView === 'risks'" class="report-risks" :risks="risks" />

    <section v-else class="step-deliverables">
      <div class="step-deliverables__heading">
        <el-icon><Document /></el-icon>
        <h3>审查交付物</h3>
      </div>
      <AcgDeliverables :deliverables="deliverables" :show-header="false" />
    </section>
  </article>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Document, Warning } from '@element-plus/icons-vue'
import type { AcgDeliverable } from '@/services/api/workflow'
import type { ContractRiskItem } from '@/utils/agentos/contractReviewArtifactExtractor'
import { renderMarkdown } from '@/utils/markdown'
import ContractRiskPanel from './ContractRiskPanel.vue'
import AcgDeliverables from './AcgDeliverables.vue'

const props = withDefaults(defineProps<{
  report: string
  deliverables?: AcgDeliverable[]
  risks?: ContractRiskItem[]
}>(), {
  deliverables: () => [],
  risks: () => []
})

const activeView = ref<'report' | 'risks' | 'details'>('report')
const renderedReport = computed(() => renderMarkdown(props.report || ''))

const riskCounts = computed(() => {
  const counts = { total: 0, high: 0, medium: 0, low: 0 }
  for (const deliverable of props.deliverables) {
    const risks = Array.isArray(deliverable.output?.risks) ? deliverable.output.risks : []
    for (const risk of risks) {
      counts.total += 1
      const level = String(risk?.level || risk?.risk_level || risk?.severity || '').toLowerCase()
      if (level.includes('high') || level.includes('高')) counts.high += 1
      else if (level.includes('low') || level.includes('低')) counts.low += 1
      else counts.medium += 1
    }
  }
  return counts
})

</script>

<style scoped>
.contract-review-report-message {
  width: min(100%, 960px);
  margin: 18px auto 36px;
  padding: 24px 28px 18px;
  border: 1px solid var(--border-light);
  border-radius: 6px;
  background: transparent;
  color: var(--text-primary);
}

.report-header,
.report-header__identity,
.risk-summary,
.report-process__toggle,
.report-step {
  display: flex;
  align-items: center;
}

.report-header {
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-light);
}

.report-header__identity { gap: 10px; min-width: 0; }
.report-header__icon {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 1px solid color-mix(in srgb, var(--primary-color) 28%, var(--border-light));
  border-radius: 6px;
  color: var(--primary-color);
  background: color-mix(in srgb, var(--primary-color) 7%, var(--bg-panel));
}
.report-header__eyebrow { margin: 0 0 2px; color: var(--text-secondary); font-size: 11px; line-height: 1.2; }
.report-header h2 { margin: 0; color: var(--text-primary); font-size: 18px; line-height: 1.25; font-weight: 750; }
.report-status {
  flex: 0 0 auto;
  padding: 3px 7px;
  border-radius: 4px;
  background: color-mix(in srgb, var(--success) 12%, transparent);
  color: var(--success);
  font-size: 11px;
  font-weight: 700;
}

.report-tabs { display: flex; gap: 4px; padding-top: 12px; }
.report-tab {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 30px;
  padding: 4px 9px;
  border: 1px solid transparent;
  border-radius: 5px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  font-weight: 650;
}
.report-tab:hover { color: var(--primary-color); background: color-mix(in srgb, var(--primary-color) 5%, transparent); }
.report-tab.active { border-color: color-mix(in srgb, var(--primary-color) 24%, var(--border-light)); background: color-mix(in srgb, var(--primary-color) 8%, transparent); color: var(--primary-color); }
.report-tab--risk.active { border-color: color-mix(in srgb, var(--warning) 26%, var(--border-light)); background: color-mix(in srgb, var(--warning) 9%, transparent); color: var(--warning); }
.report-tab span { min-width: 16px; padding: 1px 4px; border-radius: 4px; background: color-mix(in srgb, currentColor 12%, transparent); font-size: 10px; text-align: center; }

.risk-summary {
  gap: 7px;
  flex-wrap: wrap;
  padding: 13px 0 4px;
  color: var(--text-secondary);
  font-size: 12px;
}
.risk-summary__label { margin-right: 3px; color: var(--text-primary); font-weight: 650; }
.risk-count { padding: 2px 6px; border-radius: 4px; font-weight: 700; }
.risk-count--high { background: color-mix(in srgb, var(--danger) 10%, transparent); color: var(--danger); }
.risk-count--medium { background: color-mix(in srgb, var(--warning) 12%, transparent); color: var(--warning); }
.risk-count--low { background: color-mix(in srgb, var(--success) 10%, transparent); color: var(--success); }

.report-content { padding-top: 12px; font-size: 14px; line-height: 1.75; text-wrap: pretty; }
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) { color: var(--text-primary); line-height: 1.4; }
.markdown-body :deep(h1) { margin: 0 0 18px; font-size: 21px; }
.markdown-body :deep(h2) { margin: 24px 0 10px; font-size: 16px; }
.markdown-body :deep(h3) { margin: 18px 0 8px; font-size: 14px; }
.markdown-body :deep(p) { margin: 8px 0; }
.markdown-body :deep(ul),
.markdown-body :deep(ol) { margin: 8px 0 14px; padding-left: 21px; }
.markdown-body :deep(li) { margin: 5px 0; }
.markdown-body :deep(strong) { color: var(--text-primary); font-weight: 750; }
.markdown-body :deep(.markdown-table-wrap) { margin: 14px 0 18px; overflow-x: auto; border: 1px solid var(--border-light); border-radius: 6px; }
.markdown-body :deep(table) { width: 100%; min-width: 560px; border-collapse: collapse; font-size: 12px; line-height: 1.55; }
.markdown-body :deep(th),
.markdown-body :deep(td) { padding: 9px 11px; border-right: 1px solid var(--border-light); border-bottom: 1px solid var(--border-light); text-align: left; vertical-align: top; overflow-wrap: anywhere; }
.markdown-body :deep(th) { background: var(--bg-input); color: var(--text-primary); font-weight: 700; white-space: nowrap; }
.markdown-body :deep(th:last-child),
.markdown-body :deep(td:last-child) { border-right: 0; }
.markdown-body :deep(tbody tr:last-child td) { border-bottom: 0; }

.report-risks { margin-top: 14px; background: transparent; }
.step-deliverables { margin-top: 14px; }
.step-deliverables__heading { display: flex; align-items: center; gap: 7px; padding: 0 0 10px; color: var(--primary-color); }
.step-deliverables__heading h3 { margin: 0; color: var(--text-primary); font-size: 14px; }
.step-deliverables :deep(.acg-deliverables) { border: 0; border-radius: 0; background: transparent; box-shadow: none; }
.step-deliverables :deep(.detail-body) { max-height: none; }

@media (max-width: 700px) {
  .contract-review-report-message { margin: 12px 0 22px; padding: 18px 16px 14px; }
  .report-header h2 { font-size: 16px; }
  .report-content { font-size: 13px; }
}
</style>
