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
.inspector-section { min-height: 0; padding: 12px 14px 14px; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-section); background: var(--wb-surface-section); box-shadow: var(--wb-shadow-section); }
.inspector-section__heading { display: flex; justify-content: space-between; gap: 10px; margin-bottom: 10px; color: var(--wb-text-muted); font: 10px var(--font-mono, monospace); letter-spacing: .1em; text-transform: uppercase; }
.inspector-section__heading strong { color: var(--wb-text-secondary); font: 10px var(--font-mono, monospace); letter-spacing: .1em; text-transform: uppercase; }
.inspector-section__heading span { color: var(--wb-accent); letter-spacing: 0; }
</style>
