<template>
  <section v-if="visible" class="formal-control" :class="{ 'is-embedded': embedded, 'is-conversational': conversational }" aria-label="正式运行控制">
    <header v-if="!conversational"><strong>{{ embedded ? '任务进展' : '运行控制' }}</strong><button type="button" :disabled="pending" @click="emit('refresh')">刷新</button></header>
    <LifecycleProgress v-if="embedded && !conversational" :phase="lifecycle.phase" />
    <dl v-if="!embedded && !conversational" aria-live="polite">
      <div><dt>任务</dt><dd>{{ run?.status || '状态不可用' }}</dd></div>
      <div><dt>图</dt><dd>{{ control?.status || '证据不可用' }}</dd></div>
      <div><dt>许可</dt><dd>{{ control?.permitStatus || '尚未签发' }}</dd></div>
      <div><dt>执行命令</dt><dd>{{ control?.dispatch?.status || '尚未提交' }}</dd></div>
    </dl>
    <p v-if="!conversational || action || waitingForApproval || !control" class="formal-control__hint">{{ explanation }}</p>
    <p v-if="!conversational && (run?.failureCode || run?.error?.code)" role="status" class="formal-control__error">{{ run.failureCode || run.error?.code }}</p>
    <div class="formal-control__actions">
      <button v-if="action" type="button" class="formal-control__primary" :disabled="disabled" @click="submit">
        {{ pending ? '正在提交…' : error && !blocked ? '重试原操作' : reviewedPlan && action === 'materialize' ? '确认规划并继续' : formalActionLabels[action] }}
      </button>
      <button v-if="canCancel && !historical && capabilities?.canCancel" type="button" :disabled="readonly || pending || cancelPending || !run" @click="emit('cancel')">
        {{ cancelPending ? '正在取消…' : '取消任务' }}
      </button>
    </div>
    <p v-if="error" class="formal-control__error" role="alert">{{ error }}</p>
    <small v-if="!reviewedPlanMatches">规划版本已更新，请刷新后审阅最新规划。</small>
    <small v-if="(readonly || executionReadonly) && !historical && action">当前视图仅供查看，正式操作已禁用。</small>
    <WorkflowReviewPanel v-if="showReview && run?.status === 'waiting_review' && !historical && !blocked && !readonly && !executionReadonly && capabilities?.canReview" :run-id="run.runId"
      :run="reviewRun" :progress="null" compact @reviewed="emit('refresh')" @conflict="emit('refresh')" />
    <div :class="{ 'formal-control__meta': conversational }">
    <details v-if="control"><summary>{{ conversational ? '运行详情' : embedded ? '运行状态与授权引用' : '授权与关联引用' }}</summary><dl>
      <template v-if="embedded || conversational">
        <div><dt>任务</dt><dd>{{ run?.status || '状态不可用' }}</dd></div>
        <div><dt>图</dt><dd>{{ control.status }}</dd></div>
        <div><dt>许可</dt><dd>{{ control.permitStatus || '尚未签发' }}</dd></div>
        <div><dt>执行命令</dt><dd>{{ control.dispatch?.status || '尚未提交' }}</dd></div>
        <div v-if="run?.failureCode || run?.error?.code"><dt>失败代码</dt><dd>{{ run.failureCode || run.error?.code }}</dd></div>
      </template>
      <div v-for="(value, key) in references" :key="key"><dt>{{ key }}</dt><dd :title="String(value)">{{ value || '—' }}</dd></div>
    </dl></details>
    <button v-if="conversational" type="button" class="formal-control__refresh" :disabled="pending" @click="emit('refresh')">刷新状态</button>
    </div>
  </section>
</template>

<script setup lang="ts">
import LifecycleProgress from './LifecycleProgress.vue'
import { projectRunLifecycle, lifecycleDescriptions } from '@/features/workspace/runLifecycle'
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { agentosApi, type WorkflowRun, type RunActionCapabilities } from '@/services/api/agentos'
import { readRunCapabilities } from '@/workbench/runtime/runCapabilities'
import WorkflowReviewPanel from '@/components/agentos/WorkflowReviewPanel.vue'
import { formalActionLabels, formalSource, nextFormalAction, prepareFormalCommand, validFormalReceipt, type FormalOperationSuccess } from '@/features/acg/formalControl'

