<template>
  <section class="file-editor" :aria-label="request.relativePath">
    <header class="file-editor__toolbar">
      <span class="file-editor__path" :title="request.workspaceRoot + '/' + request.relativePath">{{ request.relativePath }}</span>
      <span v-if="dirty" class="file-editor__dirty">未保存</span>
      <button type="button" :disabled="loading || saving" @click="reload">重新读取</button>
      <button type="button" :disabled="!dirty || !version || loading || saving" title="保存到工作区（Ctrl+S）" @click="save">{{ saving ? '保存中…' : '保存' }}</button>
    </header>
    <p v-if="loading" role="status">正在读取文件…</p>
    <div v-if="error" class="file-editor__error" role="alert">{{ error }} <button v-if="!loaded" type="button" @click="load">重试</button></div>
    <div v-if="loaded" class="file-editor__body">
      <pre ref="gutter" class="file-editor__lines" aria-hidden="true">{{ lineNumbers }}</pre>
      <div class="file-editor__code">
        <pre v-show="showHighlight" ref="highlightLayer" class="file-editor__highlight" aria-hidden="true"><code v-html="highlighted"></code></pre>
        <textarea ref="input" v-model="content" class="file-editor__input" :class="{ 'is-highlighted': showHighlight }" aria-label="文件内容" spellcheck="false" autocapitalize="off" autocomplete="off" :readonly="saving || !version"
          @keydown.ctrl.s.prevent="save" @keydown.meta.s.prevent="save" @keydown.tab.prevent="indent" @scroll="syncScroll" @click="updateCursor" @keyup="updateCursor"
          @compositionstart="composing = true" @compositionend="composing = false" />
      </div>
    </div>
  </section>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { getElectronBridge } from '@/platform/electron/bridge'
