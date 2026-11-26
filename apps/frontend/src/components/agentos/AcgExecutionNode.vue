<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { motion, useMotionValueEvent, useSpring } from 'motion-v'

const props = defineProps<{ id: string; name: string; status: string; statusLabel: string; expanded: boolean; hasDetail: boolean }>()
const emit = defineEmits<{
  toggle: []
  dimensions: [size: { width: number; height: number }]
  collapsed: []
}>()
const content = ref<HTMLElement | null>(null)
const contentHeight = ref(300)
const progress = ref(0)
const spring = useSpring(0, { stiffness: 230, damping: 32, mass: 1 })
const width = computed(() => 320 + 60 * progress.value)
const height = computed(() => 44 + (contentHeight.value - 44) * progress.value)
const publish = () => emit('dimensions', { width: width.value, height: height.value })
useMotionValueEvent(spring, 'change', value => {
  progress.value = Math.max(0, Math.min(1, value))
  publish()
})
useMotionValueEvent(spring, 'animationComplete', () => {
  if (!props.expanded) emit('collapsed')
})
const measure = () => {
  if (content.value && props.hasDetail) contentHeight.value = Math.max(44, content.value.offsetHeight)
  publish()
}
watch(() => props.expanded, async expanded => {
  await nextTick()
  measure()
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
    spring.jump(expanded ? 1 : 0)
    progress.value = expanded ? 1 : 0
    publish()
    if (!expanded) emit('collapsed')
  } else spring.set(expanded ? 1 : 0)
}, { immediate: true })
watch(() => props.hasDetail, () => nextTick(measure))
let observer: ResizeObserver | undefined
onMounted(() => {
  observer = new ResizeObserver(measure)
  if (content.value) observer.observe(content.value)
  measure()
})
onBeforeUnmount(() => { observer?.disconnect(); spring.stop() })
</script>

<template>
  <div class="execution-node" :class="[{ 'is-open': progress > 0.01 }, status]"
    :style="{ width: `${width}px`, height: `${height}px`, borderRadius: `${22 - 6 * progress}px` }">
    <Handle type="target" :position="Position.Left" :connectable="false" />
    <button class="execution-node__capsule" type="button" :title="name" :aria-label="`${name} · ${statusLabel}`"
      :tabindex="hasDetail ? -1 : 0" :aria-hidden="hasDetail"
      :aria-expanded="expanded" :style="{ opacity: Math.max(0, 1 - progress * 5), pointerEvents: progress > 0.01 ? 'none' : 'auto' }"
      @click.stop="emit('toggle')">
      <strong>{{ name }}</strong><span class="execution-node__status"><i v-if="status === 'running'" class="execution-node__activity" aria-hidden="true" />{{ statusLabel }}</span>
    </button>
    <div ref="content" class="execution-node__measure nodrag nowheel" :aria-hidden="!hasDetail" :style="{ visibility: hasDetail ? 'visible' : 'hidden' }">
      <motion.div :initial="false" :animate="{ opacity: expanded ? 1 : 0, y: expanded ? 0 : 6 }"
        :transition="{ duration: expanded ? 0.22 : 0.12, delay: expanded ? 0.06 : 0 }"
        :style="{ pointerEvents: expanded ? 'auto' : 'none' }">
        <slot />
      </motion.div>
    </div>
    <Handle type="source" :position="Position.Right" :connectable="false" />
  </div>
</template>

<style scoped>
/* 卡片底色在主题面上向文字色提亮一档，边框同步提亮：暗色画布上不再沉入背景。 */
.execution-node { position: relative; box-sizing: border-box; overflow: hidden; border: 1px solid color-mix(in srgb, var(--wb-text, #26332f) 18%, var(--wb-border, #64748b)); background: color-mix(in srgb, var(--wb-text, #26332f) 8%, var(--wb-surface-2, #e6edf2)); color: var(--wb-text, #26332f); box-shadow: 0 2px 7px #00000014; }
.execution-node.is-open { border-color: var(--wb-accent, #6ea8fe); background: var(--wb-surface-1, #fff); box-shadow: 0 10px 28px #00000026; }
.execution-node.running { border-color: var(--sem-running, #6ea8fe); background: color-mix(in srgb, var(--sem-running, #6ea8fe) 8%, var(--wb-surface-2, #e6edf2)); box-shadow: 0 0 0 2px color-mix(in srgb, var(--sem-running, #6ea8fe) 16%, transparent); }
.execution-node.completed { border-color: var(--sem-success, #8bcb78); }
.execution-node.failed { border-color: var(--sem-failed, #e06c75); }
.execution-node.waiting_review { border-color: var(--sem-waiting, #d9b86c); }
.execution-node.retrying { border-color: var(--sem-retry, #e69a62); }
.execution-node__capsule { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 320px; height: 44px; padding: 0 16px; border: 0; background: transparent; color: inherit; cursor: pointer; font: inherit; }
.execution-node__capsule strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; font-weight: 600; }
.execution-node__capsule span { flex-shrink: 0; color: var(--wb-text-secondary, #66736f); font-size: 11px; }
.execution-node__status { display: inline-flex; align-items: center; gap: 6px; }
.running .execution-node__status { color: var(--sem-running, #6ea8fe); font-weight: 600; }
.execution-node__activity { width: 6px; height: 6px; flex-shrink: 0; border-radius: 50%; background: currentColor; animation: execution-activity 1.6s ease-in-out infinite; }
@keyframes execution-activity { 50% { box-shadow: 0 0 0 4px color-mix(in srgb, currentColor 18%, transparent); } }
@media (prefers-reduced-motion: reduce) { .execution-node__activity { animation: none; } }
.execution-node__measure { position: absolute; top: 0; left: 0; width: 378px; }
.execution-node :deep(.vue-flow__handle) { width: 1px; height: 1px; min-width: 0; min-height: 0; opacity: 0; border: 0; pointer-events: none; }
.execution-node__capsule:focus-visible { outline: 2px solid var(--wb-accent, #6ea8fe); outline-offset: -4px; border-radius: 22px; }
</style>
