<!-- 消息展示组件 — 用户使用紧凑气泡，助手使用无边框阅读流 -->
<template>
  <div v-if="message && message.role && message.content !== undefined" :class="['message-bubble', message.role]">
    <div class="message-content-wrapper">
      <div class="message-content">
        <!-- 文件展示 -->
        <div v-if="message.fileUrl" class="message-file">
          <div
            v-if="isImage(message.fileUrl)"
            class="message-image-wrapper"
            @click="openImageViewer"
          >
            <img :src="message.fileUrl" class="message-image" />
            <div class="image-overlay">
              <el-icon><FullScreen /></el-icon>
            </div>
          </div>
          <div v-else class="file-attachment">
            <el-icon><Document /></el-icon>
            <div class="file-info">
              <span class="filename">附件文件</span>
              <a :href="message.fileUrl" target="_blank" class="download-link">下载</a>
            </div>
          </div>
        </div>

        <ImageViewer
          v-model:visible="imageViewerVisible"
          :src="message.fileUrl"
          :file-name="'image.png'"
        />

        <!-- DeepSeek 风格的内联思考状态；仅展示真实状态和已有运行详情 -->
        <section
          v-if="message.role === 'assistant' && showThinkingStatus"
          class="thinking-status"
          :class="{ 'is-thinking': headerThinkingActive }"
          aria-label="AI 思考状态"
        >
          <button
            v-if="canExpandDetails"
            type="button"
            class="thinking-status__trigger"
            :aria-expanded="detailsOpen"
            :aria-controls="detailsId"
            @click="detailsOpen = !detailsOpen"
          >
            <span class="thinking-status__identity">
              <el-icon class="thinking-status__icon"><Cpu /></el-icon>
              <Transition name="thinking-phase" mode="out-in">
                <span :key="thinkingLabel" class="thinking-status__phase">{{ thinkingLabel }}</span>
              </Transition>
            </span>
            <el-icon class="thinking-status__chevron" :class="{ open: detailsOpen }"><ArrowDown /></el-icon>
          </button>
          <div v-else class="thinking-status__summary" role="status" aria-live="polite">
            <span class="thinking-status__identity">
              <el-icon class="thinking-status__icon"><Cpu /></el-icon>
              <Transition name="thinking-phase" mode="out-in">
                <span :key="thinkingLabel" class="thinking-status__phase">{{ thinkingLabel }}</span>
              </Transition>
            </span>
            <span v-if="headerThinkingActive" class="thinking-status__dots" aria-hidden="true">
              <i></i><i></i><i></i>
            </span>
          </div>

          <Transition name="thinking-details">
            <div v-if="detailsOpen && canExpandDetails" :id="detailsId" class="thinking-status__details">
              <div v-if="message.modelInfo" class="explanation-item">
                <span class="explanation-label">模型</span>
                <span class="explanation-value">{{ message.modelInfo }}</span>
              </div>

              <div v-if="message.reasoningContent" class="explanation-item vertical">
                <span class="explanation-label">思考过程</span>
                <div class="reasoning-content">{{ message.reasoningContent }}</div>
              </div>

              <div v-if="message.effectiveThinkingMode" class="explanation-item">
                <span class="explanation-label">思考强度</span>
                <span class="explanation-value">{{ thinkingModeLabel }}</span>
              </div>

              <div v-if="message.reasoningTokens" class="explanation-item">
                <span class="explanation-label">思考消耗</span>
                <span class="explanation-value">{{ message.reasoningTokens }} tokens</span>
              </div>

              <div v-if="message.confidence" class="explanation-item">
                <span class="explanation-label">置信度</span>
                <div class="explanation-value-row">
                  <el-progress
                    :percentage="(message.confidence * 100)"
                    :color="getConfidenceColor(message.confidence)"
                    :stroke-width="5"
                    :show-text="false"
                    style="width: 96px;"
                  />
                  <span class="value-text">{{ (message.confidence * 100).toFixed(1) }}%</span>
                </div>
              </div>

              <div v-if="message.tokensUsed" class="explanation-item">
                <span class="explanation-label">消耗</span>
                <span class="explanation-value">{{ message.tokensUsed }} tokens</span>
              </div>

              <div v-if="message.sources && message.sources.length > 0" class="explanation-item vertical">
                <span class="explanation-label">参考来源</span>
                <div class="sources-list">
                  <template v-for="(source, index) in message.sources" :key="source.citationId || source.url || index">
                    <a
                      v-if="source.url && isSafeUrl(source.url)"
                      class="source-tag"
                      :href="source.url"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      <el-icon><Link /></el-icon>
                      {{ source.title || source.filename || `来源 ${index + 1}` }}
                    </a>
                    <span v-else class="source-tag">
                      <el-icon><Link /></el-icon>
                      {{ source.title || source.filename || `来源 ${index + 1}` }}
                    </span>
                  </template>
                </div>
              </div>

              <div v-if="message.reasoningPath && message.reasoningPath.length > 0" class="explanation-item vertical">
                <span class="explanation-label">推理路径</span>
                <div class="reasoning-path">
                  <div v-for="(step, index) in message.reasoningPath" :key="index" class="reasoning-step">
                    <div class="step-dot"></div>
                    <div class="step-content">
                      <div class="step-title">{{ step.title }}</div>
                      <div class="step-desc">{{ step.description }}</div>
                    </div>
                  </div>
                </div>
              </div>

              <div v-if="message.executionSummary && message.executionSummary.length > 0" class="explanation-item vertical">
                <span class="explanation-label">执行摘要</span>
                <div class="execution-summary">
                  <div v-for="item in message.executionSummary" :key="`${item.stage}-${item.status}`" class="execution-summary__item">
                    <span class="execution-summary__stage">{{ executionStageLabel(item.stage) }}</span>
                    <span class="execution-summary__description">{{ item.description }}</span>
                  </div>
                </div>
              </div>
            </div>
          </Transition>
        </section>

        <section
          v-if="approvalActivities.length"
          class="approval-work"
          aria-label="文件操作审批"
        >
          <article
            v-for="item in approvalActivities"
            :key="`approval-${item.approval?.approvalId}`"
            class="approval-work__card"
            :class="{ 'is-resolved': item.approval?.status !== 'pending' }"
          >
            <div class="approval-work__title">
              {{ item.approval?.operation === 'Run command' ? '需要确认命令执行' : '需要确认文件操作' }}
            </div>
            <div class="approval-work__summary">{{ item.approval?.operationSummary }}</div>
            <div v-if="item.approval?.command" class="approval-work__command">
              <code>$ {{ item.approval.command }}</code>
            </div>
            <div v-if="item.approval?.cwd" class="approval-work__cwd">
              cwd: <code>{{ item.approval.cwd }}</code>
            </div>
            <div v-if="item.approval?.riskNotice" class="approval-work__risk">
              {{ item.approval.riskNotice }}
            </div>
            <div class="approval-work__scope">
              <code>{{ item.approval?.capabilityId }}</code>
              <code v-if="item.approval?.relativePath">{{ item.approval.relativePath }}</code>
            </div>
            <div v-if="item.approval?.status === 'pending'" class="approval-work__actions">
              <button
                type="button"
                class="approval-work__button is-primary"
                :disabled="approvalBusy[item.approval.approvalId]"
                @click="resolveApproval(item, 'allow_once')"
              >允许一次</button>
              <button
                v-if="item.approval?.capabilityId !== 'shell.exec'"
                type="button"
                class="approval-work__button"
                :disabled="approvalBusy[item.approval.approvalId]"
                @click="resolveApproval(item, 'allow_session')"
              >本次会话允许</button>
              <button
                type="button"
                class="approval-work__button is-danger"
                :disabled="approvalBusy[item.approval.approvalId]"
                @click="resolveApproval(item, 'deny')"
              >拒绝</button>
            </div>
            <div v-else class="approval-work__resolved">
              {{ item.approval?.status === 'approved' ? '已允许' : item.approval?.status === 'denied' ? '已拒绝' : '已失效' }}
            </div>
          </article>
        </section>

        <!-- Chat-only terminal output stays visible in the conversation, rather than
             being hidden inside the generic thinking details. -->
        <section
          v-if="terminalActivities.length"
          class="terminal-work"
          aria-label="终端工作"
        >
          <div class="terminal-work__header">
            <span class="terminal-work__title">终端工作</span>
            <span class="terminal-work__count">{{ terminalActivities.length }} 次调用</span>
          </div>
          <article
            v-for="item in terminalActivities"
            :key="item.stage"
            class="terminal-work__item"
            :class="{ 'is-failed': item.status === 'failed' || item.status === 'cancelled', 'is-running': item.status === 'running' }"
          >
            <div v-if="item.terminal" class="terminal-work__meta">
              <code class="terminal-work__command">$ {{ item.terminal.command }}</code>
              <span class="terminal-work__cwd">{{ item.terminal.cwd }}</span>
              <span class="terminal-work__exit">
                {{ item.terminal.timedOut ? '超时' : `退出码 ${item.terminal.exitCode}` }}
              </span>
            </div>
            <div v-else class="terminal-work__running">正在执行终端命令…</div>
            <pre v-if="item.terminal?.stdout" class="terminal-work__output">{{ item.terminal.stdout }}</pre>
            <pre v-if="item.terminal?.stderr" class="terminal-work__output is-stderr">{{ item.terminal.stderr }}</pre>
            <div v-if="item.terminal?.truncated" class="terminal-work__truncated">输出已截断</div>
          </article>
        </section>

        <section
          v-if="fileActivities.length"
          class="file-work"
          aria-label="文件工作"
        >
          <div class="file-work__header">
            <span class="file-work__title">文件工作</span>
            <span class="file-work__count">{{ fileActivities.length }} 次调用</span>
          </div>
          <article
            v-for="item in fileActivities"
            :key="`file-${item.stage}`"
            class="file-work__item"
            :class="{ 'is-failed': item.status === 'failed' || item.status === 'cancelled', 'is-running': item.status === 'running' }"
          >
            <div class="file-work__meta">
              <span class="file-work__kind">{{ fileActivityLabel(item.activity?.kind) }}</span>
              <code v-if="item.activity?.relativePath" class="file-work__path">{{ item.activity.relativePath }}</code>
              <span v-if="item.activity?.entryCount !== undefined" class="file-work__count-detail">
                {{ item.activity.entryCount }} 项
              </span>
            </div>
            <div class="file-work__summary">
              {{ item.activity?.summary || item.description }}
              <span v-if="item.activity?.addedLines !== undefined || item.activity?.removedLines !== undefined">
                （+{{ item.activity?.addedLines || 0 }} / -{{ item.activity?.removedLines || 0 }}）
              </span>
            </div>
            <div v-if="item.status === 'failed'" class="file-work__error">
              执行失败：{{ item.activity?.errorCode || 'FILE_OPERATION_FAILED' }}
            </div>
          </article>
        </section>

        <!-- 文本内容 -->
        <div
          v-if="message.content"
          class="message-text markdown-body"
          v-html="renderedMessageHtml"
        />

        <Transition name="continuation-status">
          <div
            v-if="showContinuationStatus"
            class="continuation-status"
            role="status"
            aria-live="polite"
          >
            <span class="continuation-status__pulse" aria-hidden="true">
              <i></i><i></i><i></i>
            </span>
            <span class="continuation-status__eyebrow">执行脉络</span>
            <Transition name="thinking-phase" mode="out-in">
              <span :key="continuationLabel" class="continuation-status__label">
                {{ continuationLabel }}
              </span>
            </Transition>
          </div>
        </Transition>
      </div>

      <!-- Message Actions Area -->
      <div v-if="message.content" class="message-actions">
        <el-tooltip content="复制" placement="top">
          <div class="action-item" @click="handleAction('copy')"><el-icon><CopyDocument /></el-icon></div>
        </el-tooltip>
        <el-tooltip content="引用" placement="top">
          <div class="action-item" @click="handleAction('quote')"><el-icon><ChatLineSquare /></el-icon></div>
        </el-tooltip>
        <el-tooltip content="生成语音" placement="top">
          <div class="action-item" @click="handleAction('tts')"><el-icon><Microphone /></el-icon></div>
        </el-tooltip>
        <el-tooltip content="导出" placement="top">
          <div class="action-item" @click="handleAction('export')"><el-icon><Download /></el-icon></div>
        </el-tooltip>
        <el-tooltip content="删除" placement="top">
          <div class="action-item delete" @click="handleAction('delete')"><el-icon><Delete /></el-icon></div>
        </el-tooltip>
        <span class="message-action-time">{{ formatTime(message.createdAt) }}</span>
      </div>
    </div>
  </div>
  <div v-else class="message-bubble error">
    <div class="message-content">
      <div class="message-text">消息数据无效</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowDown, Cpu, Document, Link, CopyDocument, ChatLineSquare, Delete, Microphone, Download, FullScreen } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import ImageViewer from '@/components/common/ImageViewer.vue'
