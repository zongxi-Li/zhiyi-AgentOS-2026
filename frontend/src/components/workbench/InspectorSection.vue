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
.inspector-section { min-height: 0; padding: 14px 15px; }
.inspector-section__heading { display: flex; justify-content: space-between; gap: 10px; margin-bottom: 10px; color: var(--text-secondary); font: 10px var(--font-mono, monospace); text-transform: uppercase; }
.inspector-section__heading strong { color: var(--text-primary); font: 12px var(--font-sans, sans-serif); text-transform: none; }
</style>
