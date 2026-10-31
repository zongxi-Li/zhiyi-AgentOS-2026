<template>
  <div ref="host" class="workspace-diff" aria-label="行内差异" />
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { EditorState } from '@codemirror/state'
import { EditorView, lineNumbers } from '@codemirror/view'
import { LanguageDescription, syntaxHighlighting } from '@codemirror/language'
import { unifiedMergeView } from '@codemirror/merge'
import { languages } from '@codemirror/language-data'
import { workbenchEditorTheme, workbenchHighlightStyle } from '@/workbench/editor/theme'

const props = defineProps<{
  /** HEAD 里的原始内容；新增文件传空串 */
  base: string
  /** 当前工作区内容 */
  current: string
  fileName: string
}>()

const host = ref<HTMLElement | null>(null)
let view: EditorView | null = null
let generation = 0

async function build(): Promise<void> {
  if (!host.value) return
  const token = ++generation
  const description = LanguageDescription.matchFilename(languages, props.fileName)
  const language = description ? await description.load() : []
  if (token !== generation || !host.value) return
  view?.destroy()
  view = new EditorView({
    parent: host.value,
    state: EditorState.create({
      doc: props.current,
      extensions: [
        lineNumbers(),
        workbenchEditorTheme,
        syntaxHighlighting(workbenchHighlightStyle),
        unifiedMergeView({
          original: props.base,
          mergeControls: false,
          gutter: true,
          highlightChanges: true,
          allowInlineDiffs: true,
          collapseUnchanged: { margin: 3, minSize: 4 }
        }),
        EditorState.readOnly.of(true),
        EditorView.editable.of(false),
        language
      ]
    })
  })
}

onMounted(() => void build())
watch(() => [props.base, props.current, props.fileName], () => void build())
onBeforeUnmount(() => {
  generation += 1
  view?.destroy()
  view = null
})
</script>

<style scoped>
.workspace-diff {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: transparent;
}
.workspace-diff :deep(.cm-editor) { height: 100%; }
.workspace-diff :deep(.cm-scroller) { overflow: auto; }
.workspace-diff :deep(.cm-deletedChunk) { background: color-mix(in srgb, var(--sem-failed) 9%, transparent); }
.workspace-diff :deep(.cm-deletedText) { background: color-mix(in srgb, var(--sem-failed) 22%, transparent); }
.workspace-diff :deep(.cm-changedLine), .workspace-diff :deep(.cm-inlineChangedLine) {
  background: color-mix(in srgb, var(--sem-success) 9%, transparent);
}
.workspace-diff :deep(.cm-changedText) { background: color-mix(in srgb, var(--sem-success) 26%, transparent); }
.workspace-diff :deep(.cm-insertedLine) { color: var(--sem-success); }
.workspace-diff :deep(.cm-collapsedLines) { color: var(--wb-text-muted); font: 11px var(--font-mono, monospace); }
.workspace-diff :deep(.cm-changedLineGutter) { color: var(--sem-success); }
.workspace-diff :deep(.cm-deletedLineGutter) { color: var(--sem-failed); }
</style>
