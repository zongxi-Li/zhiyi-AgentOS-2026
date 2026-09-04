<!-- ACG 低熵通信指标 — 展示平均 Token 节省率、累计节省/交付/可用 Token 数和自愈恢复次数 -->
<template>
  <section class="acg-metrics ui-surface">
    <header class="panel-head">
      <div class="head-left">
        <el-icon class="head-icon"><DataLine /></el-icon>
        <h4>低熵通信指标</h4>
      </div>
    </header>

    <div class="metric-overview">
      <div class="metric-hero">
        <div>
          <span class="metric-value">{{ savingPercent }}</span>
          <span class="metric-label">平均 Token 节省率</span>
        </div>
        <div class="saved-summary">
          <span class="metric-label">累计节省</span>
          <strong>{{ formatNum(metrics.tokensSaved) }}</strong>
          <span class="saved-unit">Token</span>
        </div>
      </div>
      <div class="delivery-summary">
        <span class="metric-label">投递 / 可获取</span>
        <strong>{{ formatNum(metrics.tokensDelivered) }} <i>/</i> {{ formatNum(metrics.tokensAvailable) }}</strong>
      </div>
    </div>

    <div class="signal-grid" aria-label="运行质量信号">
      <div class="signal-card" :class="{ warn: metrics.recoveryCount > 0 }">
        <span class="metric-value">{{ metrics.recoveryCount }}</span>
        <span class="metric-label">自愈恢复次数</span>
      </div>
      <div class="signal-card">
        <span class="metric-value">{{ metrics.interactionCount }}</span>
        <span class="metric-label">运行时交互</span>
      </div>
      <div class="signal-card" :class="{ danger: metrics.contractViolationCount > 0 }">
        <span class="metric-value">{{ metrics.contractViolationCount }}</span>
        <span class="metric-label">契约异常</span>
      </div>
    </div>

    <footer class="metrics-footer">
      <div class="ledger-status" :class="{ invalid: metrics.integrityStatus !== 'valid' }">
        <span class="ledger-dot" aria-hidden="true"></span>
        <span>审计账本</span>
        <strong>{{ metrics.integrityStatus === 'valid' ? '校验通过' : '旧版或校验异常' }}</strong>
      </div>

      <div class="bar-wrap" v-if="metrics.tokensAvailable > 0">
        <div class="bar-heading">
          <span>实际投递 {{ deliveredPercent }}</span>
          <strong>节省 {{ savingPercent }}</strong>
        </div>
        <div class="bar-track">
          <div class="bar-fill" :style="{ width: deliveredPercent }"></div>
        </div>
        <div class="bar-caption">引擎按需投递，减少无效上下文</div>
      </div>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { DataLine } from '@element-plus/icons-vue'
import type { AcgLowEntropyMetrics } from '@/services/api/agentos'

const props = withDefaults(defineProps<{
  metrics?: AcgLowEntropyMetrics
}>(), {
  metrics: () => ({
    averageSavingRatio: 0,
    effectiveSavingRatio: 0,
    tokensAvailable: 0,
    tokensDelivered: 0,
    tokensSaved: 0,
    recoveryCount: 0,
    interactionCount: 0,
    contractViolationCount: 0,
    integrityStatus: 'valid'
  })
})

const savingPercent = computed(() => `${((props.metrics.effectiveSavingRatio ?? props.metrics.averageSavingRatio) * 100).toFixed(1)}%`)

const deliveredPercent = computed(() => {
  const { tokensAvailable, tokensDelivered } = props.metrics
  if (!tokensAvailable) return '0%'
  return `${Math.min(100, (tokensDelivered / tokensAvailable) * 100).toFixed(1)}%`
})

const formatNum = (n: number) => {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n ?? 0)
}
</script>

<style scoped>
.acg-metrics {
  box-sizing: border-box; display: flex; flex-direction: column; min-width: 0;
  padding: 8px 0 6px; overflow: hidden;
}
.panel-head { display: flex; align-items: center; margin-bottom: 9px; }
.head-left { display: flex; align-items: center; gap: 6px; }
.head-icon { font-size: 15px; color: var(--primary-color); }
.panel-head h4 { margin: 0; font-size: 13px; font-weight: 700; color: var(--text-primary); }

