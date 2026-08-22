<template>
  <section class="execution-contract" aria-label="ACG 执行合同">
    <div class="contract-heading">
      <strong>执行合同</strong>
      <span class="projection-state" :class="view.identityProjection?.status || 'pending'">
        {{ projectionLabel }}
      </span>
    </div>
    <div class="contract-facts">
      <div>
        <span>Package</span>
        <code :title="packageIdentity?.packageId || ''">{{ shortId(packageIdentity?.packageId) }}</code>
        <small v-if="packageIdentity">v{{ packageIdentity.packageVersion }}</small>
        <button v-if="packageIdentity?.packageId" type="button" title="复制 Package ID" @click="copy(packageIdentity.packageId)">
          <el-icon><CopyDocument /></el-icon>
        </button>
      </div>
      <div>
        <span>Blueprint</span>
        <code :title="blueprint?.blueprintId || ''">{{ shortId(blueprint?.blueprintId) }}</code>
        <small v-if="blueprint">v{{ blueprint.version }}</small>
        <button v-if="blueprint?.blueprintId" type="button" title="复制 Blueprint ID" @click="copy(blueprint.blueprintId)">
          <el-icon><CopyDocument /></el-icon>
        </button>
      </div>
      <div>
        <span>校验</span>
        <code :title="packageIdentity?.checksum || ''">{{ shortHash(packageIdentity?.checksum) }}</code>
        <small :title="packageIdentity?.blueprintHash || ''">图 {{ shortHash(packageIdentity?.blueprintHash) }}</small>
      </div>
      <div v-if="lineageItems.length" class="lineage">
        <span>Run 血缘</span>
        <button
          v-for="item in lineageItems"
          :key="item.label"
          type="button"
          class="lineage-link"
          :title="item.value"
          @click="emit('open-run', item.value)"
        >{{ item.label }} · {{ shortId(item.value) }}</button>
      </div>
      <div v-if="lineage?.sourcePatchId">
        <span>Graph Patch</span>
        <code :title="lineage.sourcePatchId">{{ shortId(lineage.sourcePatchId) }}</code>
        <button type="button" title="复制 Patch ID" @click="copy(lineage.sourcePatchId)">
          <el-icon><CopyDocument /></el-icon>
        </button>
      </div>
    </div>
    <p v-if="view.identityProjection?.message" class="projection-message">{{ view.identityProjection.message }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { CopyDocument } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { AcgView } from '@/services/api/workflow'

const props = defineProps<{ view: AcgView }>()
const emit = defineEmits<{ 'open-run': [runId: string] }>()

const packageIdentity = computed(() => props.view.operational?.package || null)
const blueprint = computed(() => props.view.executionTree?.blueprint || null)
const lineage = computed(() => props.view.operational?.lineage || null)
const projectionLabel = computed(() => ({
  available: 'Identity 已同步',
  pending: 'Identity 同步中',
  unavailable: 'Identity 不可用'
}[props.view.identityProjection?.status || 'pending']))
const lineageItems = computed(() => [
  { label: '父 Run', value: lineage.value?.parentRunId },
  { label: '替代', value: lineage.value?.supersedesRunId },
  { label: '被替代', value: lineage.value?.supersededByRunId }
].filter((item): item is { label: string; value: string } => Boolean(item.value)))

const shortId = (value?: string | null) => !value ? '未投影' : value.length > 24 ? `${value.slice(0, 12)}...${value.slice(-7)}` : value
const shortHash = (value?: string | null) => !value ? '未投影' : value.length > 16 ? `${value.slice(0, 8)}...${value.slice(-6)}` : value
const copy = async (value: string) => {
  try {
    await navigator.clipboard.writeText(value)
    ElMessage.success('标识已复制')
  } catch {
    ElMessage.warning('浏览器未授权剪贴板')
  }
}
</script>

<style scoped>
.execution-contract { display: grid; gap: 9px; margin-top: 1px; padding: 10px 14px; border-top: 1px solid var(--border-light); border-bottom: 1px solid var(--border-light); background: var(--bg-card); }
.contract-heading, .contract-facts, .contract-facts > div { display: flex; align-items: center; }
.contract-heading { justify-content: space-between; gap: 12px; }
.contract-heading strong { font-size: 12px; }
.projection-state { padding: 3px 7px; border-radius: 5px; background: var(--bg-input); color: var(--text-secondary); font-size: 10px; font-weight: 700; }
.projection-state.available { color: var(--success); }
.projection-state.pending { color: var(--warning); }
.projection-state.unavailable { color: var(--danger); }
.contract-facts { gap: 8px 18px; flex-wrap: wrap; }
.contract-facts > div { min-width: 0; gap: 6px; }
.contract-facts span, .contract-facts small { color: var(--text-secondary); font-size: 10px; }
.contract-facts code { max-width: 190px; overflow: hidden; color: var(--text-primary); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.contract-facts button { display: inline-grid; place-items: center; min-width: 24px; height: 24px; padding: 0; border: 0; border-radius: 5px; background: transparent; color: var(--text-secondary); cursor: pointer; }
.contract-facts button:hover { background: var(--primary-fade); color: var(--primary-color); }
.contract-facts .lineage { flex-wrap: wrap; }
.contract-facts .lineage-link { width: auto; max-width: 210px; padding: 0 6px; color: var(--primary-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.projection-message { margin: 0; color: var(--warning); font-size: 10px; }
@media (max-width: 760px) { .contract-facts { display: grid; grid-template-columns: 1fr; } .contract-facts > div { flex-wrap: wrap; } .contract-facts code { max-width: min(70vw, 300px); } }
</style>