import { renderMarkdown } from '@/utils/markdown'
import { chatApi, type ChatApprovalDecision } from '@/services/api/chat'

interface Source {
  title?: string
  filename?: string
  url?: string
  content?: string
  snippet?: string
  provider?: string
  citationId?: string
  retrievedAt?: string
}

interface ReasoningStep {
  title: string
  description: string
}

interface TerminalExecution {
  command: string
  cwd: string
  exitCode: number | null
  stdout: string
  stderr: string
  timedOut: boolean
  truncated: boolean
  durationMs?: number
}

interface ToolExecutionActivity {
  kind: string
  capabilityId?: string
  relativePath?: string
  status?: string
  summary?: string
  addedLines?: number
  removedLines?: number
  entryCount?: number
  errorCode?: string
}

interface ChatApproval {
  approvalId: string
  toolCallId: string
  invocationId: string
  toolName: string
  capabilityId: string
  relativePath?: string
  operationSummary: string
  createdAt: string
  status: string
  sessionId: string
  operation?: string
  command?: string
  cwd?: string
  riskNotice?: string
}

interface ExecutionSummaryItem {
  stage: string
  status: string
  description: string
  durationMs?: number
  terminal?: TerminalExecution
  activity?: ToolExecutionActivity
  approval?: ChatApproval
}

