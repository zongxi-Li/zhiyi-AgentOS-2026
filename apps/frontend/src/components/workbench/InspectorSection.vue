<template>
  <section class="inspector-section">
    <div class="inspector-section__heading">
      <strong>{{ title }}</strong>
      <span v-if="badge">{{ badge }}</span>
    </div>
    <slot />
  </section>
</template>

<script setup lang="ts">
defineProps<{
  title: string
  badge?: string | null
}>()
</script>

<style scoped>
.inspector-section { min-height: 0; padding: 13px 4px 14px; border: 0; border-bottom: 1px solid var(--wb-border-soft); border-radius: 0; background: transparent; box-shadow: none; }
.inspector-section__heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 9px; color: var(--wb-text-secondary); font: 12px var(--font-sans, system-ui, sans-serif); letter-spacing: .02em; }
.inspector-section__heading strong { color: var(--wb-text-secondary); font: inherit; font-weight: 600; letter-spacing: .02em; }
.inspector-section__heading span { display: inline-flex; align-items: center; min-height: 20px; padding: 2px 6px; border: 1px solid color-mix(in srgb, var(--wb-accent) 20%, var(--wb-border-soft)); border-radius: var(--wb-radius-sm); color: var(--wb-accent); background: color-mix(in srgb, var(--wb-accent-soft) 44%, transparent); font: 10px var(--font-mono, monospace); letter-spacing: .04em; text-transform: uppercase; }
</style>
