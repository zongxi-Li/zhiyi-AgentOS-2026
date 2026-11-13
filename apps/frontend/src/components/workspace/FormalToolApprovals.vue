<template>
  <section v-if="items.length || error" class="tool-approvals" aria-label="正式任务工具审批" aria-live="polite">
    <article v-for="item in items" :key="item.approvalId">
      <header class="tool-approvals__head">
        <el-icon aria-hidden="true"><Key /></el-icon>
        <strong>等待你确认</strong>
      </header>
      <p>任务希望进行以下操作，确认后才会继续。</p>
      <p>{{ item.operationSummary }}</p>
      <code v-if="item.relativePath && item.relativePath !== '.'">{{ item.relativePath }}</code>
      <pre v-if="item.command">{{ item.command }}</pre>
      <p v-if="item.riskNotice" class="tool-approvals__risk">{{ item.riskNotice }}</p>
      <p v-if="readonly" class="tool-approvals__notice">正在同步操作权限或当前仅有查看权限，请刷新运行状态。</p>
      <div class="tool-approvals__actions">
        <button :disabled="busy || readonly || !active" @click="resolve(item.approvalId, 'allow_once')">{{ busy ? '正在提交…' : '允许本次操作' }}</button>
        <button :disabled="busy || readonly || !active" @click="resolve(item.approvalId, 'deny')">拒绝本次操作</button>
      </div>
    </article>
    <p v-if="error" class="tool-approvals__error" role="alert"><span>{{ error }}</span> <button :disabled="busy" @click="refresh">重试</button></p>
  </section>
