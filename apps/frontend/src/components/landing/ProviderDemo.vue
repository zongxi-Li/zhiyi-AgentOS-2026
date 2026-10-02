<template>
  <div
    class="provider-demo"
    :class="{ 'is-dark': dark }"
    data-testid="provider-run-demo"
    role="group"
    aria-label="模型治理演示：健康刷新、Failover 与 Key Rotation"
  >
    <header class="provider-demo__bar">
      <span class="provider-demo__title">MODEL STATUS · 模型健康</span>
      <span class="provider-demo__status" :class="`is-${phase.id}`" aria-live="polite">
        <i class="provider-demo__status-dot" aria-hidden="true"></i>{{ phase.label }}
      </span>
    </header>

    <div class="provider-demo__tiles">
      <article
        v-for="row in rows"
        :key="row.name"
        class="provider-demo__tile"
        :class="`is-${statusOf(row)}`"
      >
        <span class="provider-demo__tile-head">
          <i class="provider-demo__tile-glyph" aria-hidden="true">{{ row.glyph }}</i>
          <span class="provider-demo__tile-name">{{ row.name }}<code>{{ row.pack }}</code></span>
        </span>
        <span class="provider-demo__tile-desc">{{ row.desc }}</span>
        <span class="provider-demo__tile-state">
          <i class="provider-demo__state-dot" aria-hidden="true"></i>{{ stateLabel(statusOf(row)) }}
        </span>
      </article>

      <div
        class="provider-demo__link"
        :class="{ 'is-hot': playing && tick >= 4 && tick < 10 }"
        aria-hidden="true"
      >
        <svg viewBox="0 0 46 12">
          <line x1="1" y1="6" x2="38" y2="6"></line>
          <path d="M38,1.5 L45,6 L38,10.5 Z"></path>
        </svg>
        <span>Failover</span>
      </div>
    </div>

    <footer class="provider-demo__foot">
      <Transition name="provider-ticker" mode="out-in">
        <span v-if="currentEvent" :key="currentEvent.label" class="provider-demo__ticker">
          <i aria-hidden="true"></i>{{ currentEvent.label }}
        </span>
      </Transition>
      <span class="provider-demo__dots" aria-hidden="true">
        <i v-for="t in LOOP_TICKS" :key="t" :class="{ 'is-on': !playing || tick >= t - 1 }"></i>
      </span>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'

/* 模型健康的演示时间线（状态页/Uptime 式瓷砖）。11 拍循环：健康刷新 →
   通用主模型心跳超时熔断 → Failover 切至备模型 → AgentProfile 重绑定 →
   Key rotation 完成。机制名与状态均来自真实治理概念（AgentProfile binding /
   健康刷新 / failover / key rotation / 版本协商），行项是主备绑定关系而非
   具体供应商名，不虚构数值指标。 */
const LOOP_TICKS = 11

const props = withDefaults(defineProps<{ active?: boolean; dark?: boolean }>(), { active: false, dark: false })

type RowStatus = 'queued' | 'running' | 'done' | 'fault'
type ProviderRow = { glyph: string; name: string; pack: string; desc: string; faultFrom?: number; takeoverFrom?: number; recoverAt?: number }
const rows: ProviderRow[] = [
  { glyph: '写', name: '写作 · 主模型', pack: 'Primary', desc: 'AgentProfile 绑定 · 健康刷新正常' },
  { glyph: '通', name: '通用 · 主模型', pack: 'Primary', desc: '心跳超时 · 熔断打开', faultFrom: 2 },
  { glyph: '备', name: '通用 · 备模型', pack: 'Standby', desc: '版本协商 v2 · 随时接管', takeoverFrom: 4, recoverAt: 9 }
]

const events = [
  { at: 1, label: '健康刷新 · 心跳正常' },
  { at: 2, label: '心跳超时 · 熔断打开' },
  { at: 4, label: 'Failover · 流量切至备模型' },
  { at: 5, label: 'AgentProfile 重绑定' },
  { at: 7, label: 'Key rotation 完成' },
  { at: 8, label: '版本协商 · 协议 v2' },
  { at: 10, label: '治理恢复 · 服务无感' }
] as const

