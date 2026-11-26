<template>
  <section class="acg-copilot" aria-label="ACG Copilot 任务助手">
    <div class="context-strip"><el-icon><Share /></el-icon><span :title="targetTitle">{{ targetTitle }}</span><small>{{ statusLabel }}</small></div>
    <nav class="copilot-tabs" aria-label="助手视图">
      <button :class="{ active: tab === 'chat' }" @click="tab = 'chat'">对话 <i v-if="state?.question || state?.review && !reviewPending" class="attention-dot"></i></button>
      <button :class="{ active: tab === 'trace' }" @click="tab = 'trace'">活动记录 <small v-if="trajectoryCount">{{ trajectoryCount }}</small></button>
      <button :class="{ active: tab === 'pool' }" @click="tab = 'pool'">执行池</button>
    </nav>

    <div v-show="tab === 'chat'" ref="messageList" class="conversation" :class="{ 'has-run-controls': hasFormalControl }" aria-live="polite" @scroll="trackScroll">
      <CopilotRunTimeline :key="runId || ''" :run-id="runId" :status="state?.status || runStatus || ''"
        :messages="messages" :graph-nodes="graphNodes" :plan="state?.initialPlan" :tools="state?.toolActivity" :workspace-review="state?.workspaceReview" :traces="runtimeObservation?.runId === runId ? runtimeObservation.traces : []" :started-at="controlRun?.startedAt" :updated-at="controlRun?.updatedAt" :waiting-for-approval="hasPendingToolApproval" :has-resource-details="!!controlRun" @content="hasTimelineContent = $event; scrollBottom()" @inspect-agent="inspectAgent" @inspect-resource-step="inspectResourceStep">
      <template #controls><FormalExecutionControls :key="runId || ''" :run="controlRun" :run-id="runId"
        :action-capabilities="actionCapabilities"
        :mission-id="missionId || state?.missionId || ''" :historical="historical"
        :can-cancel="canCancel" :cancel-pending="cancelPending" embedded conversational launch-in-one-click
        :readonly="readonly || historical || busy || loading || !state"
        :execution-readonly="permission !== 'task_collaboration'" :reviewed-plan="state?.initialPlan" require-plan-review :waiting-for-approval="hasPendingToolApproval"
        :show-review="!state?.review && !state?.planningProgress" @refresh="refreshRun" @cancel="emit('cancel-run')" /></template>
      <template #approvals><FormalToolApprovals v-if="runId && !historical" ref="toolApprovals" :run-id="runId" :active="(state?.status || runStatus) === 'running'"
        :readonly="readonly || !allows('canResolveToolApproval')" @waiting="hasPendingToolApproval = $event" @resolved="refreshRun" /></template>
      <template #message="{ message }">
      <article class="message" :class="`is-${message.role}`">
        <div v-if="message.role === 'user' || message.planner" class="message-meta"><span>{{ message.role === 'user' ? '你' : '任务助手' }}</span><small v-if="message.planner">任务澄清</small></div>
        <div class="message-content markdown-body" v-html="messageMarkup.get(message.id)"></div>
        <small v-if="copilotResponseSummary(message)" class="response-stats" title="服务端本次回复的耗时，包含准备与排队，不包含浏览器绘制。">{{ copilotResponseSummary(message) }}</small>
        <div v-if="message.action" class="operation-card">
          <strong>{{ actionLabel(message.action.kind) }}</strong>
          <p v-if="message.action.kind === 'user_input'">在当前执行片段结束后，由 Planner 重新观察并处理补充要求。</p>
          <p v-else-if="message.action.planningMode === 'fresh'">在原任务下创建新 Run，根据当前任务目标重新规划。原运行可在历史中查看。</p>
          <template v-else><p>重新执行：{{ stepNames(message.action.executeStepIds) }}</p><p>复用结果：{{ stepNames(message.action.reusedStepIds) || '无' }}</p><p v-if="message.action.executionEnvironmentChanged">执行环境已更新：保持原计划与输入，使用当前可用能力重新执行。</p><small v-if="message.action.kind === 'recover' && message.action.retryMode === 'current_run'">在当前 Run 继续执行，保留已提交结果并追加执行记录。</small><small v-else>创建新 Run，保留原运行记录与上游证据。</small></template>
          <button type="button" :disabled="busy || loading || permission !== 'task_collaboration' || readonly || historical || !proposalAllowed(message.action, message.sourceRunId) || !!receipts[receiptKey(message.sourceRunId, message.proposalId)]" @click="confirmAction(message.proposalId, message.action, message.sourceRunId)">{{ receipts[receiptKey(message.sourceRunId, message.proposalId)] ? '已提交' : '确认操作' }}</button>
        </div>
        <div v-if="message.receipt" class="operation-receipt"><span>{{ message.receipt.kind === 'user_input' ? '等待 Planner 处理' : '运行已提交' }}</span><button v-if="message.receipt.runId !== runId" type="button" @click="emit('select-run', message.receipt.runId)">查看新运行 <el-icon><ArrowRight /></el-icon></button></div>
      </article>
      </template>
      </CopilotRunTimeline>
      <div v-if="planningRepairing" class="planning-progress wait-note" role="status"><el-icon class="is-loading"><Loading /></el-icon><span>{{ state?.planningProgress?.message }}</span></div>
      <div v-else-if="state?.planningProgress?.kind === 'blocked'" class="planning-progress planning-progress--blocked" role="status"><p>{{ state.planningProgress.message }}</p><details><summary>查看交接受阻原因</summary><p>{{ state.planningProgress.reason || state.planningProgress.errorCode }}</p><small v-if="state.planningProgress.errorType">{{ state.planningProgress.errorType }}</small></details></div>
      <div v-if="loading && !state" class="empty-state"><el-icon class="is-loading"><Loading /></el-icon><p>正在读取任务对话…</p></div>
      <div v-else-if="!messages.length && !state?.question && !state?.review && !state?.planningProgress && !state?.initialPlan && !state?.toolActivity?.length && !hasPendingToolApproval && !hasTimelineContent && !['pending', 'planning'].includes(state?.status || runStatus || '')" class="empty-state">
        <img class="empty-watermark" :src="activePack.mark" alt="" aria-hidden="true" />
        <h3 v-if="!creating">{{ runId ? '一起推进这项任务' : '从一项任务开始' }}</h3>
        <p v-if="!creating">{{ runId ? '检查进展、理解问题，或一起梳理下一步。' : '选择或启动任务后，在这里与任务助手交流。' }}</p>
      </div>

      <article v-if="busy && pendingUser" class="stream-turn">
        <div v-if="!answering" class="message is-user"><div class="message-content">{{ pendingUser }}</div></div>
        <ChatTranscriptBlock v-if="streamContent" class="message-content streaming-content" :block="streamBlock" :render-text="renderCopilotMarkdown" />
        <div class="stream-activity" role="status"><el-icon class="is-loading"><Loading /></el-icon><span>{{ answering ? '正在提交回答' : streamPhaseText }}</span><div v-if="!streamContent" class="thinking-line"></div></div>
      </article>
      <article v-if="state?.question" class="question-card">
        <div class="question-heading"><el-icon><ChatDotRound /></el-icon><span>需要你的补充</span><small>任务已暂停</small></div>
        <p>{{ state.question.prompt }}</p>
        <div v-if="state.question.choices.length" class="question-choices"><button v-for="choice in state.question.choices" :key="choice" :disabled="busy" @click="draft = choice; answering = true; focusComposer()">{{ choice }}</button></div>
        <button v-if="state" class="reply-link" @click="answering = true; focusComposer()">回答后继续规划 <el-icon><ArrowRight /></el-icon></button>
      </article>
      <article v-if="state?.review && !state.question" class="review-card">
        <div class="question-heading"><el-icon :class="{ 'is-loading': reviewPending }"><Loading v-if="reviewPending" /><Clock v-else /></el-icon><strong>{{ reviewTitle }}</strong></div>
        <p>{{ reviewDescription }}</p>
        <ul v-if="failedSteps.length"><li v-for="step in failedSteps" :key="step.stepId">{{ step.name }} · 执行失败</li></ul>
        <details>
          <summary>{{ reviewPending || state.review.decisionRejected || ['workspace_revision_blocked', 'planner_rejected', 'planner_error'].includes(reviewKind) ? '查看技术详情' : '查看等待原因与处理建议' }}</summary>
          <p>当前记录：{{ state.review.reason }}</p>
          <p v-if="state.review.errorCode">{{ reviewKind === 'planner_error' ? '错误代码' : '拒绝代码' }}：{{ state.review.errorCode }}</p>
          <p v-if="state.review.errorType">错误类型：{{ state.review.errorType }}</p>
          <ul v-if="reviewValidationDetails.length">
            <li v-for="(detail, index) in reviewValidationDetails" :key="index">{{ detail }}</li>
          </ul>
          <p v-if="state.decision?.reason && state.decision.reason !== state.review.reason">规划时记录：{{ state.decision.reason }}</p>
        </details>
        <textarea v-if="!reviewPending" v-model="reviewComment" rows="2" maxlength="2000" :placeholder="reviewKind === 'planner_error' ? '可选：补充重新规划的要求…' : state.review.subjectType === 'planner' ? '说明要补充的材料或调整的执行要求…' : '填写审核意见…'" aria-label="审核意见" :disabled="busy" />
        <div class="review-actions">
          <button v-if="reviewCanApprove" :disabled="busy || loading || permission !== 'task_collaboration' || readonly || historical || !allows('canReview')" @click="submitReview('approved')">{{ reviewKind === 'planner_error' ? '重新规划' : state.review.subjectType === 'planner' ? '确认条件已满足' : '批准并继续' }}</button>
          <button v-if="!reviewPending && state.review.subjectType === 'planner'" :disabled="busy || loading || permission !== 'task_collaboration' || readonly || historical || !allows('canCollaborate') || !reviewComment.trim()" @click="submitReviewInput">预览调整方案</button>
          <button v-if="failedSteps.length" @click="tab = 'trace'">查看失败详情</button>
          <button v-else-if="reviewPending || ['workspace_revision_blocked', 'planner_rejected', 'planner_error'].includes(reviewKind)" @click="tab = 'trace'">查看活动记录</button>
          <button v-if="!reviewPending" :disabled="busy || loading || permission !== 'task_collaboration' || readonly || historical || !allows('canReview')" @click="submitReview('rejected')">{{ state.review.subjectType === 'planner' ? '结束本次运行' : '拒绝并结束本次运行' }}</button>
        </div>
        <small v-if="!reviewPending && permission !== 'task_collaboration' && !readonly && !historical">切换为“按需确认”权限后可操作。</small>
        <small v-if="historical">请前往当前运行处理审核。</small>
        <small v-else-if="!reviewPending && state.review.subjectType === 'planner'">补充要求可用于预览新的处理方案；方案仍须通过正式校验后才能执行。</small>
      </article>
      <div v-else-if="state?.decision && state.status === 'waiting_review' && !state.question" class="wait-note"><el-icon><Clock /></el-icon><span>{{ state.decision.reason }}</span></div>
    </div>

    <div v-if="tab === 'trace'" class="trajectory-view">
      <div class="trace-toolbar"><span>{{ traceSearch.trim() ? `匹配 ${filteredTrajectory.length} / 已加载 ${trajectory.length} 条` : `已加载 ${trajectory.length} 条` }}</span><input v-model="traceSearch" placeholder="搜索步骤或调用" aria-label="搜索活动记录" /></div>
      <div v-if="!trajectory.length" class="empty-state"><el-icon><Connection /></el-icon><h3>尚无活动记录</h3><p>模型、执行步骤和工具调用会在这里留下记录。</p></div>
      <div v-else class="trace-lanes" aria-label="已加载活动分类"><span v-for="lane in lanes" :key="lane" :class="`lane-${lane}`">{{ laneLabel(lane) }} {{ laneCounts[lane] }}</span><div><i v-for="event in filteredTrajectory" :key="event.id" :class="`lane-${event.kind}`" :title="event.title"></i></div></div>
      <div class="trace-list">
        <details v-for="event in filteredTrajectory" :key="event.id" class="trace-event" :class="`lane-${event.kind}`" :open="expandedTrajectory.has(event.id)" @toggle="toggleTrajectoryDetail(event.id, $event)">
          <summary><span class="trace-dot"></span><span class="trace-kind">{{ laneLabel(event.kind) }}</span><div><strong>{{ event.title }}</strong><small>{{ event.step || 'Run' }} <span v-if="event.duration != null">· {{ event.duration }} ms</span></small></div><time>{{ formatTime(event.time) }}</time><el-icon><ArrowDown /></el-icon></summary>
          <pre v-if="expandedTrajectory.has(event.id)">{{ trajectoryDetails.get(event.id) }}</pre>
        </details>
      </div>
      <p v-if="callError" class="no-results">{{ callError }}</p>
      <button v-if="callCursor" class="load-more" :disabled="callsLoading" @click="loadCalls(true)">加载更多模型调用</button>
      <p v-if="trajectory.length && !filteredTrajectory.length" class="no-results">没有匹配的活动记录</p>
      <small class="trace-footnote">按已加载的活动记录计数，不代表步骤数；模型调用按页加载，内部投影合并在调用详情中。</small>
    </div>

    <AgentPoolPanel v-if="tab === 'pool'" :run="controlRun" :selected-step-id="selectedResourceStepId" :selected-instance-id="selectedAgentInstanceId" @select-run="emit('select-run', $event)" />

    <div v-if="reviewReceipt" class="wait-note" role="status">{{ reviewReceipt }}</div>
    <div v-if="permissionReceipt" class="wait-note permission-receipt" role="status">{{ permissionReceipt }}</div>
    <div v-if="error" class="error-note" role="alert"><span>{{ error }}</span><button @click="refresh()">刷新</button></div>
    <slot v-if="creating" name="creation-status" />
    <div v-if="!creating && (historical || readonly || !allows('canCollaborate'))" class="readonly-note">{{ historical ? '历史 Run 只读，可讨论原始证据。' : '操作按所选 Run 的服务端能力限制。' }}<button v-if="state?.latestRunId && state.latestRunId !== runId" type="button" @click="emit('select-run', state.latestRunId)">查看最新创建的 Run</button></div>
    <form ref="composerRoot" class="composer" :class="{ 'is-answering': answering && state?.question }" @submit.prevent="send" @keydown.esc="openMenu = null">
      <div v-if="state?.question" class="composer-mode"><button type="button" :class="{ selected: answering }" @click="answering = true">回答问题</button><button type="button" :class="{ selected: !answering }" @click="answering = false">询问助手</button></div>
      <slot v-if="creating" name="composer-context" />
      <textarea ref="composerInput" v-model="draft" rows="3" :maxlength="creating ? undefined : answering && state?.question ? 2000 : 4000" :disabled="(!runId && !creating) || busy || creationPending" :placeholder="composerPlaceholder" aria-label="任务对话输入" @keydown="onKeydown"></textarea>
      <div class="composer-footer">
        <slot v-if="creating" name="creation-tools" />
        <template v-else>
        <div class="composer-picker"><button type="button" class="picker-trigger" aria-label="任务操作" :disabled="busy || loading || !state || permission !== 'task_collaboration' || readonly || historical || !(allows('canCollaborate') || operationAllowed('recover') || allows('canRerunSuccessor'))" :aria-expanded="openMenu === 'operation'" @click="openMenu = openMenu === 'operation' ? null : 'operation'"><el-icon><CircleCheck /></el-icon></button>
          <div v-if="openMenu === 'operation'" class="picker-menu operation-menu">
            <div class="menu-heading">任务操作</div>
            <button type="button" :disabled="!allows('canRerunSuccessor')" @click="prepareOperation('rerun')"><span><strong>再次运行</strong><small>在原任务下创建新 Run</small></span></button>
            <label>起始节点<select v-model="operationStep" aria-label="选择重跑节点"><option value="" disabled>选择一个节点</option><option v-for="step in state?.steps" :key="step.stepId" :value="step.stepId">{{ step.name }}</option></select></label>
            <button type="button" :disabled="!operationStep || !allows('canRerunSuccessor')" @click="prepareOperation('rerun_node')"><span><strong>从指定节点重跑</strong><small>重新执行该节点及其受影响的后续步骤</small></span></button>
            <button type="button" :disabled="!operationAllowed('recover')" @click="prepareOperation('recover')"><span><strong>恢复失败任务</strong><small>{{ offeredCapabilities?.retryMode === 'current_run' ? '在当前 Run 复用已提交结果，重试失败节点' : '在新 Run 复用已提交结果，重试失败节点' }}</small></span></button>
            <button type="button" :disabled="!draft.trim() || !allows('canCollaborate')" @click="prepareOperation('user_input')"><span><strong>提交补充要求</strong><small>将输入框中的要求交给 Planner 重新决策</small></span></button>
          </div>
        </div>
        <div class="composer-picker permission-picker" :class="{ 'is-auto-approval': permissionChoice === 'full' }" @keydown="onPermissionKeydown">
          <button type="button" class="picker-trigger" aria-label="选择权限" aria-haspopup="menu" :aria-expanded="openMenu === 'permission'" :aria-busy="settingPermission" :disabled="busy || loading || !state || readonly || historical || !allows('canSetPermission')" @click="openMenu = openMenu === 'permission' ? null : 'permission'"><el-icon :class="{ 'is-loading': settingPermission }"><Loading v-if="settingPermission" /><MagicStick v-else-if="permissionChoice === 'full'" /><Lock v-else /></el-icon><span>{{ settingPermission ? '正在设置…' : permissionLabel }}</span><el-icon class="chevron"><ArrowDown /></el-icon></button>
          <div v-if="openMenu === 'permission'" class="picker-menu permission-menu" role="menu" aria-label="任务助手权限">
            <div class="menu-heading">授权范围 · 整个任务</div>
            <button v-for="option in permissionOptions" :key="option.id" type="button" role="menuitemradio" :aria-checked="permissionChoice === option.id" @click="changePermission(option.permission, option.approvalMode)"><el-icon><Lock v-if="option.id === 'read_only'" /><MagicStick v-else-if="option.id === 'full'" /><CircleCheck v-else /></el-icon><span><strong>{{ option.label }}</strong><small>{{ option.description }}</small></span><el-icon v-if="permissionChoice === option.id" class="selected-check"><Check /></el-icon></button>
            <p>适用于本任务当前绑定的工作区授权。命令按当前系统用户权限执行。</p>
          </div>
        </div>
        <div class="composer-picker model-picker">
          <button type="button" class="picker-trigger" aria-label="选择对话模型" aria-haspopup="menu" :aria-expanded="openMenu === 'model'" :disabled="busy || !state || answering && !!state.question" @click="openMenu = openMenu === 'model' ? null : 'model'"><span :title="modelLabel">{{ modelLabel }}</span><small v-if="reasoningOptions.length">· {{ effortLabel(reasoningEffort) }}</small><el-icon class="chevron"><ArrowDown /></el-icon></button>
          <div v-if="openMenu === 'model'" class="picker-menu model-menu" role="menu" aria-label="对话模型">
            <div class="menu-heading">对话模型 <small>{{ availableModels.length }} 个可用</small></div>
            <button type="button" role="menuitemradio" :aria-checked="!selectedModel" @click="selectedModel = ''; openMenu = null"><span><strong>跟随任务模型</strong><small>{{ defaultModelLabel }}</small></span><el-icon v-if="!selectedModel" class="selected-check"><Check /></el-icon></button>
            <button v-for="model in availableModels" :key="model.id" type="button" role="menuitemradio" :aria-checked="selectedModel === model.id" @click="selectedModel = model.id; openMenu = null"><span><strong>{{ model.model }}</strong><small>{{ model.provider }}</small></span><el-icon v-if="selectedModel === model.id" class="selected-check"><Check /></el-icon></button>
            <div class="reasoning-controls"><div class="menu-heading">思考程度</div><div v-if="reasoningOptions.length" class="effort-options" role="group" aria-label="思考程度"><button v-for="effort in ['', ...reasoningOptions]" :key="effort" type="button" :aria-pressed="reasoningEffort === effort" @click="reasoningEffort = effort">{{ effortLabel(effort) }}</button></div><small v-else>此模型未声明可选的思考档位</small></div>
            <p>仅用于本次对话，不修改任务执行模型。</p>
          </div>
        </div>
        </template>
        <button class="send-button" type="submit" :disabled="!canSend" :aria-label="creating ? '发送任务' : answering && state?.question ? '提交回答并继续' : '发送消息'"><el-icon v-if="busy" class="is-loading"><Loading /></el-icon><el-icon v-else><ArrowUp /></el-icon></button>
      </div>
    </form>
    <slot v-if="creating" name="creation-notice" />
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { ArrowDown, ArrowRight, ArrowUp, ChatDotRound, Check, CircleCheck, Clock, Connection, Cpu, Loading, Lock, MagicStick, Share } from '@element-plus/icons-vue'
import { agentosApi, type GraphProjection, type WorkspaceEntry, type WorkspaceGraphNode, type ModelCallUsage, type RunActionCapabilities } from '@/services/api/agentos'
import { readRunCapabilities, recoveryCheckPending, type RunCapabilityAction } from '@/workbench/runtime/runCapabilities'
import type { CopilotPermission, CopilotPermissionChange, CopilotState, CopilotAction, CopilotActionKind, CopilotProgressPhase, TaskApprovalMode } from '@/services/api/agentos/api/copilot'
import { copilotResponseSummary, type CopilotConversationMessage } from './copilotConversation'
import { validationFailureDetails, type RuntimeObservation, type RuntimeTraceObservation } from '@/workbench/runtime/observation'
import { runningRecoveryMessage } from '@/features/workspace/runLifecycle'
import { renderMarkdown } from '@/utils/markdown'
import { renderCopilotMarkdown } from './copilotMarkdown'
import { clearCopilotSession, getCopilotSession, saveCopilotSession } from './copilotSessionCache'
import FormalExecutionControls from '@/components/workspace/FormalExecutionControls.vue'
import FormalToolApprovals from '@/components/workspace/FormalToolApprovals.vue'
import CopilotRunTimeline from './CopilotRunTimeline.vue'
import ChatTranscriptBlock from '@/components/ChatTranscriptBlock.vue'
import AgentPoolPanel from './AgentPoolPanel.vue'
import { createStreamBatcher, type TranscriptBlock } from '../../../../backend/src/shared/chat-stream/index.mjs'
import { useBrand } from '@/features/brand/useBrand'

