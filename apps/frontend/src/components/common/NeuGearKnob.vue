<template>
  <div
    class="neu-gear-knob"
    role="slider"
    :aria-label="ariaLabel"
    :aria-valuemin="0"
    :aria-valuemax="Math.max(options.length - 1, 0)"
    :aria-valuenow="index"
    :aria-valuetext="activeLabel"
    :aria-disabled="disabled || undefined"
    tabindex="0"
    :style="{ '--knob-size': `${size}px`, '--gear-progress': String(progress), '--gear-accent': activeColor }"
    @pointerdown="onPointerDown"
    @pointermove="onPointerMove"
    @pointerup="onPointerUp"
    @pointercancel="onPointerUp"
    @keydown="onKeydown"
  >
    <span class="neu-gear-knob__face" aria-hidden="true"></span>
    <span class="neu-gear-knob__arc" aria-hidden="true" :style="{ '--gear-sweep': `${sweep}deg` }"></span>
    <span class="neu-gear-knob__well" aria-hidden="true"></span>
    <span
      v-for="(option, i) in options"
      :key="String(option.value)"
      class="neu-gear-knob__tick"
      :class="{ 'is-active': i === index }"
      :style="{ '--gear-color': option.color, transform: `rotate(${angle(i)}deg)` }"
      aria-hidden="true"
    >
      <span
        class="neu-gear-knob__tick-hit"
        :title="option.label"
        @pointerdown.stop
        @click="setIndex(i)"
      ></span>
    </span>
    <span class="neu-gear-knob__pin" aria-hidden="true" :style="{ transform: `rotate(${angle(index)}deg)` }"></span>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

export interface NeuGearKnobOption {
  value: string | number
  label: string
  /** 挡位语义色（任意 CSS 颜色或 var() 引用），驱动刻度/指针/渐变弧 */
  color?: string
}

const props = withDefaults(defineProps<{
  options: NeuGearKnobOption[]
  modelValue: string | number
  disabled?: boolean
  size?: number
  ariaLabel?: string
}>(), { disabled: false, size: 124, ariaLabel: '挡位旋钮' })

const emit = defineEmits<{ 'update:modelValue': [value: string | number] }>()

const index = computed(() => {
  const found = props.options.findIndex(option => String(option.value) === String(props.modelValue))
  return Math.max(0, found)
})
const progress = computed(() => (props.options.length > 1 ? index.value / (props.options.length - 1) : 0))
const sweep = computed(() => 270 * progress.value)
const activeLabel = computed(() => props.options[index.value]?.label || '')
const activeColor = computed(() => props.options[index.value]?.color || 'var(--accent-color, #4FC1FF)')

// 270° 量程（底部留 90° 缺口），指针按档位吸附（物理旋钮手感）
function angle(i: number): number {
  return props.options.length > 1 ? -135 + (270 / (props.options.length - 1)) * i : 0
}

function setIndex(next: number): void {
  if (props.disabled || !props.options.length) return
  const clamped = Math.max(0, Math.min(props.options.length - 1, next))
  const option = props.options[clamped]
  if (option && String(option.value) !== String(props.modelValue)) emit('update:modelValue', option.value)
}

let dragActive = false
let dragStartY = 0
let dragStartIndex = 0

function onPointerDown(event: PointerEvent): void {
  if (props.disabled) return
  dragActive = true
  dragStartY = event.clientY
  dragStartIndex = index.value
  try { (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId) } catch { /* 指针未激活时忽略 */ }
}

function onPointerMove(event: PointerEvent): void {
  if (!dragActive) return
  // 纵向拖拽：每 24px 换一档，向上加档、向下减档
  setIndex(dragStartIndex + Math.round((dragStartY - event.clientY) / 24))
}

function onPointerUp(event: PointerEvent): void {
  dragActive = false
  const element = event.currentTarget as HTMLElement
  if (element.hasPointerCapture && element.hasPointerCapture(event.pointerId)) {
    element.releasePointerCapture(event.pointerId)
  }
}

function onKeydown(event: KeyboardEvent): void {
  if (props.disabled) return
  if (event.key === 'ArrowUp' || event.key === 'ArrowRight') { setIndex(index.value + 1); event.preventDefault() }
  if (event.key === 'ArrowDown' || event.key === 'ArrowLeft') { setIndex(index.value - 1); event.preventDefault() }
  if (event.key === 'Home') { setIndex(0); event.preventDefault() }
  if (event.key === 'End') { setIndex(props.options.length - 1); event.preventDefault() }
}
</script>

