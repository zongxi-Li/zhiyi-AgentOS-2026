<template>
  <div
    class="mission-demo"
    :class="{ 'is-dark': dark }"
    data-testid="mission-run-demo"
    role="group"
    aria-label="任务运行演示：从目标到交付的一局任务"
  >
    <header class="mission-demo__bar">
      <span class="mission-demo__title">MISSION WORKSPACE · 任务工作区</span>
      <span class="mission-demo__status" :class="`is-${missionStatus.id}`" aria-live="polite">
        <i class="mission-demo__status-dot" aria-hidden="true"></i>{{ missionStatus.label }}
      </span>
    </header>

    <div class="mission-demo__goal">
      <span class="mission-demo__goal-label">目标</span>
      <p class="mission-demo__goal-text">编排一门智能体入门课程<span class="mission-demo__caret" aria-hidden="true"></span></p>
    </div>

    <div class="mission-demo__body">
      <ol class="mission-demo__steps" aria-label="执行步骤">
        <li
          v-for="step in steps"
          :key="step.name"
          class="mission-demo__step"
          :class="`is-${statusOf(step)}`"
        >
          <span class="mission-demo__avatar" aria-hidden="true">{{ step.glyph }}</span>
          <span class="mission-demo__step-copy">
            <span class="mission-demo__step-name">{{ step.name }}<code v-if="step.pack">{{ step.pack }}</code></span>
            <span class="mission-demo__step-desc">{{ step.desc }}</span>
          </span>
          <span class="mission-demo__step-state">{{ stateLabel(statusOf(step)) }}</span>
        </li>
        <span class="mission-demo__rail" aria-hidden="true"><span class="mission-demo__rail-fill" :style="{ transform: `scaleY(${progress})` }"></span></span>
      </ol>

      <aside class="mission-demo__trace" aria-label="运行审计时间线">
        <p class="mission-demo__trace-title">TRACE · 运行审计</p>
        <ul class="mission-demo__events">
          <li
            v-for="event in events"
            :key="event.label"
            class="mission-demo__event"
            :class="{ 'is-shown': tick >= event.at }"
          >
            <i aria-hidden="true"></i><span>{{ event.label }}</span>
          </li>
        </ul>
      </aside>
    </div>

    <footer class="mission-demo__chips" aria-label="运行机制">
      <span v-for="chip in mechanisms" :key="chip" class="mission-demo__chip">{{ chip }}</span>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'

/* 一局任务的演示时间线。12 拍循环：规划 → 教育/通用并行 superstep →
   写作成稿 → Runtime 审计交付，随后回到起点。所有步骤、事件与机制名
   均来自真实运行时概念（Planner / parallel superstep / Checkpoint CAS /
   GraphPatch / Review barrier / outputRef），不虚构数值指标；
   任务与角色取自落地页场景区的教育/通用/写作 Domain Pack。 */
const LOOP_TICKS = 12

const props = withDefaults(defineProps<{ active?: boolean; dark?: boolean }>(), { active: false, dark: false })

const steps = [
  { glyph: '划', name: 'Planner 规划', pack: 'Runtime', desc: '意图拆解 · ACG 动态组网', start: 0, end: 3 },
  { glyph: '教', name: '教育 Agent', pack: 'Education', desc: '教学设计 · 课时编排', start: 3, end: 7 },
  { glyph: '通', name: '通用 Agent', pack: 'General', desc: '资料整理 · 案例搜集', start: 3, end: 7 },
  { glyph: '写', name: '写作 Agent', pack: 'Writer', desc: '讲义成稿 · 习题生成', start: 7, end: 10 },
  { glyph: '计', name: 'Runtime 审计', pack: '', desc: 'Checkpoint · Trace · 交付', start: 10, end: 12 }
] as const

const events = [
  { at: 0, label: '意图解析 Intent' },
  { at: 3, label: 'ACG 组网 Graph compiled' },
  { at: 4, label: '并行 superstep 启动' },
  { at: 5, label: 'Checkpoint CAS 保存' },
  { at: 8, label: 'GraphPatch · 新增实验课' },
  { at: 9, label: 'Evidence 资料核对' },
  { at: 10, label: 'Review barrier 通过' },
  { at: 11, label: 'outputRef 解引用交付' }
] as const

const mechanisms = ['Checkpoint CAS', 'GraphPatch', 'Communication Broker', '熵预算', 'Evidence Store', 'Failover'] as const