const motionAllowed = () => {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return !window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

const playing = computed(() => props.active && motionAllowed())
const tick = ref(playing.value ? 0 : LOOP_TICKS)
const statusOf = (row: ProviderRow): RowStatus => {
  if (!playing.value) return 'done'
  if (row.faultFrom !== undefined && tick.value >= row.faultFrom) return 'fault'
  if (row.takeoverFrom !== undefined) {
    if (tick.value < row.takeoverFrom) return 'queued'
    if (tick.value < row.recoverAt) return 'running'
  }
  return 'done'
}
const stateLabel = (status: RowStatus) => ({ queued: '待命', running: '接管中', fault: '熔断', done: '健康' })[status]
const phase = computed(() => {
  if (!playing.value) return { id: 'done', label: '全部健康' }
  if (tick.value < 2) return { id: 'running', label: '治理中' }
  if (tick.value < 4) return { id: 'fault', label: '故障转移中' }
  if (tick.value < 10) return { id: 'running', label: '治理中' }
  return { id: 'done', label: '全部健康' }
})
const currentEvent = computed(() => {
  const at = playing.value ? tick.value : LOOP_TICKS
  let found = events[0]
  for (const event of events) { if (at >= event.at) found = event }
  return found
})

let timer: number | undefined
const stopTimer = () => {
  if (timer !== undefined) { window.clearInterval(timer); timer = undefined }
}
const startTimer = () => {
  stopTimer()
  timer = window.setInterval(() => { tick.value = (tick.value + 1) % LOOP_TICKS }, 1000)
}
watch(playing, (value) => {
  if (value) startTimer()
  else { stopTimer(); tick.value = LOOP_TICKS }
}, { immediate: true })
onUnmounted(stopTimer)
</script>

<style scoped lang="scss">
/* 与任务工作区同一「纸上对弈」调色板；星弈变体由落地页 CSS 变量穿透。 */
.provider-demo {
  --demo-ink: #2a241c;
  --demo-ink-soft: #6f665a;
  --demo-muted: #948a7b;
  --demo-line: rgba(58, 50, 38, .18);
  --demo-card: rgba(252, 250, 245, .66);
  --demo-card-strong: rgba(252, 250, 245, .94);
  --demo-accent: #c15f3c;
  --demo-tan: #8a6a3d;
  --demo-success: #3e7c4f;
  --demo-fault: #b0483d;
  --demo-on-ink: #f5f1e8;
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--demo-line);
  border-radius: 12px;
  background: var(--demo-card-strong);
  font-family: var(--font-sans, sans-serif);
  text-align: left;
}
.provider-demo.is-dark {
  --demo-ink: #f2ede4;
  --demo-ink-soft: #c9bfad;
  --demo-muted: #9a8f7e;
  --demo-line: rgba(242, 237, 228, .14);
  --demo-card: rgba(31, 28, 25, .5);
  --demo-card-strong: rgba(42, 37, 31, .92);
  --demo-accent: #d97757;
  --demo-tan: #c99a6b;
  --demo-success: #8fbf9a;
  --demo-fault: #e08a7f;
  --demo-on-ink: #1f1c19;
  border-color: var(--demo-line);
}

.provider-demo__bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 18px; border-bottom: 1px solid var(--demo-line); }
.provider-demo__title { color: var(--demo-muted); font: 700 10px var(--font-mono, monospace); letter-spacing: .16em; }
.provider-demo__status { display: inline-flex; align-items: center; gap: 7px; padding: 3px 11px; border-radius: 999px; color: var(--demo-ink-soft); border: 1px solid var(--demo-line); background: var(--demo-card); font-size: 11px; font-weight: 650; white-space: nowrap; transition: color 240ms ease, border-color 240ms ease; }
.provider-demo__status-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--demo-muted); }
.provider-demo__status.is-running { color: var(--demo-accent); border-color: color-mix(in srgb, var(--demo-accent) 42%, transparent); }
.provider-demo__status.is-running .provider-demo__status-dot { background: var(--demo-accent); animation: provider-pulse 1.1s ease-in-out infinite; }
.provider-demo__status.is-fault { color: var(--demo-fault); border-color: color-mix(in srgb, var(--demo-fault) 46%, transparent); }
.provider-demo__status.is-fault .provider-demo__status-dot { background: var(--demo-fault); animation: provider-pulse .7s ease-in-out infinite; }
.provider-demo__status.is-done { color: var(--demo-success); border-color: color-mix(in srgb, var(--demo-success) 42%, transparent); }
.provider-demo__status.is-done .provider-demo__status-dot { background: var(--demo-success); }