const props = withDefaults(defineProps<{
  entry?: WorkspaceEntry | null; graphNode?: WorkspaceGraphNode | null; graphNodes?: WorkspaceGraphNode[]
  graph?: GraphProjection | null; runId?: string | null; runStatus?: string | null
  runtimeObservation?: RuntimeObservation | null; historical?: boolean; readonly?: boolean; actionCapabilities?: RunActionCapabilities | null
  createTask?: (message: string) => Promise<void>
  creationDisabled?: boolean
  creationPending?: boolean
  initialDraft?: string
  resourceStepId?: string
  missionId?: string; canCancel?: boolean; cancelPending?: boolean; projectionRevision?: number; workspaceRefreshing?: boolean
}>(), { entry: null, graphNode: null, graphNodes: () => [], graph: null, runId: null, runStatus: null, runtimeObservation: null, historical: false, readonly: false, missionId: '', canCancel: false, cancelPending: false })
const emit = defineEmits<{ 'select-run': [runId: string]; 'refresh-run': []; 'cancel-run': []; 'draft-change': [message: string] }>()
const creating = computed(() => !props.runId && Boolean(props.createTask))
const { activePack } = useBrand()
const controlRun = computed(() => props.runtimeObservation?.runId === props.runId ? props.runtimeObservation?.run || null : null)
const offeredCapabilities = computed(() => props.actionCapabilities === undefined ? controlRun.value?.actionCapabilities : props.actionCapabilities)
function allows(action: RunCapabilityAction) {
  const mutation = !['canInspect', 'canDiscuss'].includes(action)
  const caps = readRunCapabilities(offeredCapabilities.value, props.missionId || state.value?.missionId || controlRun.value?.missionId || '',
    props.runId, mutation ? state.value?.revision : undefined, mutation ? state.value?.status : undefined)
  return caps?.[action] === true && (!mutation || !props.historical && !props.readonly)
}
function proposalAllowed(action: CopilotAction, sourceRunId?: string) {
  const recoveryAllowed = action.kind !== 'recover' || action.stepId === offeredCapabilities.value?.retryStepId && (action.retryMode === 'current_run'
    ? allows('canRecoverCurrentRun') && offeredCapabilities.value?.retryMode === 'current_run'
    : (!action.retryMode || action.retryMode === 'successor_run') && allows('canRetrySuccessor')
      && offeredCapabilities.value?.retryMode === 'successor_run')
  return (!sourceRunId || sourceRunId === props.runId) && action.expectedRevision === offeredCapabilities.value?.runtimeRevision
    && recoveryAllowed && operationAllowed(action.kind)
}
function operationAllowed(kind: CopilotActionKind) {
  return kind === 'recover' ? allows('canRecoverCurrentRun') || allows('canRetrySuccessor')
    : allows(kind === 'user_input' ? 'canCollaborate' : 'canRerunSuccessor')
}
const hasFormalControl = computed(() => Boolean(controlRun.value?.formalControl || controlRun.value?.executionState?.planningCommitRequired))
const refreshRun = () => {
  refreshPending = true
  explicitRefreshPending = true
  accessDenied = false
  refreshFailures = 0
  emit('refresh-run')
  scheduleRefresh()
}
const state = ref<CopilotState | null>(null)
const hasPendingToolApproval = ref(false)
const toolApprovals = ref<InstanceType<typeof FormalToolApprovals> | null>(null)
// The workbench already refreshes durable execution facts. Reconcile approvals
// on that same cadence even when the transient event connection has stopped.
watch(() => props.runtimeObservation, observation => {
  if (observation?.runId === props.runId) void toolApprovals.value?.refresh()
}, { flush: 'post' })
const hasTimelineContent = ref(false)
const sessionOwnerId = localStorage.getItem('userId')
const tab = ref<'chat' | 'trace' | 'pool'>('chat')
const selectedAgentInstanceId = ref<string | null>(null)
const selectedResourceStepId = ref<string | null>(null)
function inspectAgent(instanceId: string) { selectedAgentInstanceId.value = instanceId; tab.value = 'pool' }
function inspectResourceStep(stepId: string) { selectedResourceStepId.value = stepId; tab.value = 'pool' }
watch(() => props.runId, () => { selectedAgentInstanceId.value = null; selectedResourceStepId.value = null })
watch(() => [props.runId, props.resourceStepId], () => {
  if (props.resourceStepId) inspectResourceStep(props.resourceStepId)
}, { immediate: true })
const draft = ref(''), error = ref(''), traceSearch = ref('')
const reviewComment = ref(''), reviewReceipt = ref('')
let reviewRequest: { subject: string; revision: string; decision: string; comment: string; id: string } | undefined
const loading = ref(false), busy = ref(false), answering = ref(false)
const messageList = ref<HTMLElement>(), composerInput = ref<HTMLTextAreaElement>()
const followBottom = ref(true)
const composerRoot = ref<HTMLElement>(), openMenu = ref<'model' | 'permission' | 'operation' | null>(null)
const operationStep = ref('')
const actionLabel = (kind: CopilotActionKind) => ({ rerun: '再次运行', rerun_node: '从指定节点重跑', recover: '恢复失败任务', user_input: '提交补充要求' })[kind]
const stepNames = (ids: string[]) => ids.map(id => state.value?.steps.find(s => s.stepId === id)?.name || id).join('、')
const receiptKey = (sourceRunId: string | undefined, proposalId: string) => `${sourceRunId || props.runId}:${proposalId}`
const receipts = computed(() => Object.fromEntries((state.value?.exchanges || []).filter(e => e.receipt).map(e => [receiptKey(e.sourceRunId, e.receipt!.proposalId), e.receipt!])))
const selectedModel = ref(''), permission = ref<CopilotPermission>('task_collaboration')
const approvalMode = ref<TaskApprovalMode>('ask'), settingPermission = ref(false), permissionReceipt = ref('')
let permissionRequest: { runId: string; permission: CopilotPermission; change: CopilotPermissionChange } | undefined
const reasoningEffort = ref(''), streamContent = ref(''), pendingUser = ref('')
const streamPhase = ref<CopilotProgressPhase>('preparing')
const streamPhaseText = computed(() => ({ preparing: '正在准备任务回复', waiting_model: '等待模型响应',
  receiving: '模型正在生成回复', retrying: '模型请求未完成，正在重试', validating: '正在校验并保存回复' })[streamPhase.value])