const motionAllowed = () => {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return !window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

const playing = computed(() => props.active && motionAllowed())
const tick = ref(playing.value ? 0 : LOOP_TICKS)
const statusOf = (step: { start: number; end: number }) => {
  if (!playing.value) return 'done' as const
  if (tick.value < step.start) return 'queued' as const
  if (tick.value < step.end) return 'running' as const
  return 'done' as const
}
const stateLabel = (status: 'queued' | 'running' | 'done') => ({ queued: '排队', running: '运行中', done: '完成' })[status]
const missionStatus = computed(() => {
  if (!playing.value) return { id: 'done', label: '交付完成' }
  if (tick.value < 3) return { id: 'planning', label: '规划中' }
  if (tick.value < 11) return { id: 'running', label: '运行中' }
  return { id: 'done', label: '交付完成' }
})
const progress = computed(() => (playing.value ? Math.min(tick.value / (LOOP_TICKS - 1), 1) : 1))

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
/* 「纸上对弈」暖纸调色板：墨字、铜橘运行态、绿完成态，与落地页同一语言。 */
.mission-demo {
  --demo-ink: #2a241c;
  --demo-ink-soft: #6f665a;
  --demo-muted: #948a7b;
  --demo-line: rgba(58, 50, 38, .18);
  --demo-card: rgba(252, 250, 245, .66);
  --demo-card-strong: rgba(252, 250, 245, .94);
  --demo-accent: #c15f3c;
  --demo-tan: #8a6a3d;
  --demo-success: #3e7c4f;
  --demo-on-ink: #f5f1e8;
  --demo-planning: #a97e2f;
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
.mission-demo.is-dark {
  --demo-ink: #f2ede4;
  --demo-ink-soft: #c9bfad;
  --demo-muted: #9a8f7e;
  --demo-line: rgba(242, 237, 228, .14);
  --demo-card: rgba(31, 28, 25, .5);
  --demo-card-strong: rgba(42, 37, 31, .92);
  --demo-accent: #d97757;
  --demo-tan: #c99a6b;
  --demo-success: #8fbf9a;
  --demo-on-ink: #1f1c19;
  --demo-planning: #d9b66f;
  border-color: var(--demo-line);
}

.mission-demo__bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 18px; border-bottom: 1px solid var(--demo-line); }
.mission-demo__title { color: var(--demo-muted); font: 700 10px var(--font-mono, monospace); letter-spacing: .16em; }
.mission-demo__status { display: inline-flex; align-items: center; gap: 7px; padding: 3px 11px; border-radius: 999px; color: var(--demo-ink-soft); border: 1px solid var(--demo-line); background: var(--demo-card); font-size: 11px; font-weight: 650; white-space: nowrap; transition: color 240ms ease, border-color 240ms ease, background-color 240ms ease; }
.mission-demo__status-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--demo-muted); }
.mission-demo__status.is-running { color: var(--demo-accent); border-color: color-mix(in srgb, var(--demo-accent) 42%, transparent); }
.mission-demo__status.is-running .mission-demo__status-dot { background: var(--demo-accent); animation: demo-pulse 1.1s ease-in-out infinite; }
.mission-demo__status.is-planning { color: var(--demo-planning); }
.mission-demo__status.is-planning .mission-demo__status-dot { background: var(--demo-planning); }
.mission-demo__status.is-done { color: var(--demo-success); border-color: color-mix(in srgb, var(--demo-success) 42%, transparent); }
.mission-demo__status.is-done .mission-demo__status-dot { background: var(--demo-success); }

.mission-demo__goal { display: flex; align-items: center; gap: 12px; padding: 12px 18px; border-bottom: 1px solid var(--demo-line); }
.mission-demo__goal-label { flex: 0 0 auto; padding: 3px 10px; border-radius: 7px; color: var(--demo-on-ink); background: var(--demo-ink); font-size: 10px; font-weight: 700; letter-spacing: .08em; }
.mission-demo__goal-text { margin: 0; color: var(--demo-ink); font-size: 13.5px; font-weight: 640; letter-spacing: -.01em; }
.mission-demo__caret { display: inline-block; width: 1.5px; height: 14px; margin-left: 5px; vertical-align: -2px; background: var(--demo-accent); animation: demo-caret 1s steps(1) infinite; }