interface Props {
  message: {
    id: number | string
    role: 'user' | 'assistant'
    content: string
    createdAt: Date
    confidence?: number
    fileUrl?: string
    tokensUsed?: number
    sources?: Source[]
    reasoningPath?: ReasoningStep[]
    modelInfo?: string
    thinkingState?: 'thinking' | 'complete' | 'error'
    streamActivity?: 'receiving' | 'waiting' | 'complete'
    streamPhase?: string
    thinkingDurationMs?: number
    reasoningContent?: string
    requestedThinkingMode?: string
    effectiveThinkingMode?: string
    effectiveReasoningEffort?: string
    reasoningTokens?: number
    executionSummary?: ExecutionSummaryItem[]
  }
}

const props = defineProps<Props>()
const emit = defineEmits(['copy', 'quote', 'delete', 'tts', 'export'])
const detailsOpen = ref(false)
const imageViewerVisible = ref(false)
const approvalBusy = ref<Record<string, boolean>>({})
const detailsId = computed(() => `thinking-details-${String(props.message.id).replace(/[^a-zA-Z0-9_-]/g, '-')}`)

const openImageViewer = () => {
  imageViewerVisible.value = true
}

const handleAction = (type: 'copy' | 'quote' | 'delete' | 'tts' | 'export') => {
  if (type === 'copy') {
    navigator.clipboard.writeText(props.message.content)
    ElMessage.success('已复制到剪贴板')
  } else if (type === 'delete') {
    ElMessageBox.confirm('确定要删除这条消息吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
      customClass: 'destructive-confirm'
    }).then(() => {
      emit('delete', props.message.id)
    }).catch(() => {})
  } else {
    emit(type, props.message)
  }
}