const streamBlock = computed<TranscriptBlock>(() => ({ id: 'copilot-current-reply', kind: 'text', state: 'streaming', text: streamContent.value }))
let streamBatcher: ReturnType<typeof createStreamBatcher> | undefined
const availableModels = computed(() => state.value?.models || [])
const reasoningOptions = computed(() => availableModels.value.find(m => m.id === (selectedModel.value || state.value?.defaultModelId))?.reasoningEfforts || [])
const effortLabel = (value: string) => ({ low: '低', medium: '中', high: '高', max: '最高' } as Record<string, string>)[value] || '关闭'
const defaultModelLabel = computed(() => availableModels.value.find(m => m.id === state.value?.defaultModelId)?.model || state.value?.defaultModelId?.split('/').slice(1).join('/') || (state.value?.modelAvailable ? '当前任务模型' : '尚未配置模型'))
const modelLabel = computed(() => answering.value && state.value?.question ? defaultModelLabel.value : selectedModel.value ? availableModels.value.find(m => m.id === selectedModel.value)?.model || '模型已不可用' : defaultModelLabel.value)
const permissionOptions = [
  { id: 'read_only', permission: 'read_only', approvalMode: 'ask', label: '仅对话', description: '查看状态、解释问题和提供建议；不暂停正在执行的任务' },
  { id: 'ask', permission: 'task_collaboration', approvalMode: 'ask', label: '按需确认', description: '继续协作，文件修改和命令执行按现有规则询问' },
  { id: 'full', permission: 'task_collaboration', approvalMode: 'full', label: '自动审批', description: '自动批准文件修改与命令执行，跨图版本和断点恢复持续有效，直到关闭' }
] satisfies { id: string; permission: CopilotPermission; approvalMode: TaskApprovalMode; label: string; description: string }[]
const permissionChoice = computed(() => permission.value === 'read_only' ? 'read_only' : approvalMode.value === 'full' ? 'full' : 'ask')
const permissionLabel = computed(() => permissionOptions.find(option => option.id === permissionChoice.value)!.label)
const modelCalls = ref<ModelCallUsage[]>([]), callCursor = ref<string | null>(null), callError = ref(''), callsLoading = ref(false)
let generation = 0, refreshSequence = 0, refreshTimer: ReturnType<typeof setTimeout> | undefined, controller: AbortController | undefined
let refreshPending = false, explicitRefreshPending = false, refreshing = false, accessDenied = false
let refreshFailures = 0
let validatedRunId: string | null = null
let viewActive = true
let viewSuspended = false
let requestKey: { content: string; target: string; id: string; options: string } | undefined
const targetTitle = computed(() => creating.value ? '新任务' : props.graphNode?.name || props.entry?.name || '当前任务')
const failedSteps = computed(() => state.value?.steps.filter(step => step.status === 'failed') || [])
const reviewKind = computed(() => state.value?.review?.kind || (state.value?.review?.decisionRejected ? 'planner_rejected' : state.value?.review?.subjectType === 'planner' ? 'planner_wait' : 'step_review'))
const reviewValidationDetails = computed(() => validationFailureDetails(state.value?.review?.validationFailures))
const reviewPending = computed(() => reviewKind.value === 'workspace_revision_pending')
const planningRepairing = computed(() => state.value?.planningProgress?.kind === 'repairing')
const reviewCanApprove = computed(() => !recoveryCheckPending(offeredCapabilities.value) && !allows('canRecoverCurrentRun') && state.value?.review?.canApprove === true && !state.value.review.decisionRejected && !['workspace_revision_pending', 'workspace_revision_blocked', 'planner_rejected'].includes(reviewKind.value))
const reviewTitle = computed(() => allows('canRecoverCurrentRun') ? '节点执行失败，可以局部恢复' : ({ workspace_revision_pending: '正在自动修订审查计划', workspace_revision_blocked: '审查计划修订受阻', planner_wait: '等待外部条件确认', planner_error: '规划处理失败', step_review: '请审核当前步骤的结果' } as Record<string, string>)[reviewKind.value]
  || (state.value?.review?.reasonCode === 'PLANNING_COMMIT_REJECTED' ? '计划修订未通过校验' : state.value?.decision?.action === 'recover' ? '任务暂停，未能自动恢复' : '任务暂停，下一步尚未执行'))
