<template>
  <div class="resource-detail">
    <header class="resource-detail__hero">
      <span class="resource-detail__icon" aria-hidden="true"><el-icon><component :is="resourceTypeIcon(item.profile.resourceType)" /></el-icon></span>
      <div class="resource-detail__identity">
        <div class="resource-detail__title">
          <strong>{{ item.profile.resourceId }}</strong>
          <ResourceTypeBadge :type="item.profile.resourceType" />
        </div>
        <span>{{ tierLabel(item.profile.deploymentTier) }} · v{{ item.profile.version }}</span>
      </div>
      <span class="resource-detail__health" :class="`is-${item.snapshot.healthStatus}`">{{ healthLabel(item.snapshot.healthStatus) }}</span>
    </header>

    <section class="resource-detail__section">
      <h3>运行状态</h3>
      <dl class="resource-detail__kv">
        <div><dt>健康状态</dt><dd :class="`is-${item.snapshot.healthStatus}`">{{ healthLabel(item.snapshot.healthStatus) }}</dd></div>
        <div><dt>可用槽位</dt><dd>{{ item.snapshot.availableSlots }} / {{ item.profile.capacity }}</dd></div>
        <div><dt>利用率</dt><dd>{{ formatPercent(item.snapshot.utilization) }}</dd></div>
        <div><dt>延迟</dt><dd>{{ formatMetric(item.snapshot.latencyMs, 'ms') }}</dd></div>
        <div><dt>可靠性</dt><dd>{{ formatPercent(item.snapshot.reliability) }}</dd></div>
        <div><dt>启用</dt><dd>{{ item.profile.enabled ? '是' : '否' }}</dd></div>
      </dl>
    </section>

    <section v-if="item.profile.computeCapacity" class="resource-detail__section">
      <h3>算力画像</h3>
      <dl class="resource-detail__kv">
        <div><dt>CPU</dt><dd>{{ item.profile.computeCapacity.cpuCores }} 核</dd></div>
        <div><dt>内存</dt><dd>{{ Math.round(item.profile.computeCapacity.memoryMb / 1024) }} GB</dd></div>
        <div><dt>GPU</dt><dd>{{ item.profile.computeCapacity.gpuType || 'GPU' }} {{ Math.round(item.profile.computeCapacity.gpuMemoryMb / 1024) }} GB</dd></div>
        <div><dt>带宽</dt><dd>{{ item.profile.computeCapacity.bandwidthMbps }} Mbps</dd></div>
      </dl>
    </section>

    <section class="resource-detail__section">
      <h3>部署与端点</h3>
      <dl class="resource-detail__kv">
        <div><dt>部署层级</dt><dd>{{ tierLabel(item.profile.deploymentTier) }}</dd></div>
        <div><dt>隐私级别</dt><dd>{{ item.profile.privacyLevel || '未标注' }}</dd></div>
        <div><dt>数据域</dt><dd>{{ item.profile.dataZone || '未标注' }}</dd></div>
        <div><dt>位置</dt><dd>{{ item.profile.location || '未标注' }}</dd></div>
        <div><dt>归属</dt><dd>{{ item.profile.ownerScope || '未标注' }}</dd></div>
        <div v-if="item.profile.executionEndpoint"><dt>端点</dt><dd class="resource-detail__code">{{ item.profile.executionEndpoint.protocol }}://{{ item.profile.executionEndpoint.address }}</dd></div>
      </dl>
    </section>

    <section v-if="item.profile.capabilities.length" class="resource-detail__section">
      <h3>能力</h3>
      <div class="resource-detail__chips">
        <span v-for="capability in item.profile.capabilities" :key="capability">{{ capability }}</span>
      </div>
    </section>

    <section v-if="item.profile.domains.length" class="resource-detail__section">
      <h3>领域</h3>
      <div class="resource-detail__chips">
        <span v-for="domain in item.profile.domains" :key="domain">{{ domain }}</span>
      </div>
    </section>

    <section v-if="item.profile.modelIds?.length" class="resource-detail__section">
      <h3>挂载模型</h3>
      <div class="resource-detail__chips">
        <span v-for="modelId in item.profile.modelIds" :key="modelId">{{ modelId }}</span>
      </div>
    </section>

    <section v-if="Object.keys(item.profile.labels).length" class="resource-detail__section">
      <h3>标签</h3>
      <dl class="resource-detail__kv">
        <div v-for="(value, key) in item.profile.labels" :key="key"><dt>{{ key }}</dt><dd>{{ value }}</dd></div>
      </dl>
    </section>

    <section v-if="Object.keys(item.profile.costMetadata).length" class="resource-detail__section">
      <h3>成本元数据</h3>
      <dl class="resource-detail__kv">
        <div v-for="(value, key) in item.profile.costMetadata" :key="key"><dt>{{ key }}</dt><dd>{{ value }}</dd></div>
      </dl>
    </section>

    <section class="resource-detail__section">
      <h3>观测信息</h3>
      <dl class="resource-detail__kv">
        <div><dt>观测时间</dt><dd>{{ formatDate(item.snapshot.observedAt) }}</dd></div>
        <div><dt>快照版本</dt><dd>v{{ item.snapshotVersion }}</dd></div>
      </dl>
    </section>
  </div>