const escapeHtml = (raw: string) => {
  return raw
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

const isSafeUrl = (url: string) => /^(https?:\/\/|mailto:|\/)/i.test(url)

const renderedMessageHtml = computed(() => {
  const content = props.message.content || ''
  if (!content) return ''
  if (props.message.role === 'assistant') return renderMarkdown(content)
  return escapeHtml(content).replace(/\n/g, '<br />')
})

const hasDetails = computed(() => {
  return !!(
    props.message.confidence ||
    props.message.tokensUsed ||
    (props.message.sources && props.message.sources.length > 0) ||
    (props.message.reasoningPath && props.message.reasoningPath.length > 0) ||
    props.message.reasoningContent ||
    props.message.effectiveThinkingMode ||
    props.message.reasoningTokens ||
    (props.message.executionSummary && props.message.executionSummary.length > 0) ||
    props.message.modelInfo
  )
})

const showThinkingStatus = computed(() => !!props.message.thinkingState || hasDetails.value)

const terminalActivities = computed(() => (props.message.executionSummary || [])
  .filter(item => item.stage.split(':')[1] === 'terminal' || item.stage.split(':')[1] === 'run_command'))

const fileActivities = computed(() => (props.message.executionSummary || [])
  .filter(item => item.activity && item.activity.kind !== 'terminal'))

const approvalActivities = computed(() => (props.message.executionSummary || [])
  .filter(item => item.approval))

const resolveApproval = async (item: ExecutionSummaryItem, decision: ChatApprovalDecision) => {
  const approval = item.approval
  if (!approval || approvalBusy.value[approval.approvalId]) return
  approvalBusy.value = { ...approvalBusy.value, [approval.approvalId]: true }
  try {
    await chatApi.resolveApproval(approval.approvalId, {
      decision,
      sessionId: approval.sessionId,
      invocationId: approval.invocationId,
      capabilityId: approval.capabilityId,
      relativePath: approval.relativePath
    })
  } catch {
    ElMessage.error('审批请求处理失败，请重试')
  } finally {
    const next = { ...approvalBusy.value }
    delete next[approval.approvalId]
    approvalBusy.value = next
  }
}

const canExpandDetails = computed(() => {
  return hasDetails.value && (
    props.message.thinkingState !== 'thinking' || Boolean(props.message.reasoningContent)
  )
})

const thinkingModeLabel = computed(() => {
  const mode = props.message.effectiveThinkingMode || props.message.requestedThinkingMode
  if (mode === 'deep') return '深度'
  if (mode === 'standard') return '标准'
  return '关闭'
})

const thinkingDurationSeconds = computed(() => {
  if (props.message.thinkingDurationMs === undefined) return null
  return Math.max(1, Math.ceil(props.message.thinkingDurationMs / 1000))
})

const headerThinkingActive = computed(() => {
  if (props.message.thinkingState === 'thinking') return true
  return !props.message.thinkingState
    && (props.message.streamActivity === 'receiving' || props.message.streamActivity === 'waiting')
})

const thinkingLabel = computed(() => {
  const seconds = thinkingDurationSeconds.value
  const duration = seconds === null ? '' : `（用时 ${seconds} 秒）`
  if (props.message.thinkingState === 'complete') return `已思考${duration}`
  if (props.message.thinkingState === 'error') return `思考已中断${duration}`
  if (props.message.thinkingState === 'thinking') return '思考中'
  if (props.message.streamActivity === 'waiting') return props.message.streamPhase || '等待模型继续'
  if (props.message.streamActivity === 'receiving') {
    return props.message.streamPhase || '处理中'
  }
  return '运行详情'
})

const showContinuationStatus = computed(() => {
  return props.message.role === 'assistant'
    && Boolean(props.message.content)
    && (props.message.streamActivity === 'receiving' || props.message.streamActivity === 'waiting')
})

const continuationLabel = computed(() => {
  if (props.message.streamPhase) return props.message.streamPhase
  return props.message.streamActivity === 'waiting' ? '等待模型继续' : '继续推进任务'
})

const getConfidenceColor = (confidence: number) => {
  if (confidence >= 0.8) return 'var(--success)'
  if (confidence >= 0.6) return 'var(--warning)'
  return 'var(--danger)'
}

const executionStageLabel = (stage: string) => {
  if (stage === 'reasoning') return '思考'
  if (stage === 'answer_generation') return '回答生成'
  if (stage.startsWith('tool:terminal')) return '终端'
  if (stage.startsWith('tool:')) return `工具 · ${stage.split(':')[1] || 'unknown'}`
  return stage
}

const fileActivityLabel = (kind?: string) => {
  if (kind === 'file_read') return '读取'
  if (kind === 'file_list') return '列出'
  if (kind === 'file_write') return '写入'
  if (kind === 'file_patch') return '编辑'
  return '文件工具'
}

const isImage = (url: string) => {
  const imageExtensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
  return imageExtensions.some(ext => url.toLowerCase().includes(ext))
}

const formatTime = (date: Date) => {
  const d = new Date(date)
  return d.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit'
  })
}
</script>