.mission-demo__body { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(0, .85fr); gap: 0; min-height: 0; flex: 1; }
.mission-demo__steps { position: relative; display: flex; flex-direction: column; justify-content: center; gap: 9px; margin: 0; padding: 16px 18px 16px 20px; list-style: none; }
.mission-demo__rail { position: absolute; top: 24px; bottom: 24px; left: 33px; width: 2px; border-radius: 99px; background: var(--demo-line); }
.mission-demo__rail-fill { position: absolute; inset: 0; transform-origin: top; background: linear-gradient(180deg, var(--demo-accent), var(--demo-tan)); transition: transform 700ms cubic-bezier(.3, .8, .3, 1); }
.mission-demo__step { position: relative; z-index: 1; display: flex; align-items: center; gap: 11px; padding: 9px 12px; border: 1px solid transparent; border-radius: 10px; transition: background-color 260ms ease, border-color 260ms ease, opacity 260ms ease, transform 260ms ease; }
.mission-demo__step.is-queued { opacity: .52; }
.mission-demo__step.is-running { border-color: color-mix(in srgb, var(--demo-accent) 30%, transparent); background: color-mix(in srgb, var(--demo-accent) 7%, transparent); transform: translateX(3px); }
.mission-demo__step.is-done { background: transparent; }
.mission-demo__avatar { flex: 0 0 26px; display: grid; place-items: center; width: 26px; height: 26px; border-radius: 7px; border: 1px solid var(--demo-line); color: var(--demo-ink); background: var(--demo-card-strong); font-size: 12px; font-weight: 680; font-family: var(--font-serif, serif); transition: border-color 260ms ease, box-shadow 260ms ease, color 260ms ease; }
.mission-demo__step.is-running .mission-demo__avatar { border-color: color-mix(in srgb, var(--demo-accent) 55%, transparent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--demo-accent) 14%, transparent); }
.mission-demo__step.is-done .mission-demo__avatar { color: var(--demo-success); border-color: color-mix(in srgb, var(--demo-success) 40%, transparent); }
.mission-demo__step-copy { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.mission-demo__step-name { display: inline-flex; align-items: center; gap: 7px; color: var(--demo-ink); font-size: 12.5px; font-weight: 660; white-space: nowrap; }
.mission-demo__step-name code { padding: 1px 6px; border-radius: 5px; color: var(--demo-tan); border: 1px solid color-mix(in srgb, var(--demo-tan) 34%, transparent); background: color-mix(in srgb, var(--demo-tan) 8%, transparent); font: 600 9px var(--font-mono, monospace); letter-spacing: .04em; }
.mission-demo__step-desc { overflow: hidden; color: var(--demo-ink-soft); font-size: 11px; white-space: nowrap; text-overflow: ellipsis; }
.mission-demo__step-state { flex: 0 0 auto; color: var(--demo-muted); font-size: 10px; font-weight: 650; letter-spacing: .05em; }
.mission-demo__step.is-running .mission-demo__step-state { color: var(--demo-accent); }
.mission-demo__step.is-done .mission-demo__step-state { color: var(--demo-success); }

.mission-demo__trace { display: flex; flex-direction: column; gap: 4px; padding: 16px 16px 16px 14px; border-left: 1px solid var(--demo-line); }
.mission-demo__trace-title { margin: 0 0 8px; color: var(--demo-muted); font: 700 9.5px var(--font-mono, monospace); letter-spacing: .15em; }
.mission-demo__events { display: flex; flex-direction: column; gap: 2px; margin: 0; padding: 0; list-style: none; }
.mission-demo__event { display: flex; align-items: center; gap: 9px; padding: 4px 2px; color: var(--demo-ink-soft); font-size: 11px; opacity: 0; transform: translateX(8px); transition: opacity 320ms ease, transform 320ms var(--ease-out, ease-out), color 320ms ease; }
.mission-demo__event.is-shown { opacity: 1; transform: translateX(0); }
.mission-demo__event i { flex: 0 0 5px; width: 5px; height: 5px; border-radius: 50%; background: var(--demo-muted); }
.mission-demo__event.is-shown i { background: var(--demo-success); box-shadow: 0 0 8px color-mix(in srgb, var(--demo-success) 55%, transparent); }

.mission-demo__chips { display: flex; flex-wrap: wrap; gap: 6px; padding: 11px 16px; border-top: 1px solid var(--demo-line); }
.mission-demo__chip { padding: 3px 9px; border-radius: 6px; color: var(--demo-ink-soft); border: 1px solid var(--demo-line); background: var(--demo-card); font: 600 9.5px var(--font-mono, monospace); letter-spacing: .03em; }

@keyframes demo-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .3; } }
@keyframes demo-caret { 0%, 49% { opacity: 1; } 50%, 100% { opacity: 0; } }

@media (prefers-reduced-motion: reduce) {
  .mission-demo__rail-fill { transition: none; }
  .mission-demo__event { transition: none; opacity: 1; transform: none; }
  .mission-demo__step { transition: none; }
  .mission-demo__status-dot, .mission-demo__caret { animation: none; }
}

@media (max-width: 620px) {
  .mission-demo__body { grid-template-columns: 1fr; }
  .mission-demo__trace { border-top: 1px solid var(--demo-line); border-left: 0; }
  .mission-demo__rail { display: none; }
}
</style>
