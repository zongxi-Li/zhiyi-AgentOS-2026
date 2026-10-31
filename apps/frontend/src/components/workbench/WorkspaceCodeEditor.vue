<template>
  <div ref="host" class="workbench-code-editor" :class="{ 'is-readonly': readOnly }" />
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Annotation, Compartment, EditorState } from '@codemirror/state'
import {
  EditorView,
  crosshairCursor,
  drawSelection,
  dropCursor,
  highlightActiveLine,
  highlightActiveLineGutter,
  keymap,
  lineNumbers,
  rectangularSelection
} from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import {
  LanguageDescription,
  bracketMatching,
  codeFolding,
  foldGutter,
  foldKeymap,
  indentOnInput,
  syntaxHighlighting
} from '@codemirror/language'
import { highlightSelectionMatches, search, searchKeymap } from '@codemirror/search'
import { closeBrackets, closeBracketsKeymap } from '@codemirror/autocomplete'
import { forceLinting } from '@codemirror/lint'
import { languages } from '@codemirror/language-data'
import type { TextDocument } from '@/workbench/core/documents'
import { registerReveal } from '@/workbench/core/reveal'
import { lspAvailable, lspClose, lspDiagnostics, lspOpen } from '@/services/lsp'
import { lspExtension } from '@/workbench/editor/lsp'
import type { LspLocationItem } from '@/services/lsp'
import { workbenchEditorTheme, workbenchHighlightStyle } from '@/workbench/editor/theme'

const props = withDefaults(defineProps<{
  document: TextDocument
  fileName: string
  filePath: string
  workspaceRoot: string
  readOnly?: boolean
}>(), { readOnly: false })

const emit = defineEmits<{
  (event: 'save'): void
  (event: 'cursor', position: { line: number; column: number }): void
  (event: 'definition', location: LspLocationItem): void
}>()

const host = ref<HTMLElement | null>(null)
// 外部（Agent / 重新读取）推来的变更打标记，避免 updateListener 再写回文档一次。
const externalChange = Annotation.define<boolean>()
const origin = Symbol('workbench-editor')
const readOnlyCompartment = new Compartment()
const languageCompartment = new Compartment()

let view: EditorView | null = null
let unsubscribe: (() => void) | null = null
let unsubscribeReveal: (() => void) | null = null
let languageRequest = 0
let diagnosticsTimer: number | undefined
let diagnosticsSignature = ''

const readOnlyExtensions = (readOnly: boolean) => [
  EditorState.readOnly.of(readOnly),
  EditorView.editable.of(!readOnly)
]

const emitCursor = (state: EditorState): void => {
  const head = state.selection.main.head
  const line = state.doc.lineAt(head)
  emit('cursor', { line: line.number, column: head - line.from + 1 })
}

const handleUpdate = (update: import('@codemirror/view').ViewUpdate): void => {
  if (update.docChanged && !update.transactions.some(transaction => transaction.annotation(externalChange))) {
    const edits: Array<{ from: number; to: number; insert: string }> = []
    update.changes.iterChanges((fromA, toA, _fromB, _toB, inserted) => {
      edits.push({ from: fromA, to: toA, insert: inserted.toString() })
    })
    const applied = props.document.applyEdits(edits, origin)
    // 编辑器是唯一写入方时文档与视图一致；若文档拒绝（内容未变）则无需处理。
    if (!applied) return
  }
  if (update.docChanged || update.selectionSet) emitCursor(update.state)
}