<style scoped lang="scss">
.message-bubble {
  width: 100%;
  display: flex;
  justify-content: center;
  box-sizing: border-box;
  margin: 0;
  animation: fadeIn 180ms var(--ease-out);
  padding: 0 28px;
}

.message-bubble.user {
  /* 行宽限制为消息列（780px 内容宽 + 两侧 28px 内边距），
     让用户气泡右缘贴齐居中列而不是飞到面板最右侧 */
  width: min(100%, 836px);
  margin-inline: auto;
  justify-content: flex-end;
}

.message-content-wrapper {
  width: min(100%, 780px);
  max-width: 100%;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.message-bubble.user .message-content-wrapper {
  width: auto;
  max-width: min(72%, 560px);
  align-items: flex-end;
}

.message-content {
  padding: 0;
  border-radius: 0;
  word-wrap: break-word;
  line-height: 1.75;
  font-size: 15.5px;
  position: relative;
  transition: var(--transition);
}

.message-bubble.user .message-content {
  padding: 9px 14px;
  border: 1px solid var(--border-light);
  border-radius: 18px;
  background: var(--bg-panel);
  color: var(--text-primary);
  box-shadow: none;
}

.message-bubble.assistant .message-content {
  background: transparent;
  color: var(--text-primary);
  border: 0;
  border-radius: 0;
  box-shadow: none;
}

/* System/History Messages (Placeholder for role='system') */
.message-bubble.system {
  justify-content: center;
  margin: 16px 0;
}
.message-bubble.system .message-content {
  background-color: var(--bg-input);
  color: var(--text-secondary);
  font-size: 12px;
  padding: 4px 12px;
  border-radius: 8px;
  border: none;
  box-shadow: none;
}
.message-bubble.system .message-avatar, 
.message-bubble.system .message-meta {
  display: none;
}

.continuation-status {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 24px;
  margin-top: 10px;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.4;
}

.continuation-status__pulse {
  display: inline-flex;
  align-items: flex-end;
  gap: 2px;
  width: 14px;
  height: 12px;
}

.continuation-status__pulse i {
  display: block;
  width: 2px;
  height: 7px;
  border-radius: 999px;
  background: var(--primary-color);
  animation: continuationSignal 1.15s ease-in-out infinite;
}

.continuation-status__pulse i:nth-child(2) {
  height: 11px;
  animation-delay: 0.14s;
}

.continuation-status__pulse i:nth-child(3) {
  height: 8px;
  animation-delay: 0.28s;
}

.continuation-status__eyebrow {
  color: var(--text-disabled);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.08em;
  white-space: nowrap;
}

.continuation-status__label {
  color: var(--text-secondary);
}

.continuation-status-enter-active,
.continuation-status-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.continuation-status-enter-from,
.continuation-status-leave-to {
  opacity: 0;
  transform: translateY(-3px);
}

/* Error Message Style */
.message-bubble.error {
  justify-content: center;
  margin: 16px 0;
}
.message-bubble.error .message-content {
  background-color: rgba(178, 74, 74, 0.08);
  color: var(--danger);
  font-size: 13px;
  padding: 8px 16px;
  border-radius: 8px;
  border: 1px solid rgba(178, 74, 74, 0.18);
}
.message-bubble.error .message-avatar, 
.message-bubble.error .message-meta {
  display: none;
}

/* Message Actions Area */
.message-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-top: 7px;
  padding: 0;
  opacity: 0.62;
  transition: opacity 0.2s;
}