const reviewDescription = computed(() => allows('canRecoverCurrentRun') ? '已完成的结果和工具证据已保留。打开输入框下方的任务操作，选择“恢复失败任务”，继续处理失败节点。' : state.value?.review?.displayReason || (reviewPending.value
  ? '系统正在处理审查计划的自动修订，完成正式校验后会继续执行。'
  : reviewKind.value === 'workspace_revision_blocked' ? '审查计划修订未通过正式校验，任务仍处于暂停状态。请先查看受阻原因和已有执行记录。'
  : reviewKind.value === 'planner_rejected' ? '系统未能执行建议的处理方案，任务仍处于暂停状态。请先查看失败详情和已有执行记录，再决定需要补充的材料或调整要求。'
  : reviewKind.value === 'planner_error' ? '系统未能生成有效的下一步决策，已有结果已保留。可以重新规划。'
  : reviewKind.value === 'planner_wait' ? '确认下方说明中的外部等待条件已满足后，系统会重新判断能否继续执行。'
  : '请检查当前步骤的结果。批准后继续执行后续工作；拒绝将结束本次运行，保留已有记录。'))
const statusLabel = computed(() => {
  const run = controlRun.value, current = state.value
  const observedStatus = run?.status
    || (props.runtimeObservation?.runId === props.runId ? props.runtimeObservation.runStatus : null)
  // `CopilotState.revision` and `WorkflowRun.runtimeRevision` are the same
  // durable Run revision.  Treat an observation at the same revision as
  // authoritative too: an equal revision with a different lifecycle status
  // is exactly the stale Copilot projection case (for example, the Run has
  // entered waiting_review while the conversation still says running).
  // Strict `>` left that state showing the old "执行中" label indefinitely.
  // A few legacy observations omit runtimeRevision.  In that case a durable
  // review/terminal status still outranks an active Copilot projection, while
  // an unversioned active observation is kept as a temporary hint.
  const activeStatuses = ['pending', 'planning', 'running', 'retrying', 'waiting_review']
  const durableReviewOrTerminal = ['waiting_review', 'completed', 'failed', 'cancelled', 'superseded']
  const hasRunRevision = typeof run?.runtimeRevision === 'number' && Number.isFinite(run.runtimeRevision)
  const versionedRun = hasRunRevision && run!.runtimeRevision! >= (current?.revision ?? -1)
  const unversionedRun = !hasRunRevision
    && durableReviewOrTerminal.includes(observedStatus || '')
    && (!current || activeStatuses.includes(current.status))
  const newerRun = versionedRun || unversionedRun
  const recoveryMessage = !current || current.status === run?.status || newerRun
    ? runningRecoveryMessage(run) : null
  const status = versionedRun && run ? run.status : unversionedRun ? observedStatus : current?.status || props.runStatus || ''
  return recoveryMessage || (hasPendingToolApproval.value ? '等待你确认'
    : !newerRun && current?.planningProgress?.kind === 'blocked' ? '图交接受阻'
    : !newerRun && planningRepairing.value ? '自动修正中'
    : ({ pending: '等待执行', planning: '规划中', running: '执行中', retrying: '准备恢复',
      waiting_review: current?.question ? '等待你的回答' : reviewPending.value ? '自动修订中' : reviewKind.value === 'workspace_revision_blocked' ? '修订受阻' : '已暂停',
      completed: '已完成', failed: '执行失败', cancelled: '已取消', superseded: '已替换' } as Record<string, string>)[status] || '尚未启动')
})
const composerPlaceholder = computed(() => creating.value ? '输入任务，描述你想完成的事情…' : !props.runId ? '先选择一项任务' : answering.value && state.value?.question ? '补充你的选择或信息，让任务继续…' : '询问当前任务，或一起梳理下一步…')
const canSend = computed(() => creating.value
  ? Boolean(draft.value.trim()) && !busy.value && !props.creationPending && !props.creationDisabled
    && !props.readonly && !props.historical
  : !!props.runId && !!state.value && allows('canDiscuss') && !loading.value && !busy.value && !!draft.value.trim() && (answering.value && state.value.question && allows('canAnswerPlanner') ? permission.value === 'task_collaboration' : selectedModel.value ? availableModels.value.some(m => m.id === selectedModel.value) : state.value.modelAvailable))
const messages = computed<CopilotConversationMessage[]>(() => [
  ...(state.value?.exchanges || []).flatMap(e => [ ...(e.user ? [{ id: `${e.sourceRunId || props.runId}:${e.operationId}-u`, role: 'user', content: e.user, time: e.createdAt, planner: false, action: undefined, receipt: undefined, proposalId: e.operationId, sourceRunId: e.sourceRunId || props.runId || undefined }] : []), { id: `${e.sourceRunId || props.runId}:${e.operationId}-a`, role: 'assistant', content: e.assistant, time: e.createdAt, planner: false, action: e.action, receipt: e.receipt, proposalId: e.operationId, sourceRunId: e.sourceRunId || props.runId || undefined, responseTimings: e.responseTimings, latencyMs: e.latencyMs, providerRequest: e.providerRequest, contextUsage: e.contextUsage }]),
  ...(state.value?.humanAnswers || []).flatMap(a => [{ id: `${a.questionId}-q`, role: 'assistant', content: a.prompt, time: a.answeredAt, planner: true, action: undefined, receipt: undefined, proposalId: '', sourceRunId: a.sourceRunId }, { id: `${a.questionId}-r`, role: 'user', content: a.answer, time: a.answeredAt, planner: true, action: undefined, receipt: undefined, proposalId: '', sourceRunId: a.sourceRunId }])
].sort((a, b) => a.time.localeCompare(b.time)))
let markupCache = new Map<string, { text: string; html: string }>()
const messageMarkup = computed(() => {
  const next = new Map<string, { text: string; html: string }>()
  for (const message of messages.value) {
    const previous = markupCache.get(message.id)
    next.set(message.id, previous?.text === message.content ? previous : { text: message.content, html: (message.role === 'assistant' ? renderCopilotMarkdown : renderMarkdown)(message.content) })
  }
  markupCache = next
  return new Map([...next].map(([id, rendered]) => [id, rendered.html]))
})
const lanes = ['planner', 'model', 'tool', 'execution']
const laneLabel = (kind: string) => ({ planner: '规划', model: '模型', tool: '工具', execution: '执行' } as Record<string, string>)[kind] || kind
const traceSource = computed(() => props.runtimeObservation?.runId === props.runId ? props.runtimeObservation.traces : [])
const callsById = computed(() => new Map(modelCalls.value.map(call => [call.callId, call])))
const traceCallId = (event: RuntimeTraceObservation) => event.eventType === 'model_called'
  ? event.eventId : event.eventType.includes('model') ? String(event.payload?.callId || '') : ''