.metric-overview {
  display: grid; gap: 8px;
}
.metric-hero {
  min-width: 0; min-height: 82px; display: flex; align-items: center; justify-content: space-between; gap: 16px;
  padding: 12px 14px; border: 1px solid var(--primary-line); border-radius: 10px;
  background: color-mix(in srgb, var(--primary-fade) 58%, var(--bg-card));
}
.metric-hero > div:first-child { display: grid; gap: 3px; }
.saved-summary {
  display: grid; justify-items: end; gap: 1px; padding-left: 14px;
  border-left: 1px solid color-mix(in srgb, var(--primary-color) 18%, var(--border-light));
}
.saved-summary strong { color: var(--success); font-size: 22px; font-weight: 750; line-height: 1.05; }
.saved-unit { color: var(--text-muted); font-size: 10px; }
.delivery-summary {
  display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 9px 12px;
  border: 1px solid var(--border-light); border-radius: 8px; background: color-mix(in srgb, var(--bg-input) 64%, var(--bg-card));
}
.delivery-summary strong { color: var(--text-primary); font-size: 17px; font-weight: 750; line-height: 1; white-space: nowrap; }
.delivery-summary i { color: var(--text-muted); font-style: normal; font-weight: 500; }
.metric-value {
  min-width: 0; color: var(--primary-color); font-size: 28px; font-weight: 780;
  line-height: 1.05; letter-spacing: -.025em; overflow-wrap: anywhere;
}
.metric-label { color: var(--text-secondary); font-size: 10px; line-height: 1.35; }

.signal-grid {
  display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0;
  margin-top: 8px; border: 1px solid var(--border-light); border-radius: 8px; background: var(--bg-panel); overflow: hidden;
}
.signal-card {
  min-width: 0; min-height: 54px; display: flex; flex-direction: column; justify-content: center; gap: 3px; padding: 8px 10px;
  border: 0; border-right: 1px solid var(--border-light); border-radius: 0; background: transparent;
}
.signal-card:last-child { border-right: 0; }
.signal-card .metric-value { color: var(--text-primary); font-size: 17px; }
.signal-card.warn { background: color-mix(in srgb, var(--warning-fade) 50%, transparent); }
.signal-card.warn .metric-value { color: var(--warning); }
.signal-card.danger { background: color-mix(in srgb, var(--danger-fade) 50%, transparent); }
.signal-card.danger .metric-value { color: var(--danger); }

.metrics-footer { display: grid; gap: 8px; margin-top: 8px; padding-top: 9px; border-top: 1px solid var(--border-light); }
.ledger-status { display: flex; align-items: center; gap: 6px; color: var(--text-secondary); font-size: 10px; }
.ledger-status strong { margin-left: auto; color: var(--success); font-weight: 700; }
.ledger-dot {
  width: 7px; height: 7px; flex: 0 0 auto; border-radius: 50%; background: var(--success);
  box-shadow: 0 0 0 3px var(--success-fade);
}
.ledger-status.invalid strong { color: var(--warning); }
.ledger-status.invalid .ledger-dot { background: var(--warning); box-shadow: 0 0 0 3px var(--warning-fade); }
.bar-wrap { display: grid; gap: 5px; }
.bar-heading { display: flex; justify-content: space-between; gap: 10px; color: var(--text-secondary); font-size: 10px; }
.bar-heading strong { color: var(--success); font-weight: 700; }
.bar-track {
  height: 7px; overflow: hidden; border-radius: 999px;
  background: color-mix(in srgb, var(--primary-color) 9%, var(--bg-input));
}
.bar-fill {
  height: 100%; border-radius: inherit;
  background: linear-gradient(90deg, color-mix(in srgb, var(--bg-card) 30%, var(--primary-color)), var(--primary-color));
  transition: width .4s ease;
}
.bar-caption { color: var(--text-muted); font-size: 9px; }

@media (max-width: 360px) {
  .acg-metrics { padding: var(--space-md); }
  .signal-grid { grid-template-columns: 1fr; }
  .signal-card { flex-direction: row; align-items: center; justify-content: space-between; }
}
</style>
