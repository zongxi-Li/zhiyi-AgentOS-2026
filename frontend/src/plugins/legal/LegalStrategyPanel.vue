<template>
  <section class="legal-strategy">
    <header class="legal-strategy__header">
      <div><strong>法律执行策略</strong><small>只影响当前新 Run 的执行方式</small></div>
      <span class="legal-strategy__count">{{ [draft.evidenceFirst, draft.riskParallel, draft.conservativeReview, draft.useTemplateWorkflow].filter(Boolean).length }}/4 已启用</span>
    </header>
    <div class="legal-strategy__options">
      <el-checkbox v-model="draft.evidenceFirst" :disabled="readonly">Evidence 优先</el-checkbox>
      <el-checkbox v-model="draft.riskParallel" :disabled="readonly">风险并行分析</el-checkbox>
      <el-checkbox v-model="draft.conservativeReview" :disabled="readonly">保守人工审核</el-checkbox>
      <el-checkbox v-model="draft.useTemplateWorkflow" :disabled="readonly">固定合同审查 Workflow</el-checkbox>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { LegalPluginDraft } from './index'

const props = defineProps<{ modelValue: Record<string, unknown>; readonly?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: Record<string, unknown>] }>()
const draft = computed<LegalPluginDraft>({
  get: () => props.modelValue as unknown as LegalPluginDraft,
  set: value => emit('update:modelValue', value as unknown as Record<string, unknown>)
})
</script>

<style scoped>
.legal-strategy { display:grid; gap:12px; padding:14px 16px; border:1px solid var(--border-light); border-radius:var(--radius-card); background:var(--surface-solid); }
.legal-strategy__header { display:flex; align-items:center; justify-content:space-between; gap:12px; padding-bottom:10px; border-bottom:1px solid var(--border-light); }
.legal-strategy__header > div { display:grid; gap:3px; }
.legal-strategy__header strong { color:var(--text-primary); font-size:13px; font-weight:780; }
.legal-strategy__header small { color:var(--text-muted); font-size:10px; }
.legal-strategy__count { padding:5px 8px; border-radius:var(--radius-full); background:var(--primary-fade); color:var(--primary-color); font-size:10px; white-space:nowrap; }
.legal-strategy__options { display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:8px; }
.legal-strategy :deep(.el-checkbox) { display:flex; align-items:center; min-width:0; min-height:40px; margin:0; padding:8px 9px; border:1px solid var(--border-light); border-radius:9px; background:var(--bg-input); color:var(--text-secondary); transition:var(--transition); }
.legal-strategy :deep(.el-checkbox:hover) { border-color:var(--border-hover); }
.legal-strategy :deep(.el-checkbox.is-checked) { border-color:var(--primary-line); background:var(--primary-fade); }
.legal-strategy :deep(.el-checkbox__label) { min-width:0; overflow:hidden; color:inherit; font-size:11px; text-overflow:ellipsis; white-space:nowrap; }
.legal-strategy :deep(.el-checkbox__input.is-checked + .el-checkbox__label) { color:var(--primary-color); }
@media (max-width: 760px) { .legal-strategy__header { align-items:flex-start; } .legal-strategy__options { grid-template-columns:repeat(2, minmax(0, 1fr)); } }
</style>