</template>

<script setup lang="ts">
import type { RuntimeResourceItem } from '@/services/api/agentos'
import ResourceTypeBadge from './ResourceTypeBadge.vue'
import { formatDate, formatMetric, formatPercent, healthLabel, tierLabel } from '@/utils/resourceFormat'
import { resourceTypeIcon } from '@/utils/resourceTypeIcons'

defineProps<{ item: RuntimeResourceItem }>()
</script>

<style scoped>
.resource-detail { display: grid; gap: 18px; padding: 4px 2px 24px; color: var(--text-primary); }
.resource-detail__hero { display: flex; align-items: center; gap: 12px; padding: 12px 14px; border: 1px solid var(--border-light); border-radius: var(--radius-card, 9px); background: var(--bg-card); }
.resource-detail__icon { display: inline-grid; place-items: center; flex: 0 0 auto; width: 40px; height: 40px; border: 1px solid var(--primary-line); border-radius: var(--radius-control, 6px); color: var(--primary-color); background: var(--primary-fade); }
.resource-detail__identity { display: grid; gap: 3px; min-width: 0; flex: 1; }
.resource-detail__title { display: flex; align-items: center; gap: 8px; min-width: 0; }
.resource-detail__title strong { min-width: 0; }
.resource-detail__identity strong { overflow: hidden; color: var(--text-primary); font: 600 13px var(--font-mono, monospace); text-overflow: ellipsis; white-space: nowrap; }
.resource-detail__identity span { color: var(--text-muted); font: 10px var(--font-mono, monospace); }
.resource-detail__health { flex: 0 0 auto; padding: 3px 9px; border-radius: 999px; color: var(--text-secondary); background: var(--bg-input); font-size: 11px; }
.resource-detail__health.is-online { color: var(--success); }
.resource-detail__health.is-degraded { color: var(--warning); }
.resource-detail__health.is-offline { color: var(--danger); }
.resource-detail__section { display: grid; gap: 8px; }
.resource-detail__section h3 { margin: 0; color: var(--text-secondary); font-size: 11px; font-weight: 650; letter-spacing: .02em; }
.resource-detail__kv { display: grid; margin: 0; border: 1px solid var(--border-light); border-radius: var(--radius-card, 9px); overflow: hidden; }
.resource-detail__kv > div { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; padding: 9px 14px; border-bottom: 1px solid var(--border-light); background: var(--bg-card); }
.resource-detail__kv > div:last-child { border-bottom: 0; }
.resource-detail__kv dt { color: var(--text-muted); font-size: 11px; }
.resource-detail__kv dd { margin: 0; color: var(--text-secondary); font: 11px var(--font-mono, monospace); text-align: right; word-break: break-all; }
.resource-detail__kv dd.is-online { color: var(--success); }
.resource-detail__kv dd.is-degraded { color: var(--warning); }
.resource-detail__kv dd.is-offline { color: var(--danger); }
.resource-detail__code { font-size: 10px !important; }
.resource-detail__chips { display: flex; gap: 6px; flex-wrap: wrap; }
.resource-detail__chips span { padding: 4px 9px; border: 1px solid var(--border-light); border-radius: 4px; color: var(--text-secondary); background: var(--bg-input); font: 10px var(--font-mono, monospace); }
</style>

