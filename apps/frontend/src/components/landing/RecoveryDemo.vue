<template>
  <div
    class="recovery-demo"
    :class="{ 'is-dark': dark, 'is-live': playing }"
    data-testid="recovery-run-demo"
    role="group"
    aria-label="中断恢复演示：Checkpoint CAS 断点续跑的 Trace 瀑布"
  >
    <header class="recovery-demo__bar">
      <span class="recovery-demo__title">RECOVERY TRACE · 恢复瀑布</span>
      <span class="recovery-demo__status" :class="`is-${phase.id}`" aria-live="polite">
        <i class="recovery-demo__status-dot" aria-hidden="true"></i>{{ phase.label }}
      </span>
    </header>

    <div class="recovery-demo__waterfall" role="img" :aria-label="`恢复时间线：${currentEvent?.label ?? '已恢复交付'}`">
      <div class="recovery-demo__lane-head" aria-hidden="true">
        <span class="recovery-demo__lane-label">SPAN</span>
        <div class="recovery-demo__axis">
          <span v-for="t in axisTicks" :key="t" class="recovery-demo__axis-tick" :style="{ left: `${(t / LOOP_TICKS) * 100}%` }">{{ t }}</span>
        </div>
      </div>

      <div v-for="lane in lanes" :key="lane.name" class="recovery-demo__lane">
        <span class="recovery-demo__lane-label">
          <i class="recovery-demo__lane-glyph" aria-hidden="true">{{ lane.glyph }}</i>{{ lane.name }}
        </span>
        <div class="recovery-demo__track">
          <span
            v-for="seg in lane.segs"
            :key="`${seg.from}-${seg.to}`"
            class="recovery-demo__span"
            :class="[`is-${seg.kind}`, { 'is-on': !playing || tick >= seg.from }]"
            :style="{ left: `${(seg.from / LOOP_TICKS) * 100}%`, width: `${((seg.to - seg.from) / LOOP_TICKS) * 100}%` }"
          >
            <small>{{ seg.label }}</small>
          </span>
          <span
            v-if="lane.gapHint"
            class="recovery-demo__gap-hint"
            :style="{ left: `${(lane.gapHint.from / LOOP_TICKS) * 100}%`, width: `${((lane.gapHint.to - lane.gapHint.from) / LOOP_TICKS) * 100}%` }"
          >{{ lane.gapHint.label }}</span>
        </div>
      </div>

      <span class="recovery-demo__playhead" aria-hidden="true" :style="{ '--ph': playheadRatio }"></span>
    </div>

    <footer class="recovery-demo__foot">
      <Transition name="recovery-ticker" mode="out-in">
        <span v-if="currentEvent" :key="currentEvent.label" class="recovery-demo__ticker">
          <i aria-hidden="true"></i>{{ currentEvent.label }}
        </span>
      </Transition>
      <span class="recovery-demo__legend" aria-hidden="true">
        <em><i class="is-done"></i>快照</em>
        <em><i class="is-fault"></i>中断</em>
        <em><i class="is-patch"></i>重组</em>
        <em><i class="is-run"></i>续跑</em>
      </span>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'

/* 中断恢复的 Trace 瀑布演示（Jaeger/Zipkin 式泳道时间轴）。11 拍循环：
   Checkpoint 快照 → 写作节点失效 → GraphPatch 重组 → 断点续跑 → Review 交付。
   泳道段、事件与机制名均来自真实运行时概念（Checkpoint CAS / GraphPatch /
   alternate rebind / Review barrier / Evidence），任务延续任务工作区演示的
   同一门课程，不虚构数值指标。 */
const LOOP_TICKS = 11

const props = withDefaults(defineProps<{ active?: boolean; dark?: boolean }>(), { active: false, dark: false })

const axisTicks = [0, 2, 4, 6, 8, 10] as const

type SpanKind = 'done' | 'fault' | 'patch' | 'run'
type Span = { from: number; to: number; kind: SpanKind; label: string }
type Lane = { glyph: string; name: string; segs: Span[]; gapHint?: { from: number; to: number; label: string } }
const lanes: Lane[] = [
  { glyph: '存', name: 'Checkpoint', segs: [{ from: 0, to: 2, kind: 'done', label: 'CAS 快照' }] },
  { glyph: '写', name: '写作 Agent', segs: [{ from: 2, to: 4, kind: 'fault', label: '模型超时' }, { from: 6, to: 9, kind: 'run', label: '断点续跑' }], gapHint: { from: 4, to: 6, label: '等待重组' } },
  { glyph: '治', name: 'Runtime', segs: [{ from: 4, to: 6, kind: 'patch', label: 'GraphPatch' }, { from: 9, to: 11, kind: 'done', label: 'Review · 交付' }] }
]