const standaloneTraces = computed(() => [...new Map(traceSource.value.map(event => [event.eventId, event])).values()]
  .filter(event => !callsById.value.has(traceCallId(event))))
const trajectoryCount = computed(() => standaloneTraces.value.length + callsById.value.size)
// Model projections share one index; building summaries never reads their payloads in full.
const modelTraceIndex = computed(() => {
  const index = new Map<string, RuntimeTraceObservation[]>()
  for (const event of traceSource.value) {
    const callId = traceCallId(event)
    if (!callId) continue
    const events = index.get(callId)
    if (events) events.push(event)
    else index.set(callId, [event])
  }
  return index
})
const trajectory = computed(() => {
  const calls = [...callsById.value.values()].map(c => ({
    id: `model:${c.callId}`, kind: 'model', title: `${c.model || '模型调用'} · ${c.usage.totalTokens} tokens`, time: c.createdAt || null,
    step: [c.stepId || 'Run', c.callChainId ? `调用链 ${c.callChainId}${c.partIndex != null ? ` · part ${c.partIndex}` : ''}` : ''].filter(Boolean).join(' → '),
    duration: c.latencyMs, detail: () => JSON.stringify({ ...c, trace: modelTraceIndex.value.get(c.callId) || [] }, null, 2) }))
  const traces = standaloneTraces.value.map(e => {
    const p = e.payload || {}
    const kind = p.category === 'planner' || p.planningProgress === true || String(p.runtimeEvent || '').startsWith('planner.')
      ? 'planner' : e.eventType.includes('model') ? 'model' : e.eventType.includes('tool') ? 'tool' : 'execution'
    return { id: e.eventId, kind, title: e.observation || e.eventType, time: e.timestamp, step: e.stepId, duration: e.durationMs,
      detail: () => JSON.stringify(p, null, 2).slice(0, 12000) }
  })
  return [...traces, ...calls].sort((a, b) => (a.time || '').localeCompare(b.time || ''))
})
const filteredTrajectory = computed(() => trajectory.value.filter(e => `${e.title} ${e.step || ''} ${laneLabel(e.kind)}`.toLowerCase().includes(traceSearch.value.trim().toLowerCase())))
const expandedTrajectory = ref(new Set<string>())
const trajectoryDetails = computed(() => tab.value === 'trace'
  ? new Map(filteredTrajectory.value.filter(event => expandedTrajectory.value.has(event.id)).map(event => [event.id, event.detail()]))
  : new Map<string, string>())
function toggleTrajectoryDetail(id: string, event: Event) {
  if ((event.currentTarget as HTMLDetailsElement).open) expandedTrajectory.value.add(id)
  else expandedTrajectory.value.delete(id)
}
const laneCounts = computed<Record<string, number>>(() => Object.fromEntries(lanes.map(lane => [lane,
  filteredTrajectory.value.filter(e => e.kind === lane).length])))