const props = withDefaults(defineProps<{ run: WorkflowRun | null; runId: string | null; missionId: string; historical: boolean; canCancel: boolean; cancelPending: boolean; embedded?: boolean; conversational?: boolean; readonly?: boolean; executionReadonly?: boolean; showReview?: boolean; actionCapabilities?: RunActionCapabilities | null; reviewedPlan?: { commitId: string | null; commitmentRevision: number | null } | null; requirePlanReview?: boolean; waitingForApproval?: boolean }>(), { embedded: false, conversational: false, readonly: false, executionReadonly: false, showReview: true, reviewedPlan: null, requirePlanReview: false, waitingForApproval: false })
const capabilities = computed(() => !Number.isInteger(props.run?.runtimeRevision) ? null :
  readRunCapabilities(props.actionCapabilities === undefined ? props.run?.actionCapabilities : props.actionCapabilities,
    props.missionId, props.runId, props.run?.runtimeRevision, props.run?.status))
const emit = defineEmits<{ refresh: []; cancel: []; succeeded: [event: FormalOperationSuccess] }>()
const pending = ref(false)
const error = ref('')
const blocked = ref(false)
const acknowledged = ref('')
const seenFormal = ref(false)
let generation = 0
onBeforeUnmount(() => { generation++ })
watch(() => [props.missionId, props.runId], () => { generation++; pending.value = false; error.value = ''; blocked.value = false; acknowledged.value = ''; seenFormal.value = false })
watch(() => props.run?.formalControl, c => { if (c) seenFormal.value = true }, { immediate: true })
const control = computed(() => props.run?.formalControl)
const visible = computed(() => seenFormal.value || Boolean(control.value) || props.run?.executionState?.planningCommitRequired
  || props.canCancel && capabilities.value?.canCancel === true)
const action = computed(() => props.run?.runId === props.runId && props.run?.missionId === props.missionId ? nextFormalAction(props.run) : null)
const reviewedPlanMatches = computed(() => action.value !== 'materialize' || (!props.reviewedPlan ? !props.requirePlanReview
  : Boolean(props.reviewedPlan.commitId && props.reviewedPlan.commitId === control.value?.commitId
    && props.reviewedPlan.commitmentRevision === control.value?.commitmentRevision)))
const source = computed(() => action.value && props.run ? formalSource(props.run, action.value) : '')
watch(source, () => { error.value = ''; blocked.value = false })
// Observe authority changes synchronously, including mutations of the same Run object.
const authority = computed(() => JSON.stringify([props.missionId, props.runId,
  props.run?.missionId, props.run?.runId, props.run?.status, props.run?.runtimeRevision,
  props.run?.formalControl, capabilities.value, props.historical,
  props.readonly, props.executionReadonly]))
watch(authority, () => { generation++; pending.value = false }, { flush: 'sync' })

const disabled = computed(() => props.readonly || props.executionReadonly || pending.value || blocked.value || props.historical || acknowledged.value === source.value
  || !reviewedPlanMatches.value || !capabilities.value?.canExecuteFormalAction || !action.value || !capabilities.value.formalActions.includes(action.value))
const reviewRun = computed(() => props.run ? { ...props.run, review: props.run.review || props.run.executionState?.reviewPayload } : null)
const references = computed(() => ({ Commit: control.value?.commitId, Graph: control.value?.graphId, Version: control.value?.graphVersion,
  Activation: control.value?.activationId, Handoff: control.value?.handoffId, Permit: control.value?.permitId, Dispatch: control.value?.dispatch?.dispatchId }))