</template>
<script setup lang="ts">
import { ref, shallowRef, onActivated, onDeactivated, onBeforeUnmount, watch } from 'vue'
import { Key } from '@element-plus/icons-vue'
import { agentosRequest } from '@/services/api/agentos/client'
import { acquireRunRuntimeStore, releaseRunRuntimeStore, type RunRuntimeStore } from '@/workbench/runtime/runtimeEvents'
interface ToolApproval { approvalId: string; operationSummary: string; relativePath?: string; command?: string; riskNotice?: string }
const props = withDefaults(defineProps<{runId: string; active: boolean; readonly?: boolean}>(), { readonly: false })
const emit = defineEmits<{ waiting: [value: boolean]; resolved: [] }>()
const items = ref<ToolApproval[]>([])
const busy = ref(false)
const error = ref('')
const events = shallowRef<RunRuntimeStore | null>(null)
let connectedRunId: string | null = null
let viewActive = true
let generation = 0
let controller: AbortController | null = null
async function refresh() {
  if (!viewActive || !props.active || !props.runId) return
  controller?.abort()
  const request = new AbortController()
  controller = request
  const token = generation, runId = props.runId
  try {
    const response = await agentosRequest.get(`/runs/${encodeURIComponent(runId)}/tool-approvals`, { signal: request.signal, timeout: 15000 })
    if (viewActive && token === generation && controller === request) { items.value = response.data.items; error.value = '' }
  }
  catch { if (viewActive && token === generation && !request.signal.aborted) error.value = '暂时无法读取工具审批状态。' }
}
async function resolve(id: string, decision: string) {
  if (busy.value || props.readonly || !props.active) return
  const runId = props.runId, token = generation
  busy.value = true
  error.value = ''
  try {
    await agentosRequest.post(`/runs/${encodeURIComponent(runId)}/tool-approvals/${encodeURIComponent(id)}`, { decision })
    if (token !== generation) return
    emit('resolved')
    await refresh()
  } catch { if (token === generation) { error.value = '审批未确认，请刷新运行状态后重试。'; emit('resolved') } }
  finally { if (token === generation) busy.value = false }
}
function disconnect() {
  generation++; controller?.abort(); controller = null
  if (events.value) releaseRunRuntimeStore(connectedRunId, events.value)
  events.value = null; connectedRunId = null
  items.value = []; busy.value = false; error.value = ''; emit('waiting', false)
}
function connect() {
  disconnect()
  if (!viewActive || !props.active || !props.runId) return
  connectedRunId = props.runId
  events.value = acquireRunRuntimeStore(props.runId)
  void refresh()
}
watch(() => [props.runId, props.active], connect, { immediate: true })
watch(() => events.value?.activity.approvalRevision, () => { void refresh() })
watch(() => items.value.length > 0, value => emit('waiting', value))
onDeactivated(() => { viewActive = false; disconnect() })
onActivated(() => { if (!viewActive) { viewActive = true; connect() } })
onBeforeUnmount(disconnect)
</script>
<style scoped>
.tool-approvals { margin: 14px 0; color: var(--wb-text); font-size: 12px; line-height: 1.7; }
/* 审批卡：与问题卡同语言的主色淡染面 + 图标头，突出「需要人决策」 */
article { padding: 13px 14px; border: 1px solid color-mix(in srgb, var(--wb-accent) 36%, var(--wb-border-soft)); border-radius: 10px; background: color-mix(in srgb, var(--wb-accent) 5%, var(--wb-surface-section)); }
.tool-approvals__head { display: flex; align-items: center; gap: 7px; }
.tool-approvals__head .el-icon { flex-shrink: 0; font-size: 15px; color: var(--wb-accent); }
strong { color: var(--wb-accent); font-size: 13px; }
p { margin: 8px 0 0; }
.tool-approvals__notice { color: var(--wb-text-muted); font-size: 11px; }
.tool-approvals__risk { margin-top: 10px; padding: 8px 10px; border: 1px solid color-mix(in srgb, var(--wb-warning) 24%, transparent); border-radius: 7px; background: color-mix(in srgb, var(--wb-warning) 9%, transparent); color: color-mix(in srgb, var(--wb-warning) 72%, var(--wb-text)); font-size: 11px; line-height: 1.65; }
code { display: inline-block; margin-top: 8px; padding: 3px 8px; border: 1px solid var(--wb-border-soft); border-radius: 6px; background: var(--wb-surface-inset); color: var(--wb-text-secondary); font: 11px/1.65 var(--font-mono, monospace); white-space: pre-wrap; overflow-wrap: anywhere; }
pre { max-height: 160px; overflow: auto; margin: 9px 0 0; padding: 10px 12px; border: 1px solid var(--wb-border-soft); border-radius: 8px; background: var(--wb-surface-inset); color: var(--wb-text); font: 11px/1.65 var(--font-mono, monospace); white-space: pre-wrap; overflow-wrap: anywhere; }
.tool-approvals__actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
button { padding: 6px 14px; border: 1px solid var(--wb-border-soft); border-radius: 7px; background: var(--wb-surface-section); color: var(--wb-text); font: inherit; cursor: pointer; transition: filter 150ms var(--ease-out, ease), background-color 150ms var(--ease-out, ease), border-color 150ms var(--ease-out, ease); }
.tool-approvals__actions button:first-child { color: var(--on-primary); background: var(--primary-color); border-color: transparent; font-weight: 500; }
.tool-approvals__actions button:first-child:hover:not(:disabled) { filter: brightness(1.12); }
.tool-approvals__actions button:hover:not(:disabled):not(:first-child) { background: var(--wb-hover); border-color: var(--wb-border-strong); }
button:disabled { opacity: .5; cursor: not-allowed; }
button:focus-visible { outline: 2px solid var(--wb-accent); outline-offset: 2px; }
.tool-approvals__error { display: flex; align-items: center; gap: 8px; margin-top: 10px; padding: 10px 12px; border: 1px solid color-mix(in srgb, var(--wb-danger) 30%, transparent); border-radius: 8px; background: color-mix(in srgb, var(--wb-danger) 8%, transparent); color: var(--wb-text-secondary); font-size: 11px; }
.tool-approvals__error button { margin-left: auto; flex-shrink: 0; padding: 4px 10px; border: 0; background: transparent; color: var(--wb-danger); }
.tool-approvals__error button:hover:not(:disabled) { background: color-mix(in srgb, var(--wb-danger) 12%, transparent); }
</style>