/* 保持悬停效果，但不再控制显示/隐藏 */
.message-bubble:hover .message-actions,
.message-actions:focus-within {
  opacity: 1;
}

.message-bubble.user .message-actions {
  justify-content: flex-end;
}

.action-item {
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 7px;
  cursor: pointer;
  color: var(--text-disabled);
  transition: var(--transition);
  background: transparent;
}

.action-item:hover {
  background: var(--bg-panel);
  color: var(--text-primary);
  transform: none;
}

.action-item.delete:hover {
  color: var(--danger);
}

.action-item .el-icon {
  font-size: 14px;
}

.message-bubble.user .action-item {
  color: var(--text-disabled);
  background: transparent;
}

.message-bubble.user .action-item:hover {
  color: var(--text-primary);
  background: var(--bg-panel);
}

.message-action-time {
  margin-left: 6px;
  color: var(--text-disabled);
  font-size: 10px;
  white-space: nowrap;
}

.message-bubble.user .message-action-time {
  order: -1;
  margin: 0 6px 0 0;
}

/* File Attachments */
.message-image-wrapper {
  position: relative;
  display: inline-block;
  cursor: zoom-in;
  border-radius: 8px;
  overflow: hidden;
}

.message-image {
  max-width: 100%;
  border-radius: 8px;
  border: 1px solid var(--border-light);
  display: block;
}

.image-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0);
  transition: background 0.2s ease;
  border-radius: 8px;
  opacity: 0;
  transition: all 0.2s ease;
}

.message-image-wrapper:hover .image-overlay {
  background: rgba(29, 36, 34, 0.24);
  opacity: 1;
}

.image-overlay .el-icon {
  color: #fff;
  font-size: 20px;
}

.file-attachment {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: color-mix(in srgb, var(--bg-card) 72%, transparent);
  border: 1px solid var(--border-light);
  border-radius: 8px;
}

.message-bubble.assistant .file-attachment {
  background: var(--bg-input);
  border-color: var(--border-light);
}

.message-text {
  white-space: pre-wrap;
}

.message-text.markdown-body {
  white-space: normal;
  line-height: 1.78;
}

.message-text.markdown-body :deep(h1),
.message-text.markdown-body :deep(h2),
.message-text.markdown-body :deep(h3),
.message-text.markdown-body :deep(h4),
.message-text.markdown-body :deep(h5),
.message-text.markdown-body :deep(h6) {
  margin: 8px 0;
  line-height: 1.4;
  font-weight: 700;
}

.message-text.markdown-body :deep(h1) { font-size: 20px; }
.message-text.markdown-body :deep(h2) { font-size: 18px; }
.message-text.markdown-body :deep(h3) { font-size: 16px; }

.message-text.markdown-body :deep(p) {
  margin: 0 0 12px;
}

.message-text.markdown-body :deep(p:last-child) {
  margin-bottom: 0;
}

.message-text.markdown-body :deep(ul),
.message-text.markdown-body :deep(ol) {
  margin: 8px 0;
  padding-left: 20px;
}

.message-text.markdown-body :deep(li) {
  margin: 4px 0;
}

.message-text.markdown-body :deep(pre) {
  margin: 10px 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: #20262b;
  color: #eef1ef;
  overflow-x: auto;
}

.message-text.markdown-body :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace;
  padding: 0 4px;
  border-radius: 4px;
  background: color-mix(in srgb, var(--primary-color) 12%, transparent);
}

.message-text.markdown-body :deep(pre code) {
  background: transparent;
  padding: 0;
}

.message-text.markdown-body :deep(a) {
  color: var(--primary-color);
  text-decoration: underline;
  word-break: break-all;
}

/* Markdown 表格样式收敛到 global.css 的全局三线表 */

/* Inline thinking status — compact, borderless and theme-token driven */
.thinking-status {
  width: 100%;
  margin: 0 0 14px;
  color: var(--text-secondary);
}

.thinking-status__trigger,
.thinking-status__summary {
  min-height: 28px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text-primary);
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
}

.thinking-status__trigger {
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: color 180ms var(--ease-out);
}

.thinking-status__trigger:hover {
  color: var(--primary-color);
}

.thinking-status__trigger:focus-visible {
  outline: 2px solid var(--border-focus);
  outline-offset: 3px;
}

.thinking-status__identity {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.thinking-status__phase {
  display: inline-block;
  min-width: 7em;
}

.thinking-phase-enter-active,
.thinking-phase-leave-active {
  transition: opacity 160ms var(--ease-out), transform 160ms var(--ease-out);
}

.thinking-phase-enter-from {
  opacity: 0;
  transform: translateY(2px);
}

.thinking-phase-leave-to {
  opacity: 0;
  transform: translateY(-2px);
}

.thinking-status__icon {
  flex: 0 0 auto;
  color: var(--primary-color);
  font-size: 16px;
}

.thinking-status.is-thinking .thinking-status__icon {
  animation: thinkingPulse 1.5s ease-in-out infinite;
}

.thinking-status__chevron {
  margin-left: 1px;
  color: var(--text-secondary);
  font-size: 12px;
  transition: transform 180ms var(--ease-out), color 180ms var(--ease-out);
}

.thinking-status__chevron.open {
  transform: rotate(180deg);
}

.thinking-status__dots {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-left: 1px;
}

.thinking-status__dots i {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--text-secondary);
  animation: thinkingDot 1.2s ease-in-out infinite;
}

