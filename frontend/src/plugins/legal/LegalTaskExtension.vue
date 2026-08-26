<template>
  <section class="legal-extension ui-surface ui-surface--pad">
    <header class="legal-extension__header">
      <div>
        <span class="legal-extension__eyebrow">能力配置</span>
        <strong>法律任务扩展</strong>
        <small>仅对当前新 Run 生效 · 用于约束审查范围与交付方式</small>
      </div>
      <el-tag class="legal-extension__tag" effect="plain" type="warning">kinlin.legal</el-tag>
    </header>
    <div class="legal-grid">
      <label class="wide"><span>合同文本</span><el-input v-model="draft.contractText" :disabled="readonly" type="textarea" :rows="5" placeholder="粘贴合同正文；也可以在通用任务材料区上传合同文件" /></label>
      <label><span>合同审查目标</span><el-input v-model="draft.reviewGoal" :disabled="readonly" placeholder="例如：识别风险并给出修改建议" /></label>
      <label><span>合同类型（可选）</span><el-input v-model="draft.contractType" :disabled="readonly" placeholder="采购、服务、软件开发等" /></label>
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
.legal-extension { display:grid; gap:14px; border:1px solid var(--border-light); border-top:2px solid color-mix(in srgb, var(--el-color-warning) 58%, var(--border-light)); background:var(--surface-solid); }
.legal-extension__header { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; margin:0; }
.legal-extension__header > div { display:grid; gap:3px; }
.legal-extension__eyebrow { color:var(--el-color-warning); font-size:10px; font-weight:750; letter-spacing:.04em; text-transform:uppercase; }
.legal-extension__header strong { color:var(--text-primary); font-size:14px; font-weight:780; }
.legal-extension__header small, label span { color:var(--text-secondary); font-size:11px; }
.legal-extension__tag { flex:0 0 auto; border-radius:var(--radius-full); }
.legal-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
label { display:flex; flex-direction:column; gap:7px; min-width:0; }
.wide { grid-column:1 / -1; }
.legal-extension :deep(.el-textarea__inner), .legal-extension :deep(.el-input__wrapper) { border:1px solid var(--border-light); border-radius:var(--radius-control); background:var(--bg-input); box-shadow:none; color:var(--text-primary); }
.legal-extension :deep(.el-textarea__inner) { min-height:132px !important; padding:11px 12px; resize:vertical; line-height:1.55; }
.legal-extension :deep(.el-input__wrapper) { min-height:38px; padding:1px 11px; }
.legal-extension :deep(.el-textarea__inner:hover), .legal-extension :deep(.el-input__wrapper:hover) { border-color:var(--border-hover); }
.legal-extension :deep(.el-textarea__inner:focus), .legal-extension :deep(.el-input__wrapper.is-focus) { border-color:var(--primary-line); box-shadow:0 0 0 3px var(--primary-fade); }
@media (max-width: 760px) { .legal-grid { grid-template-columns:1fr; } .wide { grid-column:auto; } .legal-extension__header { align-items:flex-start; } }
</style>
