<template>
  <section class="problems-panel" aria-label="Problems">
    <div v-if="!diagnostics.length" class="problems-panel__empty">
      <span class="problems-panel__empty-mark" aria-hidden="true">✓</span>
      <strong>没有问题</strong>
      <span>当前 Mission Projection 未报告诊断问题。</span>
    </div>
    <div v-else class="problems-panel__list">
      <article v-for="diagnostic in diagnostics" :key="`${diagnostic.code}-${diagnostic.message}`" class="problems-panel__item">
        <span class="problems-panel__severity" :class="`is-${diagnostic.severity}`" aria-hidden="true">!</span>
        <div>
          <strong>{{ diagnostic.code }}</strong>
          <p>{{ diagnostic.message }}</p>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { WorkspaceDiagnostic } from '@/services/api/agentos'

defineProps<{
  diagnostics: readonly WorkspaceDiagnostic[]
}>()
</script>

<style scoped>
.problems-panel { min-height: 100%; color: var(--text-secondary); background: var(--bg-card); }
.problems-panel__empty { display: grid; justify-items: center; gap: 5px; padding: 24px 16px; color: var(--text-muted); font-size: 11px; text-align: center; }
.problems-panel__empty strong { color: var(--text-primary); font-size: 12px; }
.problems-panel__empty-mark { display: inline-grid; place-items: center; width: 21px; height: 21px; border: 1px solid color-mix(in srgb, var(--success) 40%, var(--border-light)); border-radius: 50%; color: var(--success); font-size: 12px; }
.problems-panel__list { display: grid; align-content: start; }
.problems-panel__item { display: grid; grid-template-columns: 20px minmax(0, 1fr); gap: 8px; padding: 10px 14px; border-bottom: 1px solid var(--border-light); }
.problems-panel__severity { display: inline-grid; place-items: center; width: 17px; height: 17px; border-radius: 50%; color: var(--bg-card); background: var(--warning); font: 11px var(--font-mono, monospace); font-weight: 700; }
.problems-panel__severity.is-info { background: var(--primary-color); }
.problems-panel__item strong { color: var(--text-primary); font: 10px var(--font-mono, monospace); }
.problems-panel__item p { margin: 4px 0 0; color: var(--text-secondary); font-size: 11px; line-height: 1.45; overflow-wrap: anywhere; }
</style>