const events = [
  { at: 0, label: 'Checkpoint CAS 快照' },
  { at: 2, label: '节点失效 · 模型超时' },
  { at: 4, label: 'GraphPatch 局部重组' },
  { at: 5, label: 'alternate rebind · 写作节点' },
  { at: 6, label: 'Resume · attempt 2' },
  { at: 8, label: 'Evidence 复核通过' },
  { at: 10, label: 'Review barrier · 交付' }
] as const

const motionAllowed = () => {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return !window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

const playing = computed(() => props.active && motionAllowed())
const tick = ref(playing.value ? 0 : LOOP_TICKS)
const phase = computed(() => {
  if (!playing.value) return { id: 'done', label: '已恢复交付' }
  if (tick.value < 2) return { id: 'running', label: '快照中' }
  if (tick.value < 4) return { id: 'fault', label: '节点中断' }
  if (tick.value < 10) return { id: 'running', label: '恢复中' }
  return { id: 'done', label: '已恢复交付' }
})
const playheadRatio = computed(() => ((playing.value ? tick.value : LOOP_TICKS) / LOOP_TICKS).toFixed(4))
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
.recovery-demo {
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
.recovery-demo.is-dark {
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

.recovery-demo__bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 18px; border-bottom: 1px solid var(--demo-line); }
.recovery-demo__title { color: var(--demo-muted); font: 700 10px var(--font-mono, monospace); letter-spacing: .16em; }
.recovery-demo__status { display: inline-flex; align-items: center; gap: 7px; padding: 3px 11px; border-radius: 999px; color: var(--demo-ink-soft); border: 1px solid var(--demo-line); background: var(--demo-card); font-size: 11px; font-weight: 650; white-space: nowrap; transition: color 240ms ease, border-color 240ms ease; }
.recovery-demo__status-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--demo-muted); }
.recovery-demo__status.is-running { color: var(--demo-accent); border-color: color-mix(in srgb, var(--demo-accent) 42%, transparent); }
.recovery-demo__status.is-running .recovery-demo__status-dot { background: var(--demo-accent); animation: recovery-pulse 1.1s ease-in-out infinite; }
.recovery-demo__status.is-fault { color: var(--demo-fault); border-color: color-mix(in srgb, var(--demo-fault) 46%, transparent); }
.recovery-demo__status.is-fault .recovery-demo__status-dot { background: var(--demo-fault); animation: recovery-pulse .7s ease-in-out infinite; }
.recovery-demo__status.is-done { color: var(--demo-success); border-color: color-mix(in srgb, var(--demo-success) 42%, transparent); }
.recovery-demo__status.is-done .recovery-demo__status-dot { background: var(--demo-success); }

.recovery-demo__waterfall { position: relative; display: flex; flex-direction: column; gap: 8px; padding: 14px 18px 16px 18px; }
.recovery-demo__lane { display: grid; grid-template-columns: 108px minmax(0, 1fr); align-items: center; gap: 10px; }
.recovery-demo__lane-head { display: grid; grid-template-columns: 108px minmax(0, 1fr); gap: 10px; }
.recovery-demo__lane-label { display: inline-flex; align-items: center; gap: 7px; color: var(--demo-ink-soft); font-size: 11px; font-weight: 660; white-space: nowrap; }
.recovery-demo__lane-head .recovery-demo__lane-label { color: var(--demo-muted); font: 700 9.5px var(--font-mono, monospace); letter-spacing: .14em; }
.recovery-demo__lane-glyph { display: grid; place-items: center; width: 18px; height: 18px; border-radius: 5px; border: 1px solid var(--demo-line); background: var(--demo-card-strong); color: var(--demo-ink); font-style: normal; font-family: var(--font-serif, serif); font-size: 10.5px; font-weight: 680; }

.recovery-demo__axis { position: relative; height: 14px; }
.recovery-demo__axis-tick { position: absolute; top: 0; transform: translateX(-50%); color: var(--demo-muted); font: 600 9px var(--font-mono, monospace); }