.thinking-status__dots i:nth-child(2) { animation-delay: 140ms; }
.thinking-status__dots i:nth-child(3) { animation-delay: 280ms; }

.thinking-status__details {
  width: min(100%, 720px);
  margin: 8px 0 2px 7px;
  padding: 4px 0 2px 16px;
  border-left: 1px solid color-mix(in srgb, var(--primary-color) 32%, var(--border-light));
  color: var(--text-secondary);
}

.thinking-details-enter-active,
.thinking-details-leave-active {
  transition: opacity 180ms var(--ease-out), transform 180ms var(--ease-out);
}

.thinking-details-enter-from,
.thinking-details-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

.explanation-item {
  display: flex;
  align-items: center;
  margin-bottom: 9px;
  gap: 12px;
  font-size: 13px;
  
  &.vertical {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
  }
}

.explanation-label {
  color: var(--text-secondary);
  font-weight: 500;
  min-width: 60px;
}

.explanation-value {
  min-width: 0;
  color: var(--text-regular);
  overflow-wrap: anywhere;
}

.explanation-value-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.value-text {
  font-size: 12px;
  color: var(--text-regular);
}

.reasoning-content {
  width: 100%;
  max-height: 280px;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-secondary);
  background: color-mix(in srgb, var(--bg-card) 76%, transparent);
  border: 1px solid var(--border-light);
  border-radius: 6px;
  padding: 10px 12px;
}

.execution-summary {
  display: grid;
  gap: 6px;
  width: 100%;
}

.execution-summary__item {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 8px;
  align-items: start;
  font-size: 12px;
  line-height: 1.55;
}

.execution-summary__stage {
  color: var(--text-secondary);
}

.execution-summary__description {
  color: var(--text-regular);
  overflow-wrap: anywhere;
}

.approval-work {
  display: grid;
  gap: 10px;
  margin: 12px 0 14px;
}

.approval-work__card {
  padding: 12px 14px;
  border: 1px solid color-mix(in srgb, var(--warning) 58%, var(--border-light));
  border-radius: 10px;
  background: color-mix(in srgb, var(--warning) 8%, var(--bg-card));
}

.approval-work__card.is-resolved {
  border-color: var(--border-light);
  background: var(--bg-card);
}

.approval-work__title {
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 600;
}

.approval-work__summary,
.approval-work__command,
.approval-work__cwd,
.approval-work__risk,
.approval-work__scope,
.approval-work__resolved {
  margin-top: 7px;
  color: var(--text-secondary);
  font-size: 12px;
  overflow-wrap: anywhere;
}

.approval-work__command,
.approval-work__cwd {
  margin-top: 7px;
  color: var(--text-primary);
  font: 12px/1.5 var(--font-mono, monospace);
  overflow-wrap: anywhere;
}

.approval-work__risk {
  margin-top: 9px;
  color: var(--warning);
  font-size: 12px;
  line-height: 1.55;
}

.approval-work__scope {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.approval-work__scope code {
  padding: 2px 6px;
  border-radius: 4px;
  background: color-mix(in srgb, var(--bg-panel) 82%, transparent);
}

.approval-work__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 11px;
}

.approval-work__button {
  border: 1px solid var(--border-light);
  border-radius: 6px;
  padding: 5px 9px;
  color: var(--text-primary);
  background: var(--bg-panel);
  cursor: pointer;
  font-size: 12px;
}

.approval-work__button.is-primary {
  border-color: var(--primary-color);
  color: var(--primary-color);
}

.approval-work__button.is-danger {
  color: var(--danger);
}

.approval-work__button:disabled {
  cursor: wait;
  opacity: .55;
}

.terminal-work {
  width: min(100%, 780px);
  margin: 10px 0 2px;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--border-light) 88%, transparent);
  border-radius: 10px;
  background: color-mix(in srgb, var(--bg-panel) 86%, #101317);
  box-shadow: 0 8px 22px rgba(0, 0, 0, .08);
}

.terminal-work__header,
.terminal-work__meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.terminal-work__header {
  justify-content: space-between;
  padding: 8px 11px;
  border-bottom: 1px solid color-mix(in srgb, var(--border-light) 78%, transparent);
  color: var(--text-secondary);
  font-size: 12px;
}

.terminal-work__title {
  color: var(--text-primary);
  font-weight: 600;
}

.terminal-work__count,
.terminal-work__cwd,
.terminal-work__exit {
  color: var(--text-muted);
  font-size: 11px;
}