<style scoped>
/* 拟物挡位旋钮。表面取所在容器的 --neu-surface（继承），未定义时回退主题 --bg-card；
   浅色方案白体系（暗角灰/亮角白），暗色方案覆盖派生比例。 */
.neu-gear-knob {
  --neu-fallback: var(--bg-card, #252526);
  --neu-dark: color-mix(in srgb, #000 16%, var(--neu-surface, var(--neu-fallback)));
  --neu-light: #ffffff;
  --neu-dark-strong: color-mix(in srgb, #000 34%, var(--neu-surface, var(--neu-fallback)));
  position: relative;
  width: var(--knob-size);
  height: var(--knob-size);
  border-radius: 50%;
  cursor: grab;
  touch-action: none;
}
html[data-color-scheme='codex-dark'] .neu-gear-knob,
html[data-color-scheme='one-dark-modern'] .neu-gear-knob {
  --neu-dark: color-mix(in srgb, #000 26%, var(--neu-surface, var(--neu-fallback)));
  --neu-light: color-mix(in srgb, #fff 15%, var(--neu-surface, var(--neu-fallback)));
}
.neu-gear-knob:active { cursor: grabbing; }
.neu-gear-knob:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 4px; }
.neu-gear-knob[aria-disabled='true'] { cursor: not-allowed; opacity: .55; }
.neu-gear-knob__face { position: absolute; inset: 0; border-radius: 50%; background: var(--neu-surface, var(--neu-fallback));
  box-shadow: 5px 6px 12px var(--neu-dark-strong), -5px -5px 12px var(--neu-light), 2px 3px 6px var(--neu-dark); }
/* 面染色随挡位渐变：关档近乎原色，档位越高，当前档位色的径向晕染越明显 */
.neu-gear-knob__face::after { content: ''; position: absolute; inset: 0; border-radius: 50%;
  background:
    radial-gradient(circle at 50% 46%, color-mix(in srgb, var(--gear-accent) calc(7% + var(--gear-progress, 0) * 26%), transparent) 0%, transparent 64%),
    radial-gradient(circle at 30% 22%, color-mix(in srgb, var(--neu-light) 52%, transparent) 0%, transparent 50%); }
/* 渐变弧：从首档起点长到当前档位指针处 */
.neu-gear-knob__arc { position: absolute; inset: 6px; border-radius: 50%; pointer-events: none; opacity: .85;
  background: conic-gradient(from 225deg, color-mix(in srgb, var(--gear-accent) 62%, transparent) 0deg var(--gear-sweep, 0deg), transparent var(--gear-sweep, 0deg));
  -webkit-mask: radial-gradient(closest-side, transparent calc(100% - 10px), #000 calc(100% - 9px));
  mask: radial-gradient(closest-side, transparent calc(100% - 10px), #000 calc(100% - 9px)); }
.neu-gear-knob__well { position: absolute; inset: 17px; border-radius: 50%;
  box-shadow: inset 3px 3px 7px var(--neu-dark-strong), inset -3px -3px 7px var(--neu-light); }
.neu-gear-knob__tick { position: absolute; inset: 0; pointer-events: none; transition: transform 300ms cubic-bezier(.22, 1, .36, 1); }
.neu-gear-knob__tick::after { content: ''; position: absolute; top: 5px; left: 50%; width: 4px; height: 4px;
  margin-left: -2px; border-radius: 50%; background: color-mix(in srgb, var(--gear-color) 48%, transparent);
  transition: background-color 200ms ease, box-shadow 200ms ease; }
.neu-gear-knob__tick.is-active::after { background: var(--gear-color);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--gear-color) 22%, transparent); }
/* 刻度点即换挡热区：点按单个刻度直达该档（pointerdown 截断，避免触发旋钮拖拽捕获） */
.neu-gear-knob__tick-hit { position: absolute; top: -2px; left: 50%; width: 18px; height: 18px;
  margin-left: -9px; border-radius: 50%; cursor: pointer; }
.neu-gear-knob[aria-disabled='true'] .neu-gear-knob__tick-hit { cursor: not-allowed; }
.neu-gear-knob__pin { position: absolute; inset: 0; pointer-events: none;
  transition: transform 300ms cubic-bezier(.22, 1, .36, 1); }
.neu-gear-knob__pin::after { content: ''; position: absolute; top: 10px; left: 50%; width: 3px; height: 20px;
  margin-left: -1.5px; border-radius: 2px; background: var(--gear-accent);
  box-shadow: 0 0 6px color-mix(in srgb, var(--gear-accent) 40%, transparent); }
@media (prefers-reduced-motion: reduce) {
  .neu-gear-knob__pin, .neu-gear-knob__tick { transition: none; }
}
</style>
