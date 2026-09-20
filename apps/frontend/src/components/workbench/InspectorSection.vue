<template>
  <section class="inspector-section">
    <div class="inspector-section__heading">
      <strong>{{ title }}</strong>
      <span v-if="badge" class="inspector-section__badge" :class="badgeClass">{{ badge }}</span>
    </div>
    <slot />
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { statusToneClass, type SemanticTone } from '@/utils/statusSemantic'

const props = defineProps<{
  title: string
  badge?: string | null
  /** 'status' derives the tone from the badge text; any SemanticTone pins it; 'accent' keeps the workbench accent. */
  badgeTone?: 'status' | 'accent' | SemanticTone
}>()

const badgeClass = computed(() => {
  const tone = props.badgeTone
  if (!tone || tone === 'accent') return ''
  if (tone === 'status') return statusToneClass(props.badge)
  return `tone-${tone}`
})
</script>

<style scoped>
.inspector-section { min-height: 0; padding: 13px 4px 14px; border: 0; border-radius: 0; background: transparent; box-shadow: none; }
.inspector-section__heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 9px; color: var(--wb-text-secondary); font: 12px var(--font-sans, system-ui, sans-serif); letter-spacing: .02em; }
.inspector-section__heading strong { color: var(--wb-text-secondary); font: inherit; font-weight: 600; letter-spacing: .02em; }
.inspector-section__badge, .inspector-section__heading span { display: inline-flex; align-items: center; min-height: 20px; padding: 2px 6px; border: 1px solid color-mix(in srgb, var(--wb-accent) 20%, var(--wb-border-soft)); border-radius: var(--wb-radius-sm); color: var(--wb-accent); background: color-mix(in srgb, var(--wb-accent-soft) 44%, transparent); font: 10px var(--font-mono, monospace); letter-spacing: .04em; text-transform: uppercase; }
.inspector-section__heading span.inspector-section__badge { color: var(--tone, var(--wb-accent)); border-color: color-mix(in srgb, var(--tone, var(--wb-accent)) 26%, var(--wb-border-soft)); background: color-mix(in srgb, var(--tone, var(--wb-accent)) 8%, transparent); }
</style>