.terminal-work__item {
  padding: 9px 11px 10px;
  border-bottom: 1px solid color-mix(in srgb, var(--border-light) 62%, transparent);
}

.terminal-work__item:last-child { border-bottom: 0; }

.terminal-work__item.is-failed { background: color-mix(in srgb, var(--danger) 5%, transparent); }
.terminal-work__item.is-running { background: color-mix(in srgb, var(--primary-color) 4%, transparent); }

.terminal-work__meta {
  min-width: 0;
  flex-wrap: wrap;
  line-height: 1.45;
}

.terminal-work__command {
  flex: 1 1 100%;
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--text-primary);
  font: 12px/1.5 var(--font-mono, monospace);
}

.terminal-work__cwd { overflow-wrap: anywhere; }

.terminal-work__exit {
  margin-left: auto;
  color: var(--success);
}

.terminal-work__item.is-failed .terminal-work__exit { color: var(--danger); }
.terminal-work__running { color: var(--text-secondary); font-size: 12px; }

.terminal-work__output {
  max-height: 260px;
  margin: 8px 0 0;
  padding: 9px 10px;
  overflow: auto;
  border: 1px solid color-mix(in srgb, var(--border-light) 60%, transparent);
  border-radius: 6px;
  color: #d7e2ea;
  background: #101317;
  font: 12px/1.55 var(--font-mono, monospace);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.terminal-work__output.is-stderr { color: #f0b7ad; }
.terminal-work__truncated { margin-top: 6px; color: var(--warning); font-size: 11px; }

.file-work {
  width: min(100%, 780px);
  margin: 10px 0 2px;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--border-light) 88%, transparent);
  border-radius: 10px;
  background: color-mix(in srgb, var(--bg-panel) 86%, #101317);
}

.file-work__header,
.file-work__meta {
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-work__header {
  justify-content: space-between;
  padding: 8px 11px;
  border-bottom: 1px solid color-mix(in srgb, var(--border-light) 78%, transparent);
  color: var(--text-secondary);
  font-size: 12px;
}

.file-work__title { color: var(--text-primary); font-weight: 600; }
.file-work__count,
.file-work__count-detail { color: var(--text-muted); font-size: 11px; }
.file-work__item { padding: 9px 11px 10px; border-bottom: 1px solid color-mix(in srgb, var(--border-light) 62%, transparent); }
.file-work__item:last-child { border-bottom: 0; }
.file-work__item.is-failed { background: color-mix(in srgb, var(--danger) 5%, transparent); }
.file-work__item.is-running { background: color-mix(in srgb, var(--primary-color) 4%, transparent); }
.file-work__meta { flex-wrap: wrap; line-height: 1.45; }
.file-work__kind { color: var(--text-secondary); font-size: 12px; }
.file-work__path { color: var(--text-primary); font: 12px/1.5 var(--font-mono, monospace); overflow-wrap: anywhere; }
.file-work__summary { margin-top: 5px; color: var(--text-regular); font-size: 12px; }
.file-work__error { margin-top: 5px; color: var(--danger); font-size: 11px; }

.source-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background-color: var(--primary-fade);
  border-radius: 6px;
  font-size: 12px;
  color: var(--text-regular);
  margin-right: 4px;
  margin-bottom: 4px;
  border: 1px solid var(--primary-line);
  text-decoration: none;
}

.reasoning-path {
  padding-left: 8px;
  border-left: 1px solid var(--border-light);
  margin-left: 4px;
}

.reasoning-step {
  position: relative;
  padding-bottom: 12px;
  padding-left: 12px;
  
  &:last-child {
    padding-bottom: 0;
  }
  
  .step-dot {
    position: absolute;
    left: -5px;
    top: 6px;
    width: 8px;
    height: 8px;
    background-color: var(--primary-color);
    border-radius: 50%;
  }
  
  .step-title {
    font-weight: 500;
    font-size: 13px;
    color: var(--text-color-primary);
  }
  
  .step-desc {
    font-size: 12px;
    color: var(--text-color-secondary);
    margin-top: 2px;
  }
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(5px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes thinkingPulse {
  0%, 100% { opacity: 0.58; transform: scale(0.94); }
  50% { opacity: 1; transform: scale(1); }
}

@keyframes thinkingDot {
  0%, 60%, 100% { opacity: 0.28; transform: translateY(0); }
  30% { opacity: 0.9; transform: translateY(-2px); }
}

@keyframes continuationSignal {
  0%, 100% { opacity: 0.28; transform: scaleY(0.7); }
  50% { opacity: 0.95; transform: scaleY(1); }
}

@media (prefers-reduced-motion: reduce) {
  .thinking-status__icon,
  .thinking-status__dots i,
  .continuation-status__pulse i {
    animation: none !important;
  }

  .thinking-details-enter-active,
  .thinking-details-leave-active,
  .thinking-status__chevron,
  .continuation-status-enter-active,
  .continuation-status-leave-active {
    transition: none;
  }
}
</style>
