<template>
  <component
    :is="tag"
    class="editor-object-row"
    :class="{
      'is-selected': selected,
      'is-interactive': interactive,
      'has-meta': hasMeta
    }"
    :style="{ '--editor-object-depth': depth }"
    v-bind="$attrs"
  >
    <div class="editor-object-row__gutter">
      <slot name="gutter">
        <span v-if="index != null" class="editor-object-row__index">{{ index }}</span>
      </slot>
    </div>
    <div class="editor-object-row__content">
      <slot />
    </div>
    <div v-if="hasMeta" class="editor-object-row__meta">
      <slot name="meta" />
    </div>
  </component>
</template>

<script setup lang="ts">
import { computed, useSlots } from 'vue'

defineOptions({ inheritAttrs: false })

const props = withDefaults(defineProps<{
  tag?: 'div' | 'article'
  depth?: number
  index?: string | number | null
  selected?: boolean
  interactive?: boolean
}>(), {
  tag: 'div',
  depth: 0,
  index: null,
  selected: false,
  interactive: false
})

const slots = useSlots()
const hasMeta = computed(() => Boolean(slots.meta))
</script>

<style scoped>
.editor-object-row {
  --editor-object-indent: calc(var(--editor-object-depth, 0) * 20px);
  position: relative;
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) auto;
  align-items: center;
  min-width: 0;
  min-height: 30px;
  padding: 2px 0 2px var(--editor-object-indent);
  color: var(--wb-text);
  transition: background-color 140ms var(--ease-out), box-shadow 140ms var(--ease-out);
}
.editor-object-row__gutter {
  display: flex;
  align-items: center;
  align-self: stretch;
  justify-content: flex-start;
  min-width: 0;
  color: var(--wb-text-muted);
}
.editor-object-row__index {
  width: 32px;
  color: var(--wb-accent);
  font: 10px var(--font-mono, monospace);
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.editor-object-row__content { min-width: 0; }
.editor-object-row__meta {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  min-width: 0;
  padding-left: 12px;
}
.editor-object-row.is-interactive { cursor: pointer; }
.editor-object-row.is-interactive:hover { background: color-mix(in srgb, var(--wb-hover) 42%, transparent); }
.editor-object-row.is-selected {
  background: color-mix(in srgb, var(--wb-selected) 42%, var(--wb-surface-shell));
  box-shadow: inset 2px 0 color-mix(in srgb, var(--wb-accent) 62%, transparent);
}
.editor-object-row.is-interactive:focus-visible {
  outline: 1px solid var(--wb-accent);
  outline-offset: -1px;
}

@media (max-width: 720px) {
  .editor-object-row { grid-template-columns: 36px minmax(0, 1fr) auto; }
  .editor-object-row__meta { padding-left: 7px; }
}
</style>