.recovery-demo__track {
  --track-line: color-mix(in srgb, var(--demo-ink) 14%, transparent);
  position: relative;
  height: 28px;
  border-radius: 7px;
  background: repeating-linear-gradient(90deg, transparent 0, transparent calc(100% / 11 - 1px), var(--track-line) calc(100% / 11 - 1px), var(--track-line) calc(100% / 11));
}
.recovery-demo__span {
  position: absolute;
  top: 4px;
  bottom: 4px;
  display: flex;
  align-items: center;
  overflow: hidden;
  padding: 0 7px;
  border-radius: 6px;
  color: var(--demo-on-ink);
  font-size: 9.5px;
  font-weight: 650;
  letter-spacing: .02em;
  white-space: nowrap;
  transform: scaleX(0);
  transform-origin: left center;
  transition: transform 640ms cubic-bezier(.3, .8, .3, 1);
}
.recovery-demo__span.is-on { transform: none; }
.recovery-demo__span small { overflow: hidden; text-overflow: ellipsis; }
.recovery-demo__span.is-done { background: var(--demo-success); }
.recovery-demo__span.is-fault { background: var(--demo-fault); }
.recovery-demo__span.is-patch { background: var(--demo-tan); }
.recovery-demo__span.is-run { background: var(--demo-accent); }
.recovery-demo__gap-hint {
  position: absolute;
  top: 4px;
  bottom: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px dashed color-mix(in srgb, var(--demo-muted) 55%, transparent);
  border-radius: 6px;
  color: var(--demo-muted);
  font-size: 9px;
  opacity: 0;
  transition: opacity 320ms ease;
}
.recovery-demo__gap-hint, .recovery-demo__span { pointer-events: none; }
.recovery-demo.is-live .recovery-demo__gap-hint { opacity: 1; }

.recovery-demo__playhead {
  position: absolute;
  top: 12px;
  bottom: 14px;
  width: 2px;
  left: calc(118px + (100% - 118px) * var(--ph, 0));
  border-radius: 2px;
  background: color-mix(in srgb, var(--demo-accent) 72%, transparent);
  box-shadow: 0 0 8px color-mix(in srgb, var(--demo-accent) 40%, transparent);
  transition: left 880ms linear;
  pointer-events: none;
}

.recovery-demo__foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 40px; padding: 9px 18px; border-top: 1px solid var(--demo-line); }
.recovery-demo__ticker { display: inline-flex; align-items: center; gap: 8px; overflow: hidden; color: var(--demo-ink-soft); font-size: 11px; font-weight: 620; white-space: nowrap; text-overflow: ellipsis; }
.recovery-demo__ticker i { flex: 0 0 5px; width: 5px; height: 5px; border-radius: 50%; background: var(--demo-success); box-shadow: 0 0 8px color-mix(in srgb, var(--demo-success) 55%, transparent); }
.recovery-ticker-enter-active, .recovery-ticker-leave-active { transition: opacity 220ms ease, transform 220ms ease; }
.recovery-ticker-enter-from { opacity: 0; transform: translateX(8px); }
.recovery-ticker-leave-to { opacity: 0; transform: translateX(-8px); }
.recovery-demo__legend { display: inline-flex; flex: 0 0 auto; gap: 10px; }
.recovery-demo__legend em { display: inline-flex; align-items: center; gap: 5px; color: var(--demo-muted); font-size: 9.5px; font-style: normal; }
.recovery-demo__legend i { width: 8px; height: 8px; border-radius: 3px; }
.recovery-demo__legend .is-done { background: var(--demo-success); }
.recovery-demo__legend .is-fault { background: var(--demo-fault); }
.recovery-demo__legend .is-patch { background: var(--demo-tan); }
.recovery-demo__legend .is-run { background: var(--demo-accent); }

@keyframes recovery-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .3; } }

@media (prefers-reduced-motion: reduce) {
  .recovery-demo__span, .recovery-demo__playhead, .recovery-ticker-enter-active, .recovery-ticker-leave-active { transition: none; }
  .recovery-demo__status-dot { animation: none; }
}

@media (max-width: 620px) {
  .recovery-demo__lane, .recovery-demo__lane-head { grid-template-columns: 84px minmax(0, 1fr); }
  .recovery-demo__lane-label { font-size: 10px; }
  .recovery-demo__legend { display: none; }
  .recovery-demo__playhead { left: calc(94px + (100% - 94px) * var(--ph, 0)); }
}
</style>
