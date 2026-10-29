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
      <textarea ref="input" v-model="content" class="file-editor__input" aria-label="文件内容" spellcheck="false" autocapitalize="off" autocomplete="off" :readonly="saving || !version"
        @keydown.ctrl.s.prevent="save" @keydown.meta.s.prevent="save" @keydown.tab.prevent="indent" @scroll="syncScroll" @click="updateCursor" @keyup="updateCursor" />
    </div>
    <footer class="file-editor__status"><span>{{ version ? '本地文件' : '只读 · 当前执行后端不支持版本保护保存' }}</span><span>{{ language }} · UTF-8 · {{ lines }} 行 · {{ cursor }}</span></footer>
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { getElectronBridge } from '@/platform/electron/bridge'
import { agentosApi, type WorkspaceFileOpenRequest } from '@/services/api/agentos'
const props = defineProps<{request: WorkspaceFileOpenRequest}>()
const emit = defineEmits<{'dirty-change': [dirty: boolean]}>()
const content = ref(''), original = ref(''), version = ref<string | null>(null)
const error = ref(''), loading = ref(false), saving = ref(false), loaded = ref(false)
const input = ref<HTMLTextAreaElement>(), gutter = ref<HTMLElement>(), cursor = ref('行 1，列 1')
const dirty = computed(() => content.value !== original.value)
const lines = computed(() => content.value.split('\n').length)
const lineNumbers = computed(() => Array.from({length: lines.value}, (_, i) => i + 1).join('\n'))
const language = computed(() => props.request.name.split('.').pop()?.toUpperCase() || 'TEXT')
watch(dirty, value => emit('dirty-change', value), {immediate: true})
let controller: AbortController | undefined
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
    content.value = original.value = file.content
    version.value = file.version || null
    loaded.value = true
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
function syncScroll() { if (gutter.value && input.value) gutter.value.scrollTop = input.value.scrollTop }
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
onBeforeUnmount(() => { controller?.abort(); window.removeEventListener('beforeunload', beforeUnload) })
</script>
<style scoped>
.file-editor { display:flex; flex-direction:column; width:100%; height:100%; min-height:0; color:var(--wb-text); background:var(--wb-surface-shell); }
.file-editor__toolbar,.file-editor__status { display:flex; align-items:center; gap:12px; padding:8px 16px; font-size:12px; color:var(--wb-text-secondary); }
.file-editor__path { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.file-editor button { color:var(--wb-text); background:var(--wb-surface-1); border:1px solid var(--wb-border-strong); border-radius:4px; padding:4px 10px; cursor:pointer; }
.file-editor button:disabled { opacity:.45; cursor:default; }
.file-editor__dirty { color:var(--wb-warning); }
.file-editor__body { flex:1; min-height:0; display:flex; overflow:hidden; }
.file-editor__lines,.file-editor__input { margin:0; padding:14px 16px; border:0; font:13px/22px var(--font-mono,Consolas,monospace); tab-size:4; }
.file-editor__lines { width:52px; flex:none; box-sizing:border-box; text-align:right; overflow:hidden; color:var(--wb-text-muted); user-select:none; }
.file-editor__input { flex:1; min-width:0; resize:none; outline:none; white-space:pre; overflow:auto; background:transparent; color:var(--wb-text); caret-color:var(--wb-accent); }
.file-editor__input:focus-visible { box-shadow:inset 0 0 0 1px var(--wb-accent); }
.file-editor__status { justify-content:space-between; border-top:1px solid var(--wb-border); }
.file-editor__error { padding:10px 16px; color:var(--wb-danger); }
</style>