const lifecycle = computed(() => projectRunLifecycle({ missionId: props.missionId, runId: props.runId || '', run: props.run }))
const explanation = computed(() => {
  if (props.waitingForApproval) return '等待你确认工具操作，审批通过后继续执行。'
  if (!props.run) return '无法验证正式状态，控制操作已禁用。'
  if (!control.value) return capabilities.value?.canCancel
    ? 'Runtime 已确认此 Run 可停止；未提供正式图控制证据。' : '无法验证正式状态，控制操作已禁用。'
  if (props.historical) return '历史 Run 只读。'
  if (props.embedded) return lifecycleDescriptions[lifecycle.value.phase]
  if (props.run.status === 'completed') return props.embedded ? '任务已完成，可从左侧查看或下载交付文件。' : '运行已完成；已登记的 Artifact 可从左侧打开或下载，最终交付以正式引用为准。'
  if (['failed', 'cancelled'].includes(props.run.status)) return props.run.lifecycleMessage || '运行已停止。请查看下方故障与恢复证据。'
  if (props.run.status === 'waiting_review') return '等待审核；审核决定由正式接口处理。'
  if (props.run.status === 'running' || props.run.status === 'retrying') return '以 Run 查询与节点事件观察实际执行。'
  if (control.value.dispatch) return '执行命令已持久接受，等待正式运行状态更新。202 不代表完成。'
  if (control.value.permitStatus === 'ISSUED') return control.value.dispatchEnabled
    ? '许可已签发，尚未执行。点击“执行任务”才会提交执行命令。'
    : '许可已签发；当前服务未开启正式 Dispatch，控制保持只读。'
  if (control.value.handoffStatus === 'STATE_PREPARED') return '执行交接已准备，仍需申请许可。'
  if (control.value.status === 'ACTIVATED_PAUSED') return '任务图已激活，执行保持暂停。'
  if (control.value.status === 'PLANNING_ACCEPTED') return '正式规划已接受，可准备任务图。'
  if (action.value === 'activate') return '任务图已物化，尚未激活。'
  return '等待正式规划或可验证状态；未识别的状态禁止控制操作。'
})
const submit = async () => {
  if (!action.value || !props.run || disabled.value) return
  const current = generation
  const run = props.run
  const requestedAction = action.value
  const requestedSource = source.value
  pending.value = true
  error.value = ''
  let prepared = false
  try {
    const command = prepareFormalCommand(run, requestedAction, localStorage)
    prepared = true
    const receipt = await agentosApi.submitFormalControl(run.missionId, run.runId, requestedAction, command)
    if (current !== generation) return
    if (!validFormalReceipt(requestedAction, command.operationId, receipt)) throw new Error('Unconfirmed formal receipt')
    acknowledged.value = requestedSource
    emit('succeeded', { action: requestedAction, operationId: command.operationId, status: receipt.status,
      dispatchId: receipt.dispatchId, missionId: run.missionId, runId: run.runId })
    emit('refresh') // No optimistic Run/Permit state and no follow-on command.
  } catch (failure: unknown) {
    if (current !== generation) return
    const status = (failure as { response?: { status?: number } }).response?.status
    blocked.value = !prepared || status === 401 || status === 403 || status === 409 || status === 422
    error.value = !prepared ? '操作重试记录不可用或已损坏，控制已禁用。'
      : blocked.value ? '授权或版本校验未通过，控制已禁用。请刷新检查正式状态。'
      : '提交结果未确认。可重试原操作；不会生成新的 operationId。'
    emit('refresh')
  } finally {
    if (current === generation) pending.value = false
  }
}
</script>

<style scoped>
.formal-control { flex: 0 0 auto; max-height: 58%; overflow: auto; padding: 10px 12px; border-bottom: 1px solid var(--wb-border-soft); color: var(--wb-text); background: var(--wb-surface-pane); font-size: 12px; }
.formal-control.is-embedded { max-height: none; overflow: visible; margin-bottom: 16px; padding: 10px 12px; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-sm); background: var(--wb-surface-inset); }
header, .formal-control__actions { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
header strong { font-size: 12px; font-weight: 600; }
dl { display: grid; gap: 5px; margin: 10px 0; }
dl > div { display: grid; grid-template-columns: 70px minmax(0, 1fr); gap: 8px; }
dt { color: var(--wb-text-muted); }
dd { margin: 0; min-width: 0; overflow-wrap: anywhere; font: 11px/1.5 var(--font-mono, monospace); }
button { min-height: 26px; padding: 3px 8px; border: 1px solid var(--wb-border-soft); border-radius: var(--wb-radius-sm); color: var(--wb-text); background: var(--wb-surface-inset); cursor: pointer; font-size: 12px; }
button:hover:not(:disabled) { background: var(--surface-hover); }
button:focus-visible, summary:focus-visible { outline: 1px solid var(--wb-accent); outline-offset: 2px; }
button:disabled { opacity: .5; cursor: default; }
.formal-control__primary { color: var(--on-primary); background: var(--primary-color); }
.formal-control__primary:hover:not(:disabled) { background: var(--primary-hover); }
.formal-control__hint { color: var(--wb-text-secondary); line-height: 1.6; margin: 8px 0; }
.formal-control__error { color: var(--wb-danger); line-height: 1.6; overflow-wrap: anywhere; }
details { margin-top: 10px; color: var(--wb-text-muted); }
summary { cursor: pointer; }
.formal-control.is-conversational { max-height: none; overflow: visible; margin: 0 0 22px; padding: 0; border: 0; border-radius: 0; background: transparent; }
.is-conversational .formal-control__actions { justify-content: flex-start; flex-wrap: wrap; }
.is-conversational .formal-control__hint { margin: 0 0 12px; }
.formal-control__meta { display: flex; align-items: baseline; flex-wrap: wrap; gap: 6px 16px; color: var(--wb-text-muted); font-size: 11px; }
.formal-control__meta details { min-width: 0; margin-top: 10px; }
.formal-control__meta details[open] { flex-basis: 100%; }
.formal-control__meta .formal-control__refresh { min-height: 24px; margin-top: 6px; padding: 0; border: 0; background: transparent; color: var(--wb-text-muted); font-size: 11px; }
.formal-control__meta .formal-control__refresh:hover:not(:disabled) { color: var(--wb-text); }
</style>
