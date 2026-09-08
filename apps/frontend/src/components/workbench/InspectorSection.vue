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
.inspector-section { min-height: 0; padding: 14px 4px 15px; border: 0; border-bottom: 1px solid var(--wb-border-soft); border-radius: 0; background: transparent; box-shadow: none; }
.inspector-section__heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; color: var(--wb-text-secondary); font: 12px var(--font-sans, system-ui, sans-serif); letter-spacing: .02em; }
.inspector-section__heading strong { color: var(--wb-text-secondary); font: inherit; font-weight: 500; letter-spacing: .03em; }
.inspector-section__heading span { color: var(--wb-accent); font: 10px var(--font-mono, monospace); letter-spacing: .04em; text-transform: uppercase; }
</style>
