<template>
  <article class="mission-editor editor-document" aria-label="mission.md">
    <header class="editor-document__header">
      <div>
        <span class="editor-document__eyebrow">VIRTUAL DOCUMENT</span>
        <h1>mission.md</h1>
        <p>Mission brief · read-only projection</p>
      </div>
      <code>{{ projection.mission.missionId }}</code>
    </header>

    <div class="editor-document__body markdown-body" v-html="renderedContent" />

    <section class="mission-editor__meta" aria-label="Mission metadata">
      <div class="property-row"><span>status</span><code>{{ projection.mission.status }}</code></div>
      <div v-if="projection.activeRun" class="property-row"><span>active Run</span><code>{{ projection.activeRun.runId }}</code></div>
      <div v-if="projection.activeRun" class="property-row"><span>Run status</span><code>{{ projection.activeRun.status }}</code></div>
    </section>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '@/utils/markdown'
import type { MissionWorkspaceProjection, WorkspaceEntry } from '@/services/api/agentos'

const props = defineProps<{
  projection: MissionWorkspaceProjection
  entry: WorkspaceEntry
}>()

const renderedContent = computed(() => {
  const source = props.entry.content || `# ${props.projection.mission.goal}`
  return renderMarkdown(source)
})
</script>

<style scoped>
.mission-editor {
  flex: 1 1 auto;
  height: 100%;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  padding: 34px clamp(24px, 6vw, 92px) 56px;
  color: var(--text-primary);
}

.editor-document__header {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  padding-bottom: 22px;
  border-bottom: 1px solid var(--border-light);
}

.editor-document__header h1 { max-width: 820px; margin: 7px 0 4px; font-size: 19px; line-height: 1.3; text-wrap: pretty; overflow-wrap: anywhere; }
.editor-document__header p { margin: 0; color: var(--text-secondary); font-size: 12px; }
.editor-document__header code { align-self: flex-start; max-width: 220px; overflow: hidden; color: var(--text-muted); font: 10px var(--font-mono, monospace); text-overflow: ellipsis; white-space: nowrap; }
.editor-document__eyebrow { color: var(--primary-color); font: 10px var(--font-mono, monospace); letter-spacing: .08em; }

.editor-document__body { width: min(100%, 820px); padding-top: 24px; }
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3) { color: var(--text-primary); line-height: 1.35; text-wrap: pretty; }
.markdown-body :deep(h1) { margin: 0 0 18px; font-size: 25px; }
.markdown-body :deep(h2) { margin: 28px 0 10px; padding-bottom: 6px; border-bottom: 1px solid var(--border-light); font-size: 17px; }
.markdown-body :deep(h3) { margin: 20px 0 8px; font-size: 14px; }
.markdown-body :deep(p),
.markdown-body :deep(li) { color: var(--text-secondary); font-size: 13px; line-height: 1.75; overflow-wrap: anywhere; }
.markdown-body :deep(ul),
.markdown-body :deep(ol) { padding-left: 23px; }
.markdown-body :deep(code) { padding: 2px 4px; color: var(--text-primary); background: var(--bg-input); font: 11px var(--font-mono, monospace); }
.markdown-body :deep(pre) { overflow: auto; padding: 12px; border: 1px solid var(--border-light); background: var(--bg-input); }
.markdown-body :deep(pre code) { padding: 0; background: transparent; }
.markdown-body :deep(blockquote) { margin: 12px 0; padding-left: 12px; border-left: 2px solid var(--primary-color); color: var(--text-secondary); }
.markdown-body :deep(a) { color: var(--primary-color); }

.mission-editor__meta { width: min(100%, 820px); margin-top: 30px; padding-top: 14px; border-top: 1px solid var(--border-light); }
.property-row { display: flex; justify-content: space-between; gap: 24px; min-height: 30px; padding: 7px 0; border-bottom: 1px solid color-mix(in srgb, var(--border-light) 70%, transparent); color: var(--text-secondary); font-size: 12px; }
.property-row code { color: var(--text-primary); font: 11px var(--font-mono, monospace); }
</style>