.provider-demo__tiles {
  position: relative;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  padding: 16px 18px;
}
.provider-demo__tile {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 13px 14px;
  border: 1px solid var(--demo-line);
  border-radius: 10px;
  background: var(--demo-card);
  transition: border-color 280ms ease, background-color 280ms ease, box-shadow 280ms ease;
}
.provider-demo__tile.is-fault { border-color: color-mix(in srgb, var(--demo-fault) 48%, transparent); background: color-mix(in srgb, var(--demo-fault) 7%, var(--demo-card)); }
.provider-demo__tile.is-running { border-color: color-mix(in srgb, var(--demo-accent) 44%, transparent); background: color-mix(in srgb, var(--demo-accent) 7%, var(--demo-card)); box-shadow: 0 0 0 3px color-mix(in srgb, var(--demo-accent) 12%, transparent); }
.provider-demo__tile-head { display: flex; align-items: center; gap: 8px; }
.provider-demo__tile-glyph { display: grid; place-items: center; width: 24px; height: 24px; border-radius: 7px; border: 1px solid var(--demo-line); background: var(--demo-card-strong); color: var(--demo-ink); font-style: normal; font-family: var(--font-serif, serif); font-size: 12px; font-weight: 680; }
.provider-demo__tile.is-fault .provider-demo__tile-glyph { color: var(--demo-fault); border-color: color-mix(in srgb, var(--demo-fault) 52%, transparent); }
.provider-demo__tile.is-running .provider-demo__tile-glyph { color: var(--demo-accent); border-color: color-mix(in srgb, var(--demo-accent) 52%, transparent); }
.provider-demo__tile-name { display: inline-flex; align-items: center; gap: 6px; color: var(--demo-ink); font-size: 12px; font-weight: 660; white-space: nowrap; }
.provider-demo__tile-name code { padding: 1px 6px; border-radius: 5px; color: var(--demo-tan); border: 1px solid color-mix(in srgb, var(--demo-tan) 34%, transparent); background: color-mix(in srgb, var(--demo-tan) 8%, transparent); font: 600 9px var(--font-mono, monospace); letter-spacing: .04em; }
.provider-demo__tile-desc { color: var(--demo-ink-soft); font-size: 10.5px; line-height: 1.5; }
.provider-demo__tile-state { display: inline-flex; align-items: center; gap: 6px; margin-top: auto; color: var(--demo-muted); font-size: 10.5px; font-weight: 700; letter-spacing: .04em; }
.provider-demo__state-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--demo-success); }
.provider-demo__tile.is-done .provider-demo__tile-state { color: var(--demo-success); }
.provider-demo__tile.is-queued .provider-demo__state-dot { background: var(--demo-muted); }
.provider-demo__tile.is-queued .provider-demo__tile-state { color: var(--demo-muted); }
.provider-demo__tile.is-fault .provider-demo__state-dot { background: var(--demo-fault); animation: provider-pulse .7s ease-in-out infinite; }
.provider-demo__tile.is-fault .provider-demo__tile-state { color: var(--demo-fault); }
.provider-demo__tile.is-running .provider-demo__state-dot { background: var(--demo-accent); animation: provider-pulse 1.1s ease-in-out infinite; }
.provider-demo__tile.is-running .provider-demo__tile-state { color: var(--demo-accent); }

.provider-demo__link {
  position: absolute;
  top: 50%;
  left: calc(25px + (100% - 36px) * 0.6667);
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transition: opacity 320ms ease;
  pointer-events: none;
}
.provider-demo__link.is-hot { opacity: 1; }
.provider-demo__link svg { width: 46px; height: 12px; overflow: visible; }
.provider-demo__link line {
  stroke: var(--demo-accent);
  stroke-width: 2;
  stroke-dasharray: 5 4;
}
.provider-demo__link.is-hot line { animation: provider-dash 0.9s linear infinite; }
.provider-demo__link path { fill: var(--demo-accent); }
.provider-demo__link span { padding: 0 6px; border-radius: 5px; color: var(--demo-on-ink); background: var(--demo-accent); font: 700 8.5px var(--font-mono, monospace); letter-spacing: .08em; }

.provider-demo__foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 40px; padding: 9px 18px; border-top: 1px solid var(--demo-line); }
.provider-demo__ticker { display: inline-flex; align-items: center; gap: 8px; overflow: hidden; color: var(--demo-ink-soft); font-size: 11px; font-weight: 620; white-space: nowrap; text-overflow: ellipsis; }
.provider-demo__ticker i { flex: 0 0 5px; width: 5px; height: 5px; border-radius: 50%; background: var(--demo-success); box-shadow: 0 0 8px color-mix(in srgb, var(--demo-success) 55%, transparent); }
.provider-ticker-enter-active, .provider-ticker-leave-active { transition: opacity 220ms ease, transform 220ms ease; }
.provider-ticker-enter-from { opacity: 0; transform: translateX(8px); }
.provider-ticker-leave-to { opacity: 0; transform: translateX(-8px); }
.provider-demo__dots { display: inline-flex; flex: 0 0 auto; gap: 4px; }
.provider-demo__dots i { width: 6px; height: 6px; border-radius: 50%; background: color-mix(in srgb, var(--demo-ink) 14%, transparent); transition: background-color 240ms ease; }
.provider-demo__dots i.is-on { background: color-mix(in srgb, var(--demo-accent) 70%, transparent); }

@keyframes provider-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .3; } }
@keyframes provider-dash { to { stroke-dashoffset: -18; } }

@media (prefers-reduced-motion: reduce) {
  .provider-demo__tile, .provider-demo__link, .provider-ticker-enter-active, .provider-ticker-leave-active { transition: none; }
  .provider-demo__status-dot, .provider-demo__state-dot { animation: none; }
  .provider-demo__link.is-hot line { animation: none; }
}

@media (max-width: 720px) {
  .provider-demo__tiles { grid-template-columns: 1fr; }
  .provider-demo__link { display: none; }
  .provider-demo__dots { display: none; }
}
</style>
