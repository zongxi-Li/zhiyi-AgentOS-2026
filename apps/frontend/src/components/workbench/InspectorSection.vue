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
.inspector-section { min-height: 0; padding: 15px 18px 16px; border: 1px solid var(--wb-border-soft); border-radius: 12px; background: var(--wb-surface-section); box-shadow: 0 1px 2px color-mix(in srgb, #000 24%, transparent), 0 5px 16px color-mix(in srgb, #000 18%, transparent); }
.inspector-section__heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 12px; color: var(--wb-text-secondary); font: 13px var(--font-sans, system-ui, sans-serif); letter-spacing: .02em; }
.inspector-section__heading strong { color: var(--wb-text-secondary); font: inherit; font-weight: 500; letter-spacing: .03em; }
.inspector-section__heading span { color: var(--wb-accent); font: 10px var(--font-mono, monospace); letter-spacing: .04em; text-transform: uppercase; }
</style>
