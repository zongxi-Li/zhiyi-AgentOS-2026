<template>
  <div ref="host" class="mission-markdown-editor" :class="{ 'is-readonly': readOnly }" />
</template>

<script setup lang="ts">
// 任务说明的文档编辑器：CodeMirror + markdown 语法（经 language-data 懒加载，
// 与 WorkspaceCodeEditor 同一条语言加载路径，避免直连 transitive 依赖）。
// 草稿只存在于本地（v-model），保存链路接入后端前不发生任何写回。
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Annotation, Compartment, EditorState } from '@codemirror/state'
import {
  EditorView,
  drawSelection,
  dropCursor,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
  placeholder
} from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { LanguageDescription, syntaxHighlighting } from '@codemirror/language'
import { languages } from '@codemirror/language-data'
import { workbenchEditorTheme, workbenchHighlightStyle } from '@/workbench/editor/theme'

const props = withDefaults(defineProps<{
  modelValue: string
  readOnly?: boolean
  ariaLabel?: string
}>(), { readOnly: false, ariaLabel: '任务说明 Markdown 源文' })

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const host = ref<HTMLElement | null>(null)
// 外部（投影刷新）推来的内容打标记，避免 updateListener 再向父级回写一次。
const externalChange = Annotation.define<boolean>()
const readOnlyCompartment = new Compartment()
const languageCompartment = new Compartment()
let view: EditorView | null = null
let languageRequest = 0

const readOnlyExtensions = (readOnly: boolean) => [
  EditorState.readOnly.of(readOnly),
  EditorView.editable.of(!readOnly)
]

const handleUpdate = (update: import('@codemirror/view').ViewUpdate) => {
  if (!update.docChanged) return
  if (update.transactions.some(transaction => transaction.annotation(externalChange))) return
  emit('update:modelValue', update.state.doc.toString())
}

// 文档卡片内的编辑器：高度随内容增长，滚动交给外层 mission-editor 卡片。
const documentTheme = EditorView.theme({
  '&': { height: 'auto', minWidth: 0 },
  '.cm-scroller': { overflow: 'visible' },
  '.cm-content': { paddingBottom: '22px' }
})

const baseExtensions = () => [
  lineNumbers(),
  highlightActiveLineGutter(),
  highlightActiveLine(),
  history(),
  drawSelection(),
  dropCursor(),
  EditorView.lineWrapping,
  placeholder('任务说明…'),
  syntaxHighlighting(workbenchHighlightStyle),
  workbenchEditorTheme,
  documentTheme,
  EditorView.contentAttributes.of({ 'aria-label': props.ariaLabel, spellcheck: 'false', autocapitalize: 'off' }),
  readOnlyCompartment.of(readOnlyExtensions(props.readOnly)),
  languageCompartment.of([]),
  keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
  EditorView.updateListener.of(handleUpdate)
]

async function applyLanguage(): Promise<void> {
  const request = ++languageRequest
  const description = LanguageDescription.matchFilename(languages, 'mission.md')
  if (!description) return
  const support = await description.load()
  if (!view || request !== languageRequest) return
  view.dispatch({ effects: languageCompartment.reconfigure(support) })
}

onMounted(() => {
  if (!host.value) return
  view = new EditorView({
    state: EditorState.create({ doc: props.modelValue, extensions: baseExtensions() }),
    parent: host.value
  })
  // 只有可见的编辑器才抢焦点（mission.md 与其他文档可能同屏保活）。
  if (host.value.offsetParent !== null) view.focus()
  void applyLanguage()
})

watch(() => props.modelValue, value => {
  if (!view || value === view.state.doc.toString()) return
  view.dispatch({
    changes: { from: 0, to: view.state.doc.length, insert: value },
    annotations: externalChange.of(true)
  })
})

watch(() => props.readOnly, value => {
  view?.dispatch({ effects: readOnlyCompartment.reconfigure(readOnlyExtensions(value)) })
})

onBeforeUnmount(() => {
  view?.destroy()
  view = null
})

defineExpose({ focus: () => view?.focus() })
</script>

<style scoped>
/* 贴边编辑器面板：无边框无圆角，CodeMirror 直接铺满所在区域（gutter 起于面板左缘）。 */
.mission-markdown-editor {
  min-width: 0;
  overflow: hidden;
  background: transparent;
}

.mission-markdown-editor :deep(.cm-editor) { min-width: 0; }
.mission-markdown-editor :deep(.cm-editor.cm-focused) { outline: none; }
.mission-markdown-editor.is-readonly :deep(.cm-content) { color: var(--wb-text-secondary); }
</style>
