<template>
  <header class="workspace-page-hero">
    <div class="workspace-page-hero__copy">
      <span class="workspace-page-hero__eyebrow">{{ eyebrow }}</span>
      <h1>{{ title }}</h1>
      <p v-if="description">{{ description }}</p>
    </div>
    <div class="workspace-page-hero__actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<script setup lang="ts">
defineProps<{
  eyebrow: string
  title: string
  description?: string
}>()
</script>

<style scoped>
.workspace-page-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 30px 0 24px;
  border-bottom: 1px solid var(--border-light);
}

.workspace-page-hero__eyebrow {
  color: var(--primary-color);
  font: 10px var(--font-mono, monospace);
  letter-spacing: .12em;
}

.workspace-page-hero h1 {
  margin: 8px 0 5px;
  color: var(--text-primary);
  font: 650 clamp(26px, 2.4vw, 34px)/1.15 var(--font-serif, Georgia, serif);
}

.workspace-page-hero p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 12px;
}

.workspace-page-hero__actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

@media (max-width: 700px) {
  .workspace-page-hero {
    flex-direction: column;
    gap: 16px;
  }

  .workspace-page-hero__actions {
    width: 100%;
    flex-wrap: wrap;
  }
}
</style>