const formatTime = (value?: string | null) => value ? new Date(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : ''
function focusComposer() { void nextTick(() => composerInput.value?.focus()) }
function trackScroll() { const e = messageList.value; if (e) followBottom.value = e.scrollHeight - e.scrollTop - e.clientHeight < 80 }
function scrollBottom() { if (followBottom.value) void nextTick(() => { const e = messageList.value; if (e) e.scrollTop = e.scrollHeight }) }
function errorMessage(e: any) { return typeof e?.response?.data?.detail === 'string' ? e.response.data.detail : e?.response?.data?.message || e?.message || '连接暂时不可用，请重试。你的输入已保留。' }
async function changePermission(value: CopilotPermission, mode: TaskApprovalMode = 'ask') {
  if (!props.runId || busy.value || loading.value || !state.value || validatedRunId !== props.runId || !allows('canSetPermission')) return
  const token = generation
  const effectiveMode = value === 'read_only' ? 'ask' : mode
  if (!permissionRequest || permissionRequest.runId !== props.runId || permissionRequest.permission !== value || permissionRequest.change.approvalMode !== effectiveMode) {
    permissionRequest = { runId: props.runId, permission: value, change: {
      approvalMode: effectiveMode, expectedPolicyRevision: state.value.policyRevision ?? 0, operationId: crypto.randomUUID(),
    } }
  }
  const request = permissionRequest
  busy.value = true; settingPermission.value = true; openMenu.value = null; error.value = ''; permissionReceipt.value = ''
  try {
    const result = await agentosApi.setCopilotPermission(request.runId, request.permission, request.change)
    if (token !== generation) return
    if (props.missionId && result.missionId !== props.missionId) throw new Error('任务授权身份不匹配，请刷新后重试。')
    permissionRequest = undefined
    // A receipt can arrive after a newer policy snapshot from another client.
    if ((result.policyRevision ?? 0) >= (state.value?.policyRevision ?? 0)) {
      permission.value = result.taskPermission; approvalMode.value = result.approvalMode ?? 'ask'
      if (state.value) Object.assign(state.value, { taskPermission: result.taskPermission, approvalMode: approvalMode.value,
        policyRevision: result.policyRevision ?? 0, approvalPolicy: result.approvalPolicy })
      permissionReceipt.value = approvalMode.value === 'full'
        ? `已开启自动审批，已处理 ${result.autoApprovedCount ?? 0} 项待审批操作`
        : '后续操作将按需确认'
    }
    void toolApprovals.value?.refresh()
    emit('refresh-run')
  } catch (e: any) {
    if (token === generation) {
      error.value = errorMessage(e)
      // A rejected compare-and-set has no unknown result to replay.
      if (e?.response?.status === 409) { permissionRequest = undefined; refreshPending = true }
    }
  } finally {
    if (token === generation) { busy.value = false; settingPermission.value = false; if (refreshPending) scheduleRefresh() }
  }
}
function onPermissionKeydown(event: KeyboardEvent) {
  if (!['ArrowDown', 'ArrowUp', 'Home', 'End', 'Escape'].includes(event.key)) return
  const root = event.currentTarget as HTMLElement
  const trigger = root.querySelector<HTMLButtonElement>('.picker-trigger')
  if (trigger?.disabled) return
  event.preventDefault(); event.stopPropagation()
  if (event.key === 'Escape') { openMenu.value = null; trigger?.focus(); return }
  const wasOpen = openMenu.value === 'permission'
  openMenu.value = 'permission'
  void nextTick(() => {
    const options = Array.from(root.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]'))
    const current = options.indexOf(document.activeElement as HTMLButtonElement)
    const selected = options.findIndex(option => option.getAttribute('aria-checked') === 'true')
    const index = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1 : !wasOpen || current < 0
      ? Math.max(0, selected) : (current + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length
    options[index]?.focus()
  })
}
async function refresh(silent = false) {
  const id = props.runId, token = generation
  if (!id) return
  silent = silent && !explicitRefreshPending
  explicitRefreshPending = false
  stopScheduledRefresh()
  const request = ++refreshSequence
  const revision = props.projectionRevision
  refreshing = true
  refreshPending = false
  // An existing, validated snapshot remains usable while its replacement loads.
  if (!silent && (!state.value || validatedRunId !== id)) loading.value = true
  try {
    const next = await agentosApi.getCopilot(id, controller?.signal)
    if (token !== generation || request !== refreshSequence) return
    if (next.runId !== id || (next.missionId && props.missionId && next.missionId !== props.missionId)) throw new Error('任务对话身份不匹配，请刷新后重试。')
    validatedRunId = id
    accessDenied = false
    refreshFailures = 0
    refreshPending = refreshPending || props.projectionRevision !== revision
    const changedQuestion = next.question?.questionId !== state.value?.question?.questionId
    // Policy revisions are independent of the Run revision. A GET started before
    // a successful setting must not roll its authority back when it arrives.
    if ((next.policyRevision ?? 0) < (state.value?.policyRevision ?? 0)) {
      Object.assign(next, { taskPermission: state.value?.taskPermission, approvalMode: state.value?.approvalMode,
        policyRevision: state.value?.policyRevision, approvalPolicy: state.value?.approvalPolicy })
    }
    state.value = next
    if (next.taskPermission) permission.value = next.taskPermission
    approvalMode.value = next.approvalMode ?? 'ask'
    if (requestKey && next.exchanges.some(e => e.operationId === requestKey?.id)) { draft.value = ''; requestKey = undefined }
    if (changedQuestion) { answering.value = !!next.question; requestKey = undefined }
    if (!silent) error.value = ''
    scrollBottom()
    if (tab.value === 'trace' && !silent) void loadCalls()
  } catch (e: any) {
    if (token === generation && request === refreshSequence && e?.code !== 'ERR_CANCELED') {
      error.value = errorMessage(e)
      refreshFailures++
      const status = e?.response?.status
      refreshPending = refreshFailures <= 2 && (!status || status >= 500)
      if ([401, 403, 404].includes(status)) { accessDenied = true; validatedRunId = null; state.value = null; clearCopilotSession(id) }
    }
  }
  finally { if (token === generation && request === refreshSequence) { loading.value = false; refreshing = false; scheduleRefresh() } }
}

function stopScheduledRefresh() { clearTimeout(refreshTimer); refreshTimer = undefined }
function scheduleRefresh(delay = 150) {
  if (!refreshPending || !viewActive || document.hidden || busy.value || refreshing || props.workspaceRefreshing || accessDenied || !props.runId || refreshTimer) return
  // Consume the Mission subscription already owned by the workbench. A burst
  // requests at most one read, plus one follow-up if it changed during the read.
  refreshTimer = setTimeout(() => {
    refreshTimer = undefined
    if (refreshPending && viewActive && !document.hidden && !busy.value && !refreshing && !props.workspaceRefreshing && !accessDenied) void refresh(true)
  }, refreshFailures ? 1000 * refreshFailures : delay)
}
watch(() => props.projectionRevision, (revision, previous) => {
  if (!Number.isSafeInteger(revision) || revision! < 0 || (previous !== undefined && revision! <= previous)) return
  refreshPending = true
  refreshFailures = 0
  scheduleRefresh()
})
watch(busy, value => { if (!value) scheduleRefresh() })
// Formal receipts and the workspace watermark share the same pending read.
// Wait for the parent's projection so one conversation read covers both.
watch(() => props.workspaceRefreshing, value => {
  if (value) return
  // Read the committed snapshot before the next throttled workspace refresh;
  // continuous runtime events must not keep postponing the conversation.
  stopScheduledRefresh()
  scheduleRefresh(0)
})
function onVisibilityChange() {
  if (document.hidden) stopScheduledRefresh()
  else if (viewActive) { refreshPending = true; scheduleRefresh() }
}
async function loadCalls(more = false) {
  const id = props.runId, token = generation
  if (!id || callsLoading.value) return
  callsLoading.value = true
  try {
    const page = await agentosApi.listRunResourceCalls(id, { cursor: more ? callCursor.value || undefined : undefined, pageSize: 50 }, { signal: controller?.signal })
    if (token !== generation) return
    modelCalls.value = more ? [...modelCalls.value, ...page.items] : page.items
    callCursor.value = page.nextCursor || null; callError.value = ''
  } catch (e: any) { if (token === generation && e?.code !== 'ERR_CANCELED') callError.value = '模型调用记录暂时不可用，仍可查看运行事件。' }
  finally { if (token === generation) callsLoading.value = false }
}
async function send() {
  if (creating.value) {
    if (!canSend.value) return
    const token = generation
    busy.value = true
    error.value = ''
    try {
      await props.createTask!(draft.value.trim())
    } catch (cause) {
      if (token === generation) error.value = cause instanceof Error ? cause.message : '任务创建失败，请重试'
    } finally {
      if (token === generation) busy.value = false
    }
    return
  }
  if (!canSend.value || !state.value || !props.runId) return
  const id = props.runId, token = generation, content = draft.value.trim(), question = answering.value && allows('canAnswerPlanner') ? state.value.question : null
  const target = question?.questionId || 'chat'
  const options = JSON.stringify([question ? '' : selectedModel.value, permission.value, reasoningEffort.value])
  if (!requestKey || requestKey.content !== content || requestKey.target !== target || requestKey.options !== options) requestKey = { content, target, options, id: crypto.randomUUID() }
  const operationId = requestKey.id
  openMenu.value = null
  busy.value = true; error.value = ''; followBottom.value = true; tab.value = 'chat'
  pendingUser.value = content; streamContent.value = ''; streamPhase.value = 'preparing'
  let receivedContent = ''
  const batcher = createStreamBatcher(event => {
    if (token !== generation) return
    streamContent.value += event.data.delta
    scrollBottom()
  })
  streamBatcher = batcher
  try {
    if (question) await agentosApi.answerPlanner(id, question.questionId, content, state.value.revision, operationId, permission.value)
    else {
      const exchange = await agentosApi.streamCopilotMessage(id, content, operationId, event => {
        if (token !== generation) return
        if (event.type === 'content') {
          const next = event.content || ''
          if (!next.startsWith(receivedContent)) { batcher.flush(); streamContent.value = ''; receivedContent = '' }
          batcher.accept({ event: 'content_delta', requestId: operationId, data: { delta: next.slice(receivedContent.length), attemptId: event.attemptId } })
          receivedContent = next
        } else {
          batcher.flush()
          if (event.type === 'progress' && event.phase) streamPhase.value = event.phase
        }
      }, controller?.signal, { ...(selectedModel.value ? { modelId: selectedModel.value } : {}), permission: !allows('canCollaborate') ? 'read_only' : permission.value, ...(reasoningEffort.value ? { reasoningEffort: reasoningEffort.value } : {}) })
      if (token === generation && !state.value.exchanges.some(e => e.operationId === exchange.operationId)) state.value.exchanges.push(exchange)
      if (token === generation) { pendingUser.value = ''; streamContent.value = '' }
    }
    if (token !== generation) return
    draft.value = ''; requestKey = undefined
    await refresh()
  } catch (e) { if (token === generation) { error.value = errorMessage(e); if ((e as any)?.response?.status === 409) await refresh(true) } }
  finally { if (token === generation) batcher.flush(); batcher.dispose(); if (streamBatcher === batcher) streamBatcher = undefined; if (token === generation) { busy.value = false; streamContent.value = ''; pendingUser.value = '' } }
}
async function prepareOperation(kind: CopilotActionKind) {
  if (!state.value || !props.runId || busy.value || !operationAllowed(kind) || permission.value !== 'task_collaboration') return
  const id = props.runId, token = generation
  const stepId = kind === 'rerun_node' ? operationStep.value : undefined
  const content = kind === 'user_input' ? draft.value.trim() : `${actionLabel(kind)}${stepId ? `：${stepNames([stepId])}` : ''}`
  if (!content) return
  const target = `operation:${kind}:${stepId || ''}`, options = permission.value
  if (!requestKey || requestKey.content !== content || requestKey.target !== target || requestKey.options !== options) requestKey = { content, target, options, id: crypto.randomUUID() }
  busy.value = true; error.value = ''; openMenu.value = null
  try {
    const exchange = await agentosApi.previewCopilotAction(id, kind, content, requestKey.id, permission.value, stepId)
    if (token !== generation) return
    if (!state.value.exchanges.some(e => e.operationId === exchange.operationId)) state.value.exchanges.push(exchange)
    requestKey = undefined; if (kind === 'user_input') draft.value = ''
    followBottom.value = true; scrollBottom()
  } catch (e) { if (token === generation) error.value = errorMessage(e) }
  finally { if (token === generation) busy.value = false }
}
async function submitReviewInput() {
  if (!reviewComment.value.trim()) return
  draft.value = reviewComment.value.trim()
  await prepareOperation('user_input')
  tab.value = 'chat'
}
async function submitReview(decision: 'approved' | 'rejected') {
  const review = state.value?.review, id = props.runId, token = generation
  if (!review || !id || busy.value || !allows('canReview') || permission.value !== 'task_collaboration' || reviewPending.value || (decision === 'approved' && !reviewCanApprove.value)) return
  const comment = reviewComment.value.trim()
  if (!reviewRequest || reviewRequest.subject !== review.subjectId || reviewRequest.revision !== review.expectedRunUpdatedAt || reviewRequest.decision !== decision || reviewRequest.comment !== comment) reviewRequest = { subject: review.subjectId, revision: review.expectedRunUpdatedAt, decision, comment, id: crypto.randomUUID() }
  busy.value = true; error.value = ''
  try {
    await agentosApi.applyWorkflowReview(id, { stepId: review.subjectId, decision, comment, operationId: reviewRequest.id, expectedRunUpdatedAt: review.expectedRunUpdatedAt })
    if (token !== generation) return
    reviewReceipt.value = decision === 'approved' ? review.kind === 'planner_error' ? '重新规划已提交，正在判断下一步。' : '审核已提交，正在重新判断下一步。' : '已拒绝，本次运行已结束。'
    reviewRequest = undefined; reviewComment.value = ''
    await refresh(true)
  } catch (e) { if (token === generation) { error.value = errorMessage(e); await refresh(true) } }
  finally { if (token === generation) busy.value = false }
}
async function confirmAction(proposalId: string, action: CopilotAction, sourceRunId?: string) {
  if (!props.runId || busy.value || !proposalAllowed(action, sourceRunId) || permission.value !== 'task_collaboration') return
  const id = props.runId, token = generation
  busy.value = true; error.value = ''
  try {
    const receipt = await agentosApi.applyCopilotAction(sourceRunId || id, proposalId, action.expectedRevision, permission.value)
    if (token !== generation) return
    if (state.value && !state.value.exchanges.some(e => e.operationId === receipt.operationId)) state.value.exchanges.push(receipt)
    await refresh(true); scrollBottom()
  } catch (e) { if (token === generation) { error.value = errorMessage(e); await refresh(true) } }
  finally { if (token === generation) busy.value = false }
}
watch(() => props.graphNode?.acgNodeId || props.entry?.acgNodeId, id => { operationStep.value = id || '' }, { immediate: true })
function onKeydown(e: KeyboardEvent) { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); void send() } }
function saveSession(id = props.runId) { if (id && state.value) saveCopilotSession(id, { state: state.value, draft: draft.value, model: selectedModel.value, permission: permission.value, effort: reasoningEffort.value, operation: requestKey }, sessionOwnerId) }
watch(() => props.runId, (_next, previous) => {
  saveSession(previous)
  generation++; controller?.abort(); controller = new AbortController(); stopScheduledRefresh()
  streamBatcher?.dispose(); streamBatcher = undefined
  refreshing = false; refreshPending = false; explicitRefreshPending = false; accessDenied = false; refreshFailures = 0
  validatedRunId = null
  hasPendingToolApproval.value = false
  hasTimelineContent.value = false
  state.value = null; draft.value = creating.value ? props.initialDraft || '' : ''; error.value = ''; busy.value = false; requestKey = undefined; answering.value = false
  reviewComment.value = ''; reviewReceipt.value = ''; reviewRequest = undefined
  approvalMode.value = 'ask'; settingPermission.value = false; permissionReceipt.value = ''; permissionRequest = undefined
  selectedModel.value = ''; permission.value = 'task_collaboration'; openMenu.value = null
  reasoningEffort.value = ''; streamContent.value = ''; pendingUser.value = ''
  modelCalls.value = []; callCursor.value = null; callError.value = ''; callsLoading.value = false
  expandedTrajectory.value.clear()
  const cached = props.runId ? getCopilotSession(props.runId) : undefined
  if (cached) { state.value = cached.state; draft.value = cached.draft; selectedModel.value = cached.model; permission.value = cached.permission; approvalMode.value = cached.state.approvalMode ?? 'ask'; reasoningEffort.value = cached.effort; requestKey = cached.operation; answering.value = !!cached.state.question }
  void refresh()
}, { immediate: true })
watch(tab, value => { if (value === 'trace') void loadCalls() })
watch(reasoningOptions, options => { if (!options.includes(reasoningEffort.value)) reasoningEffort.value = '' })
watch(draft, value => { if (creating.value) emit('draft-change', value) }, { flush: 'sync' })
watch(draft, () => void nextTick(() => { const e = composerInput.value; if (e) { e.style.height = 'auto'; e.style.height = `${Math.min(180, Math.max(76, e.scrollHeight))}px` } }))
function closePickers(e: PointerEvent) { if (!composerRoot.value?.contains(e.target as Node)) openMenu.value = null }
onMounted(() => { document.addEventListener('pointerdown', closePickers); document.addEventListener('visibilitychange', onVisibilityChange) })
onDeactivated(() => { viewActive = false; viewSuspended = true; stopScheduledRefresh(); document.removeEventListener('pointerdown', closePickers); document.removeEventListener('visibilitychange', onVisibilityChange) })
onActivated(() => { if (!viewSuspended) return; viewSuspended = false; viewActive = true; document.addEventListener('pointerdown', closePickers); document.addEventListener('visibilitychange', onVisibilityChange); refreshPending = true; if (!busy.value && !refreshing) void refresh(true) })
onBeforeUnmount(() => { saveSession(); generation++; controller?.abort(); stopScheduledRefresh(); streamBatcher?.dispose(); document.removeEventListener('pointerdown', closePickers); document.removeEventListener('visibilitychange', onVisibilityChange) })
</script>

