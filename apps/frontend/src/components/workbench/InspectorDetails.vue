<template>
  <details class="inspector-details" :class="{ 'inspector-details--text': textToggle }" :open="open || undefined">
    <summary>
      <span class="inspector-details__caret" aria-hidden="true">
        <svg width="10" height="10" viewBox="0 0 10 10"><path d="M3.5 2 L7 5 L3.5 8" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
      </span>
      <span>{{ title }}</span>
      <span v-if="count != null" class="inspector-details__count">{{ count }}</span>
      <span v-if="textToggle" class="inspector-details__action" aria-hidden="true">
        <span>展开</span><span>收起</span>
      </span>
    </summary>
    <div class="inspector-details__body"><p v-if="description" class="inspector-details__description">{{ description }}</p><slot /></div>
  </details>
</template>

<script setup lang="ts">
defineProps<{ title: string; description?: string; count?: number; open?: boolean; textToggle?: boolean }>()
</script>

<style scoped>
.inspector-details { min-width: 0; margin-top: 12px; }
.inspector-details > summary { display: flex; align-items: center; gap: 8px; min-height: 38px; color: var(--wb-text-secondary); cursor: pointer; list-style: none; font: 500 12px/1.5 var(--font-sans, sans-serif); }
.inspector-details > summary::-webkit-details-marker { display: none; }
/* 折叠键帽：凸起小圆钮收住尖角，展开旋转朝下并染强调色 */
.inspector-details__caret { display: grid; place-items: center; width: 20px; height: 20px; flex: none; border-radius: 50%; color: var(--wb-text-muted); background: var(--wb-surface-inset); box-shadow: 2px 2px 4px color-mix(in srgb, #000 32%, transparent), -2px -2px 4px color-mix(in srgb, #fff 4.5%, transparent); transition: color 160ms ease; }
.inspector-details__caret svg { transition: transform 180ms ease; }
.inspector-details[open] > summary .inspector-details__caret { color: var(--wb-accent); }
.inspector-details[open] > summary .inspector-details__caret svg { transform: rotate(90deg); }
.inspector-details > summary:hover { color: var(--wb-text); }
.inspector-details > summary:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: 2px; border-radius: 4px; }
.inspector-details__count { margin-left: auto; color: var(--wb-text-muted); font-variant-numeric: tabular-nums; }
.inspector-details__body { min-width: 0; padding: 0 0 8px 14px; }
.inspector-details__description { margin: 0 0 10px; color: var(--wb-text-muted); font-size: 12px; line-height: 1.65; }
.inspector-details--text { margin-top: 0; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-md); background: var(--wb-surface-inset); }
.inspector-details--text > summary { padding: 0 10px; border-radius: inherit; }
.inspector-details--text > summary:hover { background: var(--wb-hover); }
.inspector-details--text .inspector-details__caret { display: none; }
.inspector-details--text > .inspector-details__body { padding: 0 10px 10px; }
.inspector-details__action { flex: none; margin-left: auto; padding: 1px 6px; border-radius: var(--wb-radius-sm); background: var(--wb-hover); font-size: 10px; }
.inspector-details__count + .inspector-details__action { margin-left: 0; }
.inspector-details:not([open]) > summary .inspector-details__action > :last-child,
.inspector-details[open] > summary .inspector-details__action > :first-child { display: none; }
.inspector-details[open] > summary .inspector-details__action { color: var(--wb-accent); background: var(--wb-accent-soft); }
</style>