import { agentosApi, type WorkspaceFileOpenRequest } from '@/services/api/agentos'
import { highlightCode } from '@/utils/syntaxHighlight'
// 文件元信息不在编辑器内占一行，而是上报给窗口底部状态栏（VS Code 式）显示。
export interface WorkspaceFileEditorStatus {
  /** 后端是否支持版本保护保存；false 时状态栏展示只读标记。 */
  editable: boolean
  language: string
  lines: number
  cursor: string
}
const props = defineProps<{request: WorkspaceFileOpenRequest}>()
const emit = defineEmits<{'dirty-change': [dirty: boolean], 'status-change': [status: WorkspaceFileEditorStatus]}>()
const content = ref(''), original = ref(''), version = ref<string | null>(null)
const error = ref(''), loading = ref(false), saving = ref(false), loaded = ref(false)
const input = ref<HTMLTextAreaElement>(), gutter = ref<HTMLElement>(), highlightLayer = ref<HTMLElement>(), cursor = ref('行 1，列 1')
const highlighted = ref(''), composing = ref(false)
const dirty = computed(() => content.value !== original.value)
const lines = computed(() => content.value.split('\n').length)
const lineNumbers = computed(() => Array.from({length: lines.value}, (_, i) => i + 1).join('\n'))
const language = computed(() => props.request.name.split('.').pop()?.toUpperCase() || 'TEXT')
const status = computed<WorkspaceFileEditorStatus>(() => ({editable: Boolean(version.value), language: language.value, lines: lines.value, cursor: cursor.value}))
// 输入法组合期间先把着色层让出来：否则被透明的原生输入框会把候选文字一起藏掉。
const showHighlight = computed(() => Boolean(highlighted.value) && !composing.value)
watch(dirty, value => emit('dirty-change', value), {immediate: true})
watch(status, value => emit('status-change', value), {immediate: true})
watch(showHighlight, () => void nextTick(syncScroll))
let controller: AbortController | undefined
let highlightToken = 0, highlightTimer: number | undefined
const message = (cause: any) => cause?.response?.data?.detail || cause?.response?.data?.message || cause?.message || '操作失败，请检查工作区服务'
async function load() {
  controller?.abort()
  const pending = new AbortController()
  controller = pending; loading.value = true; error.value = ''
  try {
    const native = getElectronBridge()?.workspace
    const file = props.request.desktopWorkspaceId && native
      ? await native.read(props.request.desktopWorkspaceId, props.request.relativePath)
      : await agentosApi.readWorkspaceFile(props.request.missionId, props.request.relativePath, {signal: pending.signal})
    if (controller !== pending || pending.signal.aborted) return
    const changed = file.content !== content.value
    content.value = original.value = file.content
    version.value = file.version || null
    highlighted.value = ''
    loaded.value = true
    // 重新读取到相同内容时 content watcher 不会触发，这里补一次着色，避免颜色丢失。
    if (!changed) scheduleHighlight(0)
  } catch (cause) { if (!pending.signal.aborted) error.value = message(cause) }
  finally { if (controller === pending) loading.value = false }
}
function reload() {
  if (!dirty.value || window.confirm('重新读取将放弃尚未保存的修改，是否继续？')) void load()
}
async function save() {
  if (!dirty.value || !version.value || loading.value || saving.value) return
  saving.value = true; error.value = ''
  const saved = content.value
  try {
    const native = getElectronBridge()?.workspace
    const result = props.request.desktopWorkspaceId && native
      ? await native.save(props.request.desktopWorkspaceId, props.request.relativePath, saved, version.value)
      : await agentosApi.saveWorkspaceFile(props.request.missionId, {
          path: props.request.relativePath, content: saved, expectedVersion: version.value, operationId: crypto.randomUUID()})
    original.value = saved; version.value = result.version || null
  } catch (cause: any) {
    error.value = (cause?.response?.status === 409 || message(cause).includes('FILE_CONFLICT')) ? '磁盘文件已变化，未覆盖。请复制当前修改，重新读取后再合并。' : `${message(cause)}。未自动重试；请重新读取磁盘确认保存结果。`
  } finally { saving.value = false }
}
// 着色只是阅读辅助：延迟重算并丢弃过期结果，输入时不会阻塞原生编辑与保存。
function scheduleHighlight(delay = 60) {
  window.clearTimeout(highlightTimer)
  const token = ++highlightToken
  const code = content.value, name = props.request.name
  const apply = async () => {
    const html = await highlightCode(code, name)
    if (token !== highlightToken) return
    highlighted.value = html || ''
    await nextTick()
    syncScroll()
  }
  if (delay > 0) highlightTimer = window.setTimeout(() => void apply(), delay)
  else void apply()
}
function syncScroll() {
  const element = input.value
  if (!element) return
  if (gutter.value) gutter.value.scrollTop = element.scrollTop
  if (highlightLayer.value) {
    highlightLayer.value.scrollTop = element.scrollTop
    highlightLayer.value.scrollLeft = element.scrollLeft
  }
}
function updateCursor() {
  const prefix = content.value.slice(0, input.value?.selectionStart || 0).split('\n')
  cursor.value = `行 ${prefix.length}，列 ${prefix[prefix.length - 1].length + 1}`
}
function indent() {
  const element = input.value
  if (!element || element.readOnly) return
  const start = element.selectionStart, end = element.selectionEnd
  content.value = content.value.slice(0, start) + '    ' + content.value.slice(end)
  requestAnimationFrame(() => { element.selectionStart = element.selectionEnd = start + 4; updateCursor() })
}
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value || saving.value) { event.preventDefault(); event.returnValue = '' } }
window.addEventListener('beforeunload', beforeUnload)
watch(() => [props.request.missionId, props.request.relativePath], () => void load(), {immediate: true})
watch([content, () => props.request.name], () => scheduleHighlight(), {flush: 'post'})
onBeforeUnmount(() => { controller?.abort(); window.clearTimeout(highlightTimer); highlightToken += 1; window.removeEventListener('beforeunload', beforeUnload) })
</script>
<style scoped>
.file-editor { display:flex; flex-direction:column; width:100%; height:100%; min-height:0; color:var(--wb-text); background:var(--wb-surface-shell); }
.file-editor__toolbar { display:flex; align-items:center; gap:12px; padding:8px 16px; font-size:12px; color:var(--wb-text-secondary); }
.file-editor__path { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.file-editor button { color:var(--wb-text); background:var(--wb-surface-1); border:1px solid var(--wb-border-strong); border-radius:4px; padding:4px 10px; cursor:pointer; }
.file-editor button:disabled { opacity:.45; cursor:default; }
.file-editor__dirty { color:var(--wb-warning); }
.file-editor__body { flex:1; min-height:0; display:flex; overflow:hidden; }
.file-editor__lines,.file-editor__highlight,.file-editor__input { margin:0; padding:14px 16px; border:0; font:13px/22px var(--font-mono,Consolas,monospace); tab-size:4; }
.file-editor__lines { width:52px; flex:none; box-sizing:border-box; text-align:right; overflow:hidden; color:var(--wb-text-muted); user-select:none; }
.file-editor__code { position:relative; flex:1; min-width:0; overflow:hidden; }
.file-editor__highlight,.file-editor__input { position:absolute; inset:0; }
.file-editor__highlight { overflow:hidden; white-space:pre; pointer-events:none; color:var(--wb-text); }
/* 文件以换行结尾时 <pre> 会少一行，补零宽字符让着色层与原生输入框的滚动高度一致。 */
.file-editor__highlight code { font:inherit; white-space:pre; }
.file-editor__highlight code::after { content:"\200b"; }
.file-editor__input { resize:none; outline:none; white-space:pre; overflow:auto; background:transparent; color:var(--wb-text); caret-color:var(--wb-accent); }
/* 着色层在下面，原生输入框只保留光标与选区，保证编辑/撤销/保存行为完全不变。 */
.file-editor__input.is-highlighted { color:transparent; }
.file-editor__input.is-highlighted::selection { background:color-mix(in srgb,var(--wb-accent) 34%,transparent); }
.file-editor__input:focus-visible { box-shadow:inset 0 0 0 1px var(--wb-accent); }
.file-editor__error { padding:10px 16px; color:var(--wb-danger); }
.file-editor__highlight :deep(.hljs-comment),.file-editor__highlight :deep(.hljs-quote) { color:var(--wb-text-muted); font-style:italic; }
.file-editor__highlight :deep(.hljs-keyword),.file-editor__highlight :deep(.hljs-selector-tag),.file-editor__highlight :deep(.hljs-literal),.file-editor__highlight :deep(.hljs-doctag) { color:var(--sem-artifact); }
.file-editor__highlight :deep(.hljs-string),.file-editor__highlight :deep(.hljs-regexp),.file-editor__highlight :deep(.hljs-addition),.file-editor__highlight :deep(.hljs-attribute),.file-editor__highlight :deep(.hljs-template-tag) { color:var(--sem-success); }
.file-editor__highlight :deep(.hljs-number),.file-editor__highlight :deep(.hljs-symbol),.file-editor__highlight :deep(.hljs-bullet),.file-editor__highlight :deep(.hljs-link) { color:var(--sem-retry); }
.file-editor__highlight :deep(.hljs-title),.file-editor__highlight :deep(.hljs-section),.file-editor__highlight :deep(.hljs-name),.file-editor__highlight :deep(.hljs-selector-id) { color:var(--wb-accent); }
.file-editor__highlight :deep(.hljs-built_in),.file-editor__highlight :deep(.hljs-type),.file-editor__highlight :deep(.hljs-class .hljs-title),.file-editor__highlight :deep(.hljs-selector-class) { color:var(--sem-flow); }
.file-editor__highlight :deep(.hljs-attr),.file-editor__highlight :deep(.hljs-variable),.file-editor__highlight :deep(.hljs-template-variable),.file-editor__highlight :deep(.hljs-params) { color:var(--wb-text); }
.file-editor__highlight :deep(.hljs-meta),.file-editor__highlight :deep(.hljs-tag) { color:var(--sem-waiting); }
.file-editor__highlight :deep(.hljs-deletion) { color:var(--sem-failed); }
.file-editor__highlight :deep(.hljs-operator),.file-editor__highlight :deep(.hljs-punctuation) { color:var(--wb-text-secondary); }
.file-editor__highlight :deep(.hljs-strong) { color:var(--wb-text); font-weight:600; }
.file-editor__highlight :deep(.hljs-emphasis) { color:var(--wb-text-secondary); font-style:italic; }
</style>