<style scoped>
.planning-progress--blocked { margin: 8px 0; padding: 10px 12px; border: 1px solid var(--wb-border-soft, var(--border-light)); border-radius: 6px; color: var(--sem-waiting, var(--text-secondary)); font-size: 12px; }
.planning-progress--blocked p { margin: 0 0 6px; line-height: 1.7; overflow-wrap: anywhere; }
.planning-progress--blocked summary { cursor: pointer; color: var(--text-secondary); font-size: 11px; }
.planning-progress--blocked details p { margin-top: 8px; font-size: 11px; }
.review-card { margin: 16px 0; padding: 18px; border: 1px solid var(--cp-border); border-radius: 12px; background: var(--wb-surface-section); font-size: 13px; line-height: 1.7; }
.review-card strong { color: var(--wb-text); }
.review-card p { margin: 10px 0; }
.review-card details { color: var(--wb-text-secondary); margin: 12px 0; }
.review-card textarea { box-sizing: border-box; width: 100%; padding: 10px; border: 1px solid var(--cp-border); border-radius: 8px; background: transparent; color: inherit; resize: vertical; font: inherit; }
.review-actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.review-actions button { padding: 7px 10px; border: 1px solid var(--cp-border); border-radius: 7px; background: var(--wb-accent-soft); color: var(--wb-accent); cursor: pointer; }
.review-actions button:disabled { opacity: .45; cursor: not-allowed; }
.acg-copilot { display:flex; flex-direction:column; width:100%; height:100%; min-height:0; color:var(--wb-text); background:var(--wb-surface-1); font-family:var(--font-sans,sans-serif); --cp-border:var(--wb-border-soft); --cp-prose-size:14px; --cp-prose-line-height:1.75; --cp-paragraph-gap:.45em; --cp-list-item-gap:.2em; }
.agent-pool ~ .composer, .agent-pool ~ .error-note, .agent-pool ~ .readonly-note, .agent-pool ~ .wait-note { display:none; }
button { font:inherit; cursor:pointer; }
button:disabled { cursor:not-allowed; opacity:.4; }
button:focus-visible, input:focus-visible { outline:2px solid var(--wb-accent); outline-offset:2px; }
.context-strip { display:flex; align-items:center; gap:7px; margin:0 14px 12px; padding-top:13px; font-size:11px; color:var(--wb-text-muted); }
.context-strip > span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0; }
.context-strip > small { margin-left:auto; flex-shrink:0; color:var(--wb-text-secondary); background:var(--wb-surface-section); padding:3px 7px; border-radius:5px; font-size:10px; }
.copilot-tabs { display:flex; gap:22px; padding:0 16px; border-bottom:1px solid var(--cp-border); }
.copilot-tabs button { position:relative; padding:0 0 10px; border:0; color:var(--wb-text-muted); background:transparent; font-size:12px; }
.copilot-tabs button.active { color:var(--wb-text); }
.copilot-tabs button.active::after { content:''; position:absolute; left:0; right:0; bottom:-1px; height:2px; background:var(--wb-accent); border-radius:2px; }
.copilot-tabs small { margin-left:4px; font:10px var(--font-mono,monospace); }
.attention-dot { display:inline-block; width:5px; height:5px; border-radius:50%; margin-left:4px; background:var(--wb-accent); }
.conversation,.trajectory-view { flex:1; min-height:0; overflow:auto; padding:18px 16px; }
.empty-state { display:flex; flex-direction:column; align-items:center; justify-content:center; text-align:center; min-height:230px; height:100%; color:var(--wb-text-muted); }
.conversation.has-run-controls > .empty-state { height:auto; min-height:180px; padding:24px 0; }
.empty-watermark { display:block; width:148px; height:148px; object-fit:contain; margin-bottom:6px; animation:copilot-watermark-pulse 3.2s ease-in-out infinite; }
.empty-state h3 { margin:0 0 7px; color:var(--wb-text); font-size:14px; font-weight:650; }
.empty-state p { margin:0; max-width:280px; color:var(--wb-text-secondary); font-size:12px; line-height:1.65; }
.message { margin-bottom:24px; min-width:0; }
.message-meta { display:flex; align-items:center; gap:6px; margin-bottom:8px; color:var(--wb-text-muted); font-size:10px; }
.message-meta > .el-icon { color:var(--wb-accent); }
.message-meta time { margin-left:auto; font:9px var(--font-mono,monospace); }
.message-meta small { color:var(--wb-accent); font-size:9px; }
.stream-activity { display:flex; align-items:center; gap:7px; color:var(--wb-text-muted); font-size:11px; }
.stream-turn { margin-bottom:24px; }
.streaming-content { min-height:24px; }
.response-stats { display:block; margin-top:8px; color:var(--wb-text-muted); font-size:10px; }
.message.is-user { width:fit-content; max-width:92%; margin-left:auto; padding:10px 13px; border-radius:12px; background:var(--wb-surface-section); border:1px solid var(--cp-border); }
.message-content { color:var(--wb-text-secondary); font-size:var(--cp-prose-size); line-height:var(--cp-prose-line-height); overflow-wrap:anywhere; text-wrap:pretty; }
/* One prose rhythm for replies, streamed step output and planner thoughts. */
.conversation :deep(.markdown-body) { line-height:var(--cp-prose-line-height); white-space:normal; text-wrap:pretty; }
.conversation :deep(.markdown-body p) { margin:0 0 var(--cp-paragraph-gap); color:inherit; }
.conversation :deep(.markdown-body ul), .conversation :deep(.markdown-body ol) { margin:var(--cp-paragraph-gap) 0; padding-left:1.5em; color:inherit; }
.conversation :deep(.markdown-body li) { margin:var(--cp-list-item-gap) 0; color:inherit; }
.conversation :deep(.markdown-body li > p) { margin:.25em 0; }
.conversation :deep(.markdown-body h1), .conversation :deep(.markdown-body h2), .conversation :deep(.markdown-body h3),
.conversation :deep(.markdown-body h4), .conversation :deep(.markdown-body h5), .conversation :deep(.markdown-body h6) { margin:1.1em 0 .5em; line-height:1.4; color:var(--wb-text); }
.conversation :deep(.markdown-body > :first-child) { margin-top:0; }
.conversation :deep(.markdown-body > :last-child) { margin-bottom:0; }
.conversation :deep(.markdown-body strong) { color:var(--wb-text); font-weight:600; }
.message-content :deep(p:last-child) { margin-bottom:0; }
.question-card { margin:8px 0 18px; padding:14px; border:1px solid color-mix(in srgb,var(--wb-accent) 45%,var(--cp-border)); border-radius:12px; background:color-mix(in srgb,var(--wb-accent) 4%,var(--wb-surface-section)); }
.operation-card { margin-top:12px; padding:12px; border:1px solid var(--cp-border); border-radius:10px; background:var(--wb-surface-section); font-size:12px; }
.operation-card p { margin:9px 0; line-height:1.7; overflow-wrap:anywhere; }
.operation-card small { display:block; color:var(--wb-text-muted); line-height:1.6; }
.operation-card button,.operation-receipt button { margin-top:10px; padding:7px 10px; border:1px solid var(--cp-border); border-radius:6px; background:var(--wb-accent-soft); color:var(--wb-accent); font-size:11px; }
.operation-receipt { display:flex; gap:10px; align-items:center; font-size:11px; color:var(--wb-text-muted); }
.operation-receipt button { margin:0; }
.operation-menu label { display:grid; gap:7px; padding:8px; font-size:11px; color:var(--wb-text-muted); }
.operation-menu select { width:100%; padding:7px; border:1px solid var(--cp-border); border-radius:6px; color:var(--wb-text); background:var(--wb-surface-1); }
.question-heading { display:flex; align-items:center; gap:7px; color:var(--wb-accent); font-size:11px; }
.question-heading small { margin-left:auto; color:var(--wb-text-muted); font-size:10px; }
.question-card p { font-size:13px; line-height:1.7; margin:12px 0; white-space:pre-wrap; overflow-wrap:anywhere; }
.question-choices { display:grid; gap:7px; }
.question-choices button { padding:9px 11px; border:1px solid var(--cp-border); border-radius:7px; color:var(--wb-text-secondary); background:var(--wb-surface-1); text-align:left; font-size:12px; }
.question-choices button:hover { border-color:var(--wb-accent); }
.reply-link { display:flex; align-items:center; gap:7px; padding:0; margin-top:13px; border:0; background:transparent; color:var(--wb-accent); font-size:11px; }
.wait-note { display:flex; gap:8px; padding:12px; color:var(--wb-text-muted); font-size:12px; line-height:1.6; border:1px solid var(--cp-border); border-radius:9px; }
.composer { position:relative; margin:8px 12px 0; padding:16px 14px 10px; border:1px solid var(--cp-border); border-radius:17px; background:var(--wb-surface-section); box-shadow:0 3px 12px #0000000a; }
.composer:focus-within { border-color:color-mix(in srgb,var(--wb-text-muted) 60%,var(--cp-border)); }
.composer textarea { display:block; box-sizing:border-box; width:100%; min-height:76px; max-height:180px; resize:none; padding:0 2px; border:0; outline:0; background:transparent; color:var(--wb-text); font:13px/1.7 var(--font-sans,sans-serif); }
.composer textarea::placeholder { color:var(--wb-text-muted); }
.composer-footer { display:flex; align-items:center; gap:6px; margin-top:12px; min-width:0; }
.composer-picker { min-width:0; }
.permission-picker { flex-shrink:0; }
.model-picker { margin-left:auto; flex:0 1 auto; }
.picker-trigger { display:flex; align-items:center; gap:5px; max-width:100%; padding:5px 3px; border:0; border-radius:6px; background:transparent; color:var(--wb-text-secondary); font-size:11px; }
.picker-trigger:hover,.picker-trigger[aria-expanded=true] { background:var(--wb-hover); color:var(--wb-text); }
.picker-trigger > span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0; }
.picker-trigger .el-icon { flex-shrink:0; font-size:12px; }
.picker-trigger .chevron { font-size:9px; color:var(--wb-text-muted); }
.picker-trigger > small { flex-shrink:0; font-size:10px; color:var(--wb-text-muted); }
.permission-picker .picker-trigger > .el-icon:first-child { color:var(--wb-warning); }
.permission-picker.is-auto-approval .picker-trigger > .el-icon:first-child { color:var(--wb-accent); }
.picker-menu { position:absolute; z-index:20; bottom:52px; right:8px; left:8px; padding:6px; max-height:320px; overflow:auto; border:1px solid var(--wb-border); border-radius:12px; background:var(--wb-surface-section); box-shadow:0 8px 28px #00000040; }
.menu-heading { display:flex; justify-content:space-between; padding:8px 8px 7px; color:var(--wb-text-muted); font-size:10px; }
.menu-heading small { font-size:10px; }
.picker-menu button { display:flex; align-items:center; gap:9px; width:100%; padding:10px 8px; border:0; border-radius:7px; text-align:left; background:transparent; color:var(--wb-text-secondary); }
.picker-menu button:hover,.picker-menu button[aria-checked=true] { background:var(--wb-hover); color:var(--wb-text); }
.picker-menu button > span { min-width:0; flex:1; }
.picker-menu strong { display:block; font-size:12px; font-weight:500; overflow-wrap:anywhere; }
.picker-menu small { display:block; margin-top:4px; font-size:10px; line-height:1.5; color:var(--wb-text-muted); }
.picker-menu .selected-check { color:var(--wb-accent); }
.picker-menu p { margin:7px 8px 4px; padding-top:8px; border-top:1px solid var(--cp-border); color:var(--wb-text-muted); font-size:10px; line-height:1.5; }
.reasoning-controls { border-top:1px solid var(--cp-border); padding:4px 4px 8px; }
.reasoning-controls > small { display:block; padding:4px 8px; }
.effort-options { display:flex; gap:4px; }
.effort-options button { justify-content:center; padding:7px 3px; font-size:11px; }
.effort-options button[aria-pressed=true] { background:var(--wb-accent-soft); color:var(--wb-accent); }
.send-button { display:grid; place-items:center; width:30px; height:30px; flex-shrink:0; border:0; border-radius:50%; background:var(--wb-text); color:var(--wb-surface-1); font-size:17px; }
.send-button:disabled { background:var(--wb-hover); color:var(--wb-text-muted); opacity:.7; }
.composer-mode { display:flex; gap:5px; margin-bottom:10px; }
.composer-mode button { border:0; background:transparent; color:var(--wb-text-muted); border-radius:5px; padding:4px 7px; font-size:10px; }
.composer-mode .selected { color:var(--wb-accent); background:var(--wb-accent-soft); }
.error-note { display:flex; align-items:center; justify-content:space-between; gap:8px; margin:8px 12px; padding:10px; background:var(--wb-surface-section); border:1px solid var(--cp-border); border-radius:8px; color:var(--wb-text-secondary); font-size:11px; line-height:1.5; }
.error-note button { flex-shrink:0; border:0; color:var(--wb-accent); background:transparent; }
.readonly-note { padding:6px 16px; color:var(--wb-text-muted); font-size:10px; }
.thinking-line { height:3px; width:70px; background:var(--wb-accent-soft); border-radius:4px; animation:pulse 1.3s infinite alternate; }
.trajectory-view { padding:12px 0; }
.trace-toolbar { display:flex; gap:10px; align-items:center; padding:0 12px 12px; color:var(--wb-text-muted); font-size:10px; }
.trace-toolbar span { flex-shrink:0; }
.trace-toolbar input { min-width:0; width:100%; border:1px solid var(--cp-border); border-radius:6px; color:var(--wb-text); background:var(--wb-surface-section); padding:6px 8px; font:10px var(--font-sans,sans-serif); }
.trace-lanes { display:flex; align-items:center; flex-wrap:wrap; gap:7px; padding:10px 12px; border-block:1px solid var(--cp-border); font-size:9px; }
.trace-lanes > div { flex:1 1 100%; display:flex; gap:3px; overflow:hidden; min-width:0; }
.trace-lanes i { width:5px; height:7px; min-width:3px; background:currentColor; border-radius:1px; }
.lane-planner { color:var(--wb-accent); }.lane-model { color:var(--wb-artifact); }.lane-tool { color:var(--wb-warning); }.lane-execution { color:var(--wb-success); }
.trace-event { border-bottom:1px solid var(--cp-border); }
.trace-event summary { display:flex; align-items:center; gap:7px; padding:11px 12px; cursor:pointer; list-style:none; }
.trace-event summary::-webkit-details-marker { display:none; }
.trace-event summary:hover { background:var(--wb-hover); }
.trace-dot { flex-shrink:0; width:5px; height:5px; border-radius:50%; background:currentColor; }
.trace-kind { font-size:9px; flex-shrink:0; }
.trace-event summary > div { flex:1; min-width:0; }
.trace-event strong { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:11px; font-weight:450; color:var(--wb-text-secondary); }
.trace-event small { display:block; margin-top:4px; color:var(--wb-text-muted); font:9px var(--font-mono,monospace); }
.trace-event time { font-size:9px; color:var(--wb-text-muted); flex-shrink:0; }
.trace-event summary > .el-icon { font-size:10px; color:var(--wb-text-muted); }
.trace-event pre { margin:0; padding:12px; overflow:auto; max-height:220px; background:var(--wb-surface-inset); color:var(--wb-text-secondary); font:10px/1.6 var(--font-mono,monospace); }
.trace-footnote { display:block; padding:14px; color:var(--wb-text-muted); font-size:10px; line-height:1.6; }
.no-results { padding:15px; color:var(--wb-text-muted); font-size:12px; }
.load-more { display:block; margin:12px auto; padding:7px 12px; border:1px solid var(--cp-border); border-radius:7px; background:transparent; color:var(--wb-text-secondary); font-size:11px; }
@keyframes copilot-watermark-pulse { 0%,100% { opacity:.85; transform:scale(.985); } 50% { opacity:1; transform:scale(1); } }
@keyframes pulse { from { opacity:.4; } to { opacity:1; } }
@media(prefers-reduced-motion:reduce) { .thinking-line { animation:none; } .empty-watermark { animation:none; } }
@media(max-width:340px) { .conversation { padding:14px 12px; }.trace-event time { display:none; } }
</style>