const baseExtensions = () => [
  lineNumbers(),
  highlightActiveLineGutter(),
  highlightActiveLine(),
  foldGutter(),
  codeFolding(),
  history(),
  drawSelection(),
  dropCursor(),
  rectangularSelection(),
  crosshairCursor(),
  EditorState.allowMultipleSelections.of(true),
  EditorState.tabSize.of(4),
  indentOnInput(),
  bracketMatching(),
  closeBrackets(),
  highlightSelectionMatches(),
  search({ top: true }),
  syntaxHighlighting(workbenchHighlightStyle),
  workbenchEditorTheme,
  ...(lspAvailable()
    ? lspExtension({
        root: props.workspaceRoot,
        path: props.filePath,
        onDefinition: location => emit('definition', location)
      })
    : []),
  EditorView.contentAttributes.of({ 'aria-label': '文件内容', spellcheck: 'false', autocapitalize: 'off' }),
  readOnlyCompartment.of(readOnlyExtensions(props.readOnly)),
  languageCompartment.of([]),
  keymap.of([
    {
      key: 'Mod-s',
      preventDefault: true,
      run: () => { emit('save'); return true }
    },
    ...closeBracketsKeymap,
    ...defaultKeymap,
    ...searchKeymap,
    ...foldKeymap,
    ...historyKeymap,
    indentWithTab
  ]),
  EditorView.updateListener.of(handleUpdate)
]

async function applyLanguage(): Promise<void> {
  const request = ++languageRequest
  const description = LanguageDescription.matchFilename(languages, props.fileName)
  if (!description) return
  const support = await description.load()
  if (!view || request !== languageRequest) return
  view.dispatch({ effects: languageCompartment.reconfigure(support) })
}

onMounted(() => {
  if (!host.value) return
  view = new EditorView({
    state: EditorState.create({ doc: props.document.getText(), extensions: baseExtensions() }),
    parent: host.value
  })
  unsubscribe = props.document.onDidChange(event => {
    if (!view || event.origin === origin) return
    view.dispatch({
      changes: event.changes.map(change => ({ from: change.from, to: change.to, insert: change.insert })),
      annotations: externalChange.of(true)
    })
  })
  // 搜索/诊断结果点击后定位到行；未挂载时的请求由 reveal 模块暂存。
  unsubscribeReveal = registerReveal(props.filePath, line => {
    if (!view) return
    const target = Math.min(Math.max(line, 1), view.state.doc.lines)
    const anchor = view.state.doc.line(target).from
    view.dispatch({
      selection: { anchor },
      effects: EditorView.scrollIntoView(anchor, { y: 'center' })
    })
    view.focus()
  })
  void applyLanguage()
  emitCursor(view.state)
  // 只有可见的编辑器才抢焦点：EditorGroup 会把所有打开的文件都保持挂载。
  if (host.value?.offsetParent !== null) view.focus()
  if (lspAvailable()) {
    void lspOpen(props.workspaceRoot, props.filePath, props.document.getText())
      .then(result => {
        if (!result.languageId || !view) return
        forceLinting(view)
        startDiagnosticsPolling()
      })
      .catch(() => undefined)
  }
})

/** 语言服务的诊断是异步的：轮询比对签名，有新结果就让 linter 重新取一次。 */
function startDiagnosticsPolling(): void {
  window.clearInterval(diagnosticsTimer)
  diagnosticsTimer = window.setInterval(async () => {
    if (!view) return
    const items = await lspDiagnostics(props.workspaceRoot).catch(() => [])
    const signature = JSON.stringify(items.filter(item => item.path === props.filePath))
    if (signature === diagnosticsSignature) return
    diagnosticsSignature = signature
    if (view) forceLinting(view)
  }, 2500)
}

watch(() => props.readOnly, value => {
  view?.dispatch({ effects: readOnlyCompartment.reconfigure(readOnlyExtensions(value)) })
})

onBeforeUnmount(() => {
  unsubscribe?.()
  unsubscribe = null
  unsubscribeReveal?.()
  unsubscribeReveal = null
  window.clearInterval(diagnosticsTimer)
  diagnosticsTimer = undefined
  languageRequest += 1
  view?.destroy()
  view = null
  if (lspAvailable()) void lspClose(props.workspaceRoot, props.filePath).catch(() => undefined)
})

defineExpose({ focus: () => view?.focus() })
</script>

<style scoped>
.workbench-code-editor {
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: transparent;
}
.workbench-code-editor :deep(.cm-editor) {
  height: 100%;
}
.workbench-code-editor :deep(.cm-scroller) {
  overflow: auto;
}
</style>
