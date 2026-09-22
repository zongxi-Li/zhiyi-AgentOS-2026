<!-- 主对话页面 — 角色快速导航（律师/教师/程序员/作家）与聊天工作台 -->
<template>
  <div class="chat-view detail-interface">
    <div
      class="chat-main"
      :class="[
        {
          'has-agent-results': isAgentMode,
          'agent-panel-collapsed': isAgentMode && agentPanelCollapsed,
          'agent-panel-resizing': agentPanelResizing,
          'workspace-mode-switching': workspaceModeSwitching
        }
      ]"
      :style="agentPanelLayoutStyle"
    >
      <section
        ref="chatPanelRef"
        class="chat-panel"
        :class="{ 'hero-mode': showHeroMode }"
        :aria-busy="isLoadingConversation || isStreamingChat"
      >
        <Transition name="context-panel-slide" :css="!workspaceModeSwitching" @after-leave="finishContextPanelClose">
          <section
            v-if="isAgentMode && contextPanelOpen"
            class="context-panel"
            :class="{ resizing: contextPanelResizing }"
            :style="{ height: `${contextPanelHeight}px` }"
            aria-label="运行上下文"
          >
            <header class="context-panel__header">
              <div class="context-panel__identity">
                <el-icon><Cpu /></el-icon>
                <strong>运行上下文</strong>
                <span>{{ contextObjective }}</span>
              </div>
              <div class="context-panel__metrics">
                <span>{{ contextStepNodes.length }} 步骤</span>
                <span>{{ contextNodes.length }} 节点</span>
                <span>{{ contextEdges.length }} 关系</span>
                <button type="button" title="收起运行上下文" aria-label="收起运行上下文" @click="setContextPanelOpen(false)">
                  <el-icon><ArrowDownBold /></el-icon>
                </button>
              </div>
            </header>

            <nav class="context-panel__tabs" aria-label="运行上下文视图">
              <button
                v-for="tab in contextTabs"
                :key="tab.key"
                type="button"
                :class="{ active: contextPanelTab === tab.key }"
                @click="contextPanelTab = tab.key"
              >
                {{ tab.label }}
                <span>{{ tab.count }}</span>
              </button>
            </nav>

            <div class="context-panel__body">
              <div v-if="!contextNodes.length" class="context-panel__empty">
                启用 Workflow 后，这里会同步展示数据血缘、执行节点和任务步骤。
              </div>

              <div v-else-if="contextPanelTab === 'lineage'" class="context-lineage">
                <div v-for="edge in contextEdges" :key="edge.edgeId" class="context-lineage__row">
                  <span class="context-node-pill">{{ contextNodeLabel(edge.sourceId) }}</span>
                  <span class="context-edge-label">{{ contextEdgeLabel(edge.edgeType) }}</span>
                  <span class="context-lineage__arrow">→</span>
                  <span class="context-node-pill target">{{ contextNodeLabel(edge.targetId) }}</span>
                </div>
                <div v-if="!contextEdges.length" class="context-panel__empty">当前蓝图暂无血缘关系。</div>
              </div>

              <div v-else-if="contextPanelTab === 'nodes'" class="context-node-grid">
                <article v-for="node in contextNodes" :key="node.nodeId" class="context-node-card">
                  <span class="context-node-card__type">{{ contextNodeTypeLabel(node.nodeType) }}</span>
                  <strong>{{ node.name || node.agentName || node.nodeId }}</strong>
                  <small>{{ node.description || node.capability || node.nodeId }}</small>
                </article>
              </div>

              <div v-else class="context-step-list">
                <article v-for="(step, index) in contextStepNodes" :key="step.nodeId" class="context-step-item">
                  <span class="context-step-item__index">{{ String(index + 1).padStart(2, '0') }}</span>
                  <div>
                    <strong>{{ step.name || step.nodeId }}</strong>
                    <small>{{ step.agentName || step.capability || '等待分配 Agent' }}</small>
                  </div>
                  <span class="context-step-item__status" :class="{ done: displayCompletedStepIds.includes(step.nodeId) }">
                    {{ displayCompletedStepIds.includes(step.nodeId) ? '已完成' : '待执行' }}
                  </span>
                </article>
                <div v-if="!contextStepNodes.length" class="context-panel__empty">当前蓝图暂无任务步骤。</div>
              </div>
            </div>

            <div
              class="context-panel__resizer"
              role="separator"
              aria-label="调整运行上下文面板高度"
              aria-orientation="horizontal"
              :aria-valuemin="CONTEXT_PANEL_MIN_HEIGHT"
              :aria-valuemax="CONTEXT_PANEL_MAX_HEIGHT"
              :aria-valuenow="contextPanelHeight"
              tabindex="0"
              title="拖动调整高度，双击恢复默认"
              @pointerdown="startContextPanelResize"
              @keydown="handleContextPanelResizeKeydown"
              @dblclick="resetContextPanelHeight"
            ><span aria-hidden="true"></span></div>
          </section>
        </Transition>

        <button
          v-if="isAgentMode && !contextPanelOpen && !contextPanelClosing"
          class="context-panel-dock"
          type="button"
          aria-label="展开运行上下文"
          @click="setContextPanelOpen(true)"
        >
          <span class="context-panel-dock__pulse" aria-hidden="true"></span>
          <strong>运行上下文</strong>
          <span>{{ contextStepNodes.length }} 步骤</span>
          <span>{{ contextNodes.length }} 节点</span>
          <span>{{ contextEdges.length }} 关系</span>
          <el-icon><ArrowDownBold /></el-icon>
        </button>

        <div class="messages-shell">
          <div class="messages" ref="messagesRef">
          <div v-if="showHeroMode" class="empty-state">
            <div
              ref="heroLogoFieldRef"
              class="hero-logo-field"
              :class="{ 'is-pressed': heroLogoPressed }"
              aria-hidden="true"
              @pointermove="handleHeroLogoPointerMove"
              @pointerleave="handleHeroLogoPointerLeave"
              @pointerdown="handleHeroLogoPointerDown"
              @pointerup="handleHeroLogoPointerUp"
              @pointercancel="handleHeroLogoPointerUp"
            >
              <svg class="hero-logo-filter-defs" aria-hidden="true" focusable="false">
                <defs>
                  <filter id="hero-logo-fluid" x="-24%" y="-24%" width="148%" height="148%" color-interpolation-filters="sRGB">
                    <feTurbulence
                      ref="heroLogoTurbulenceRef"
                      type="fractalNoise"
                      baseFrequency="0.012 0.018"
                      numOctaves="2"
                      seed="11"
                      result="hero-logo-noise"
                    />
                    <feDisplacementMap
                      ref="heroLogoDisplacementRef"
                      in="SourceGraphic"
                      in2="hero-logo-noise"
                      scale="0"
                      xChannelSelector="R"
                      yChannelSelector="B"
                    />
                  </filter>
                </defs>
              </svg>
              <img class="hero-watermark" src="/logo.webp" alt="" />
            </div>
            <h2 class="hero-greeting">{{ heroGreeting }}</h2>
          </div>

          <section v-else-if="showWorkflowHistoryDetail" class="workflow-history-detail" aria-label="Agent 历史任务详情">
            <div v-if="!activeWorkflowRun" class="workflow-history-loading" :class="{ 'is-error': workflowResultState === 'error' || workflowResultState === 'partial' }">
              <template v-if="workflowResultState === 'loading' || workflowResultState === 'idle'">
                <el-icon class="is-loading"><Loading /></el-icon>
                <span>正在恢复任务详情…</span>
              </template>
              <template v-else>
                <strong>任务详情暂时未能加载</strong>
                <span>{{ workflowResultError || '请重新加载任务详情。' }}</span>
                <button type="button" @click="retryWorkflowHistoryDetail">重新加载</button>
              </template>
            </div>
            <template v-else>
              <div v-if="workflowResultState === 'partial'" class="workflow-history-partial" role="status">
                <span>{{ workflowResultError }}</span>
                <button type="button" @click="retryWorkflowHistoryDetail">补充加载</button>
              </div>
              <article class="workflow-history-request">
                <header>
                  <div>
                    <span class="workflow-history-eyebrow">历史任务输入</span>
                    <h3>{{ workflowHistoryTitle }}</h3>
                  </div>
                  <div class="workflow-history-identity">
                    <span>{{ activeWorkflowRun.workflowId }}</span>
                    <code>{{ activeWorkflowRun.runId }}</code>
                  </div>
                </header>
                <pre>{{ workflowHistoryInput }}</pre>
              </article>

              <GenericArtifactPanel
                :step-outputs="workflowHistoryStepOutputs"
                :final-artifacts="workflowHistoryFinalArtifacts"
                :final-report="workflowHistoryFinalReport"
                :status="activeWorkflowStatus"
              />
            </template>
          </section>

          <div v-else class="message-list">
            <div
              v-for="msg in chatStore.messages"
              :key="msg.id"
              class="message-row"
              :class="[msg.role, { 'rail-flash': railFlashId === msg.id }]"
              :data-message-id="String(msg.id)"
              :data-role="msg.role"
            >
              <MessageBubble
                :message="{
                  id: msg.id,
                  role: msg.role,
                  content: msg.content || '',
                  createdAt: msg.createdAt || (msg.timestamp ? new Date(msg.timestamp) : new Date()),
                  confidence: msg.confidence,
                  fileUrl: msg.fileUrl,
                  tokensUsed: msg.tokensUsed,
                  sources: msg.sources,
                  reasoningPath: msg.reasoningPath,
                  modelInfo: msg.modelInfo,
                  thinkingState: msg.thinkingState,
                  streamActivity: msg.streamActivity,
                  streamPhase: msg.streamPhase,
                  thinkingDurationMs: msg.thinkingDurationMs,
                  reasoningContent: msg.reasoningContent,
                  requestedThinkingMode: msg.requestedThinkingMode,
                  effectiveThinkingMode: msg.effectiveThinkingMode,
                  effectiveReasoningEffort: msg.effectiveReasoningEffort,
                  reasoningTokens: msg.reasoningTokens,
                  executionSummary: msg.executionSummary
                }"
              />
            </div>
          </div>
          </div>

          <nav
            v-if="conversationRailVisible"
            ref="conversationRailRef"
            class="conversation-rail"
            aria-label="对话导航"
            @pointerleave="handleRailLeave"
          >
            <div class="conversation-rail__ticks">
              <button
                v-for="item in conversationRailItems"
                :key="item.id"
                type="button"
                class="conversation-rail__tick"
                :class="{ 'is-active': item.id === activeRailTickId }"
                :aria-label="`跳转到第 ${item.round} 轮对话`"
                @click="jumpToRailInteraction(item.id)"
                @pointerenter="handleRailHover(item, $event)"
              ></button>
            </div>
            <Transition name="rail-preview">
              <div
                v-if="railHoverItem"
                class="conversation-rail__preview"
                :style="{ top: `${railPreviewTop}px` }"
              >
                <span class="conversation-rail__preview-round">第 {{ railHoverItem.round }} 轮 · 提问预览</span>
                <p>{{ railHoverItem.preview }}</p>
              </div>
            </Transition>
          </nav>
        </div>

        <div ref="composerRef" class="composer" :style="{ bottom: composerDockOffset }">
          <div v-if="isSubmittingWorkflow || activeWorkflowRunId" class="chat-workflow-progress">
            <WorkflowProgressBar
              :progress="workflowProgressState.progress.value"
              :loading="isSubmittingWorkflow || workflowProgressState.isLoading.value"
              :sync-error="workflowProgressState.syncError.value"
              variant="compact"
            />
            <AgentOsRunSummaryCard
              :progress="workflowProgressState.progress.value"
              :run="activeWorkflowRun"
              :view="activeAcgView"
              :events="activeAcgAuditEvents"
            />
          </div>

          <p v-if="workflowStartError" class="chat-workflow-error" role="alert">
            {{ workflowStartError }}
          </p>

          <WorkflowReviewPanel
            v-if="activeWorkflowRunId && activeWorkflowStatus === 'waiting_review'"
            class="chat-workflow-review"
            :run-id="activeWorkflowRunId"
            :progress="workflowProgressState.progress.value"
            :run="activeWorkflowRun"
            compact
            @reviewed="handleChatWorkflowReviewed"
            @conflict="handleChatReviewConflict"
          />

          <div
            v-if="activeWorkflowRunId && !isAgentMode"
            class="workflow-run-strip"
            :class="activeWorkflowStatus"
          >
            <span class="workflow-run-strip__state">
              <span class="workflow-run-strip__dot" aria-hidden="true"></span>
              {{ activeWorkflowStatusLabel }}
            </span>
            <code :title="activeWorkflowRunId">{{ activeWorkflowRunId }}</code>
            <span class="workflow-run-strip__workflow">{{ activeWorkflowRun?.workflowId || activeWorkflowBinding?.workflowId || 'WorkflowRun' }}</span>
            <div class="workflow-run-strip__actions">
              <button type="button" @click="openActiveWorkflowOperations">
                <span>查看 ACG</span>
                <el-icon><DArrowRight /></el-icon>
              </button>
              <button type="button" @click="openActiveWorkflowConsole">
                <span>运行控制</span>
                <el-icon><DArrowRight /></el-icon>
              </button>
            </div>
          </div>

          <div v-if="showHeroMode" class="composer-missions">
            <div ref="missionAnchorRef" class="mission-anchor">
              <button
                class="mission-chip"
                type="button"
                :aria-expanded="missionMenuOpen"
                aria-haspopup="listbox"
                title="选择对话记录进入 Mission"
                @click="toggleMissionMenu"
              >
                <el-icon><Clock /></el-icon>
                <span>{{ isAgentMode ? '运行记录' : '对话记录' }}</span>
                <el-icon class="mission-chip__chevron"><ArrowDownBold /></el-icon>
              </button>
              <Transition name="mission-pop">
                <div v-if="missionMenuOpen" class="mission-menu" role="listbox" aria-label="选择对话记录进入 Mission">
                  <div v-if="missionRecordsLoading" class="mission-menu-hint">正在加载…</div>
                  <template v-else-if="isAgentMode">
                    <button
                      v-for="run in missionRecentRuns"
                      :key="run.runId"
                      class="mission-option"
                      type="button"
                      role="option"
                      :title="resolveAcgTaskTitle(run)"
                      @click="openMissionRecord(run, null)"
                    >
                      <strong>{{ resolveAcgTaskTitle(run) }}</strong>
                      <span>{{ missionRunState(run) }}</span>
                    </button>
                    <div v-if="!missionRecentRuns.length" class="mission-menu-hint">暂无运行记录</div>
                  </template>
                  <template v-else>
                    <button
                      v-for="conversation in missionRecentConversations"
                      :key="conversation.id"
                      class="mission-option"
                      type="button"
                      role="option"
                      :title="conversation.title || '未命名对话'"
                      @click="openMissionRecord(null, conversation)"
                    >
                      <strong>{{ conversation.title || '未命名对话' }}</strong>
                      <span>{{ formatMissionTime(conversation.updatedAt || conversation.createdAt) }}</span>
                    </button>
                    <div v-if="!missionRecentConversations.length" class="mission-menu-hint">暂无历史对话</div>
                  </template>
                </div>
              </Transition>
            </div>
          </div>

          <div class="composer-card">
            <el-input
              v-model="inputText"
              type="textarea"
              :rows="1"
              :autosize="{ minRows: 1, maxRows: 6 }"
              resize="none"
              :placeholder="$t('chat.placeholder')"
              @keydown="handleKeydown"
            />
              <div class="composer-footer">
                <div class="left-actions">
                <div ref="composerToolsAnchorRef" class="composer-tools-anchor">
                  <button
                    class="composer-icon-action composer-tools-toggle"
                    :class="{ active: composerToolsOpen }"
                    type="button"
                    aria-label="更多输入工具"
                    aria-haspopup="menu"
                    :aria-expanded="composerToolsOpen"
                    title="更多输入工具"
                    @click="toggleComposerTools"
                  >
                    <el-icon><Plus /></el-icon>
                  </button>
                  <Transition name="composer-tools-pop">
                    <div v-if="composerToolsOpen" class="composer-tools-menu" role="menu" aria-label="输入工具">
                      <button class="composer-tools-menu__item" type="button" role="menuitem" @click="openComposerFileManager">
                        <el-icon><UploadFilled /></el-icon>
                        <span>添加文件</span>
                      </button>
                      <div v-if="!isAgentMode" class="composer-tools-menu__runtime">
                        <span class="composer-tools-menu__label">模型设置</span>
                        <ModelRuntimeControls compact />
                      </div>
                    </div>
                  </Transition>
                </div>
                <PermissionSelector v-if="isAgentMode" />
                <button
                  v-if="isAgentMode"
                  class="composer-acg-toggle"
                  :class="{ active: workflowPanelOpen }"
                  type="button"
                  :aria-pressed="workflowPanelOpen"
                  :title="workflowPanelOpen ? '收起 ACG 拓扑' : '展开 ACG 拓扑'"
                  @click="toggleWorkflowPanel"
                >
                  <el-icon><Share /></el-icon>
                  <span>ACG</span>
                </button>
                <el-tooltip v-if="contextUsage.visible" placement="top" :show-after="200">
                  <template #content>
                    <div class="context-usage-tip">
                      <div>上下文窗口</div>
                      <div>{{ contextUsage.percent }}% 已用</div>
                      <div>已用 {{ contextUsage.usedLabel }}，共 {{ contextUsage.windowLabel }}</div>
                    </div>
                  </template>
                  <button
                    class="context-usage"
                    :class="contextUsage.level"
                    type="button"
                    title="上下文窗口用量"
                  >
                    {{ contextUsage.percent }}%
                  </button>
                </el-tooltip>
              </div>
              <div class="right-actions">
                <ModelRuntimeControls composer />
                <span v-if="inputText.length" class="word-count" :class="{ warning: inputText.length > 500 }">
                  {{ inputText.length }} 字
                </span>
                <button
                  class="composer-icon-action"
                  type="button"
                  :class="{ active: isRecording }"
                  :aria-label="isRecording ? '停止录音' : '语音输入'"
                  :title="isRecording ? '停止录音' : '语音输入'"
                  @click="isRecording ? stopVoiceInput() : startVoiceInput()"
                >
                  <el-icon><Microphone /></el-icon>
                </button>
                <el-button v-if="inputText.length > 500" text @click="autoSegment">自动分段</el-button>
                <el-button
                  v-if="isStreamingChat"
                  class="composer-cancel"
                  type="danger"
                  @click="cancelMessageStream"
                >
                  <span>停止</span>
                </el-button>
                <el-button class="composer-send" type="primary" :disabled="isSendDisabled" @click="sendMessage">
                  <el-icon v-if="!loading"><ArrowUp /></el-icon>
                  <el-icon v-else class="is-loading"><Loading /></el-icon>
                </el-button>
              </div>
            </div>
          </div>
        </div>

        <Transition name="workflow-acg-slide" :css="!workspaceModeSwitching">
          <section
            v-if="isAgentMode && workflowPanelOpen"
            class="workflow-acg-panel"
            :class="{ resizing: workflowPanelResizing }"
            :style="{ height: `${workflowPanelHeight}px` }"
            aria-label="ACG 动态拓扑"
          >
            <div
              class="workflow-panel-resizer"
              role="separator"
              aria-label="调整 ACG 拓扑面板高度"
              aria-orientation="horizontal"
              :aria-valuemin="WORKFLOW_PANEL_MIN_HEIGHT"
              :aria-valuemax="getWorkflowPanelHardMaxHeight()"
              :aria-valuenow="workflowPanelHeight"
              tabindex="0"
              title="拖动调整高度，双击恢复默认"
              @pointerdown="startWorkflowPanelResize"
              @keydown="handleWorkflowPanelResizeKeydown"
              @dblclick="resetWorkflowPanelHeight"
            >
              <span aria-hidden="true"></span>
            </div>
            <AcgTopologyGraph
              :blueprint="displayAcgBlueprint"
              :completed-step-ids="displayCompletedStepIds"
              :step-states="activeAcgView?.stepStates"
              collapsible
              @collapse="setWorkflowPanelOpen(false)"
            />
            <RuntimeAuditTimeline
              v-if="activeAcgView"
              class="chat-runtime-timeline"
              :events="activeAcgAuditEvents"
              :patch-refs="activeWorkflowRun?.executionState?.graphPatchRefs || []"
              :max-items="8"
            />
            <div v-if="isLoadingWorkflowResult && !activeAcgView" class="workflow-acg-loading">正在加载动态拓扑…</div>
          </section>
        </Transition>
        <button
          v-if="isAgentMode && !workflowPanelOpen"
          class="workflow-acg-dock"
          :class="{ idle: !hasActiveWorkflow }"
          type="button"
          aria-label="展开 ACG 动态拓扑"
          @click="setWorkflowPanelOpen(true)"
        >
          <span class="workflow-acg-dock__pulse" aria-hidden="true"></span>
          <span>ACG 动态拓扑</span>
          <span class="workflow-acg-dock__meta">
            {{ hasActiveWorkflow ? `${displayAcgBlueprint?.nodes.length || 0} 节点` : '等待任务' }}
          </span>
          <el-icon><ArrowUp /></el-icon>
        </button>
      </section>

      <Transition name="agent-panel-slide">
        <aside
          v-if="isAgentMode"
          class="agent-panel"
          :class="{ collapsed: agentPanelCollapsed, resizing: agentPanelResizing }"
        >
          <div
            v-if="!agentPanelCollapsed"
            class="agent-panel-resizer"
            role="separator"
            aria-label="调整右侧工作台宽度"
            aria-orientation="vertical"
            :aria-valuemin="AGENT_PANEL_MIN_WIDTH"
            :aria-valuemax="AGENT_PANEL_MAX_WIDTH"
            :aria-valuenow="agentPanelWidth"
            tabindex="0"
            title="拖动调整宽度，双击恢复默认"
            @pointerdown="startAgentPanelResize"
            @keydown="handleAgentPanelResizeKeydown"
            @dblclick="resetAgentPanelWidth"
          ></div>

          <div class="agent-panel-toggle-row">
            <button
              class="agent-panel-toggle"
              type="button"
              :aria-label="agentPanelCollapsed ? '展开右侧工作台' : '收起右侧工作台'"
              :title="agentPanelCollapsed ? '展开右侧工作台' : '收起右侧工作台'"
              @click="agentPanelCollapsed = !agentPanelCollapsed"
            >
              <el-icon>
                <DArrowLeft v-if="agentPanelCollapsed" />
                <DArrowRight v-else />
              </el-icon>
              <span v-if="!agentPanelCollapsed">收起</span>
            </button>
          </div>

          <div v-if="agentPanelCollapsed" class="agent-panel-rail" aria-hidden="true">
            <span class="agent-panel-rail-icon">
              <el-icon><component :is="agentIcon" /></el-icon>
            </span>
          </div>

          <div ref="agentPanelContentRef" v-show="!agentPanelCollapsed" class="agent-panel-content">
            <AcgRunInspector
              :run-id="activeWorkflowRunId"
              :status="activeWorkflowStatus"
              :status-label="activeWorkflowStatusLabel"
              :run="activeWorkflowRun"
              :view="activeAcgView"
              :progress="workflowProgressState.progress.value"
              :blueprint="displayAcgBlueprint"
              :loading="isSubmittingWorkflow || isLoadingWorkflowResult || workflowProgressState.isLoading.value"
              @open-acg="openActiveWorkflowOperations"
              @open-console="openActiveWorkflowConsole"
            />
          </div>
      </aside>
      </Transition>
    </div>

    <FileManager v-model="showFileManager" @fileSelected="handleFileSelected" />
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import axios from 'axios'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowDownBold,
  ArrowUp,
  Clock,
  Cpu,
  DArrowLeft,
  DArrowRight,
  Loading,
  Microphone,
  Plus,
  Share,
  UploadFilled
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import MessageBubble from '@/components/MessageBubble.vue'
import ModelRuntimeControls from '@/components/ModelRuntimeControls.vue'
import PermissionSelector from '@/components/PermissionSelector.vue'
const FileManager = defineAsyncComponent(() => import('@/components/FileManager.vue').then(module => module.default))
const AcgTopologyGraph = defineAsyncComponent(() => import('@/components/agentos/AcgTopologyGraph.vue'))
import WorkflowProgressBar from '@/components/agentos/WorkflowProgressBar.vue'
const WorkflowReviewPanel = defineAsyncComponent(() => import('@/components/agentos/WorkflowReviewPanel.vue').then(module => module.default))
import AgentOsRunSummaryCard from '@/components/agentos/AgentOsRunSummaryCard.vue'
const RuntimeAuditTimeline = defineAsyncComponent(() => import('@/components/agentos/RuntimeAuditTimeline.vue').then(module => module.default))
const AcgRunInspector = defineAsyncComponent(() => import('@/components/agentos/AcgRunInspector.vue').then(module => module.default))
const GenericArtifactPanel = defineAsyncComponent(() => import('@/features/acg/GenericArtifactPanel.vue').then(module => module.default))
import {
  agentosApi,
  type AcgDeliverable,
  type AcgFinalArtifact,
  type AcgView,
  type WorkflowRun
} from '@/services/api/agentos'
import type { WorkflowProgress } from '@/services/api/workflow'
import { workflowApi, type WorkflowRunSummary } from '@/services/api/workflow'
import { conversationApi, type Conversation } from '@/services/api/conversation'
import { useChatStore, type ChatWorkflowBinding, type Message } from '@/stores/chat'
import { useWorkflowProgress } from '@/composables/useWorkflowProgress'
import { setConversationWorkspace } from '@/utils/conversationWorkspace'
import { wasErrorUserNotified } from '@/utils/request'
import { resolveAcgTaskTitle } from '@/utils/acgTaskTitle'
import { ACG_HISTORY_SOURCES, acgHistoryRoleDomain, loadAcgHistoryRole } from '@/utils/acgHistoryFilter'
import { loadModelSettings } from '@/config/modelSettings'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const chatStore = useChatStore()
const createClientRequestId = (): string => {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0'))
  return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex.slice(6, 8).join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10).join('')}`
}
type WorkspaceMode = 'agent' | 'chat'
const WORKSPACE_MODE_KEY = 'layout.workspace_mode'
const DRAFT_CONVERSATION_KEY = 'chat.workflow_draft_conversation_id'
const WORKFLOW_SUBMISSION_KEY_PREFIX = 'chat.workflow_submission.'
const draftConversationId = ref(
  localStorage.getItem(DRAFT_CONVERSATION_KEY) || `draft:${createClientRequestId()}`
)
localStorage.setItem(DRAFT_CONVERSATION_KEY, draftConversationId.value)
const workspaceMode = ref<WorkspaceMode>(
  route.query.workspace === 'agent' || localStorage.getItem(WORKSPACE_MODE_KEY) === 'agent'
    ? 'agent'
    : 'chat'
)
const workspaceModeSwitching = ref(false)

const inputText = ref('')
const loading = ref(false)
const showFileManager = ref(false)
const isRecording = ref(false)
const messagesRef = ref<HTMLElement | null>(null)
const composerRef = ref<HTMLElement | null>(null)
const chatPanelRef = ref<HTMLElement | null>(null)
const heroLogoFieldRef = ref<HTMLElement | null>(null)
const heroLogoTurbulenceRef = ref<SVGFETurbulenceElement | null>(null)
const heroLogoDisplacementRef = ref<SVGFEDisplacementMapElement | null>(null)
const heroLogoPressed = ref(false)
const isNearBottom = ref(true)
const pendingMessageCount = ref(0)
const AGENT_PANEL_COLLAPSED_KEY = 'chat.agent_panel_collapsed'
const AGENT_PANEL_WIDTH_KEY = 'chat.agent_panel_width'
const AGENT_PANEL_DEFAULT_WIDTH = 340
const AGENT_PANEL_MIN_WIDTH = 280
const AGENT_PANEL_MAX_WIDTH = 520
const WORKFLOW_PANEL_HEIGHT_KEY = 'chat.workflow_panel_height'
const WORKFLOW_PANEL_OPEN_KEY = 'chat.workflow_panel_open_v2'
const WORKFLOW_PANEL_DEFAULT_HEIGHT = 280
const WORKFLOW_PANEL_MIN_HEIGHT = 180
const CONTEXT_PANEL_HEIGHT_KEY = 'chat.context_panel_height'
const CONTEXT_PANEL_OPEN_KEY = 'chat.context_panel_open'
const CONTEXT_PANEL_DEFAULT_HEIGHT = 250
const CONTEXT_PANEL_MIN_HEIGHT = 170
const CONTEXT_PANEL_MAX_HEIGHT = 420
const agentPanelCollapsed = ref(localStorage.getItem(AGENT_PANEL_COLLAPSED_KEY) === '1')
const storedAgentPanelWidth = Number(localStorage.getItem(AGENT_PANEL_WIDTH_KEY))
const agentPanelWidth = ref(
  Number.isFinite(storedAgentPanelWidth) && storedAgentPanelWidth >= AGENT_PANEL_MIN_WIDTH && storedAgentPanelWidth <= AGENT_PANEL_MAX_WIDTH
    ? storedAgentPanelWidth
    : AGENT_PANEL_DEFAULT_WIDTH
)
const agentPanelResizing = ref(false)
const storedWorkflowPanelHeight = Number(localStorage.getItem(WORKFLOW_PANEL_HEIGHT_KEY))
const workflowPanelHeight = ref(
  Number.isFinite(storedWorkflowPanelHeight) && storedWorkflowPanelHeight >= WORKFLOW_PANEL_MIN_HEIGHT
    ? storedWorkflowPanelHeight
    : WORKFLOW_PANEL_DEFAULT_HEIGHT
)
const workflowPanelResizing = ref(false)
const workflowPanelOpen = ref(localStorage.getItem(WORKFLOW_PANEL_OPEN_KEY) === '1')
const storedContextPanelHeight = Number(localStorage.getItem(CONTEXT_PANEL_HEIGHT_KEY))
const contextPanelHeight = ref(
  Number.isFinite(storedContextPanelHeight) && storedContextPanelHeight >= CONTEXT_PANEL_MIN_HEIGHT && storedContextPanelHeight <= CONTEXT_PANEL_MAX_HEIGHT
    ? storedContextPanelHeight
    : CONTEXT_PANEL_DEFAULT_HEIGHT
)
const contextPanelOpen = ref(localStorage.getItem(CONTEXT_PANEL_OPEN_KEY) === '1')
const contextPanelClosing = ref(false)
const contextPanelResizing = ref(false)
const contextPanelTab = ref<'lineage' | 'nodes' | 'steps'>('lineage')
const activeWorkflowRunId = ref('')
const activeWorkflowBinding = ref<ChatWorkflowBinding | null>(null)
const activeWorkflowRun = ref<WorkflowRun | null>(null)
const activeAcgView = ref<AcgView | null>(null)
const isSubmittingWorkflow = ref(false)
const isLoadingWorkflowResult = ref(false)
type WorkflowResultState = 'idle' | 'loading' | 'ready' | 'partial' | 'error'
type WorkflowResultCacheEntry = { run?: WorkflowRun; view?: AcgView }
const workflowResultState = ref<WorkflowResultState>('idle')
const workflowResultError = ref<string | null>(null)
const workflowStartError = ref<string | null>(null)
const currentConversationId = computed(() => {
  const routeContextId = typeof route.query.contextId === 'string' ? route.query.contextId.trim() : ''
  return routeContextId || chatStore.contextId || draftConversationId.value
})
const isStreamingChat = computed(() => chatStore.isStreaming)
const cancelMessageStream = () => {
  const cancel = (chatStore as typeof chatStore & { cancelMessageStream?: () => unknown }).cancelMessageStream
  if (typeof cancel === 'function') void cancel()
}
const isLoadingConversation = computed(() => chatStore.isLoadingConversation)
const workflowProgressState = useWorkflowProgress({
  intervalMs: 2000,
  onProgressChanged: handleWorkflowProgressChanged,
  onTerminal: handleWorkflowTerminal
})
const hasActiveWorkflow = computed(() => Boolean(activeWorkflowRunId.value))
const showWorkflowHistoryDetail = computed(() => (
  Boolean(activeWorkflowRunId.value) && (
    chatStore.messages.length === 0
    || (
      isAgentMode.value
      && (
        workflowProgressState.progress.value?.phase === 'completed'
        || workflowProgressState.progress.value?.status === 'completed'
      )
      && !['idle', 'loading'].includes(workflowResultState.value)
    )
  )
))
const showHeroMode = computed(() => {
  return chatStore.messages.length === 0
    && !isSubmittingWorkflow.value
    && !activeWorkflowRunId.value
})
const composerDockOffset = computed(() => {
  if (showHeroMode.value) return 'auto'
  if (!isAgentMode.value) return '0px'
  return workflowPanelOpen.value ? `${workflowPanelHeight.value}px` : '30px'
})
const composerHeight = ref(180)
const composerReservedSpace = computed(() => {
  if (showHeroMode.value) return 0
  const dockHeight = isAgentMode.value
    ? (workflowPanelOpen.value ? workflowPanelHeight.value : 30)
    : 0
  return Math.ceil(composerHeight.value + dockHeight + 24)
})
const agentPanelLayoutStyle = computed(() => ({
  '--agent-panel-width': `${agentPanelWidth.value}px`,
  '--composer-clearance': `${composerReservedSpace.value}px`
}))
let agentPanelResizeStartX = 0
let agentPanelResizeStartWidth = AGENT_PANEL_DEFAULT_WIDTH
let workflowPanelResizeStartY = 0
let workflowPanelResizeStartHeight = WORKFLOW_PANEL_DEFAULT_HEIGHT
let workflowPanelResizeMaxHeight = Number.MAX_SAFE_INTEGER
let contextPanelResizeStartY = 0
let contextPanelResizeStartHeight = CONTEXT_PANEL_DEFAULT_HEIGHT
let workflowResultController: AbortController | null = null
let workflowResultGeneration = 0
let workflowResultInFlight: { runId: string; promise: Promise<boolean> } | null = null
let workflowResultRetryTimer: ReturnType<typeof window.setTimeout> | null = null
let workflowResultRetryCount = 0
let conversationGeneration = 0
const terminalResultLoaded = new Set<string>()
const workflowResultCache = new Map<string, WorkflowResultCacheEntry>()
let composerResizeObserver: ResizeObserver | undefined
const agentPanelContentRef = ref<HTMLElement | null>(null)

const displayAcgBlueprint = computed(() => activeAcgView.value?.acgBlueprint || null)
const displayCompletedStepIds = computed(() => activeAcgView.value?.completedStepIds || [])
const activeAcgAuditEvents = computed(() => {
  const events = [
    ...(activeAcgView.value?.recoveryTrace || []),
    ...(activeAcgView.value?.scheduleTrace || []),
    ...(activeAcgView.value?.contractViolations || [])
  ]
  const seen = new Set<string>()
  return events.filter((event, index) => {
    const key = event.eventId || `${event.eventType}:${event.createdAt || index}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
})
const contextNodes = computed(() => displayAcgBlueprint.value?.nodes || [])
const contextEdges = computed(() => displayAcgBlueprint.value?.edges || [])
const contextStepNodes = computed(() => contextNodes.value.filter(node => node.nodeType === 'step'))
const contextObjective = computed(() => {
  return displayAcgBlueprint.value?.objective || activeWorkflowRun.value?.workflowId || '等待工作流'
})
const historyText = (value: unknown): string => typeof value === 'string' ? value.trim() : ''
const workflowHistoryInput = computed(() => {
  return historyText(activeWorkflowRun.value?.title) || '任务原文不属于运行状态，请从原会话查看。'
})
const workflowHistoryTitle = computed(() => {
  const run = activeWorkflowRun.value
  if (!run) return 'Agent 历史任务'
  return resolveAcgTaskTitle({
    title: workflowHistoryInput.value,
    workflowId: run.workflowId
  })
})
const workflowHistoryStepOutputs = computed<AcgDeliverable[]>(() => {
  const projected = activeAcgView.value?.stepOutputs?.length
    ? activeAcgView.value.stepOutputs
    : activeAcgView.value?.deliverables
  return projected || []
})
const workflowHistoryFinalArtifacts = computed<AcgFinalArtifact[]>(() => {
  return activeAcgView.value?.finalArtifacts || []
})
const workflowHistoryFinalReport = computed(() => {
  if (historyText(activeAcgView.value?.finalReport)) return activeAcgView.value?.finalReport || null
  return null
})
const activeWorkflowStatus = computed(() => (
  workflowProgressState.progress.value?.status
  || activeWorkflowRun.value?.status
  || activeAcgView.value?.status
  || [...chatStore.messages].reverse().find(message => message.workflowRunId === activeWorkflowRunId.value)?.workflowStatus
  || 'pending'
))
const activeWorkflowStatusLabel = computed(() => ({
  pending: '等待规划',
  planning: '规划中',
  running: '运行中',
  waiting_review: '等待人工审核',
  retrying: '正在重试',
  failed: '运行失败',
  completed: '运行完成',
  cancelled: '已取消'
}[activeWorkflowStatus.value] || activeWorkflowStatus.value))
const contextTabs = computed(() => [
  { key: 'lineage' as const, label: '数据血缘', count: contextEdges.value.length },
  { key: 'nodes' as const, label: '节点', count: contextNodes.value.length },
  { key: 'steps' as const, label: '任务步骤', count: contextStepNodes.value.length }
])
const contextNodeLabel = (nodeId: string) => {
  const node = contextNodes.value.find(item => item.nodeId === nodeId)
  return node?.name || node?.agentName || nodeId
}
const contextEdgeLabel = (edgeType: string) => ({
  dependency: '依赖',
  communication: '通信',
  control_flow: '控制流',
  execution: '执行',
  write: '写入',
  read: '读取',
  support: '支撑'
}[edgeType] || edgeType)
const contextNodeTypeLabel = (nodeType: string) => ({
  step: '步骤',
  agent: '智能体',
  skill: '技能',
  memory: '记忆',
  evidence: '证据',
  control: '控制'
}[nodeType] || nodeType)
const clampAgentPanelWidth = (width: number) => {
  return Math.min(AGENT_PANEL_MAX_WIDTH, Math.max(AGENT_PANEL_MIN_WIDTH, Math.round(width)))
}

const persistAgentPanelWidth = () => {
  localStorage.setItem(AGENT_PANEL_WIDTH_KEY, String(agentPanelWidth.value))
}

const handleAgentPanelResizeMove = (event: PointerEvent) => {
  if (!agentPanelResizing.value) return
  agentPanelWidth.value = clampAgentPanelWidth(agentPanelResizeStartWidth + agentPanelResizeStartX - event.clientX)
}

const stopAgentPanelResize = () => {
  if (!agentPanelResizing.value) return
  agentPanelResizing.value = false
  persistAgentPanelWidth()
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  window.removeEventListener('pointermove', handleAgentPanelResizeMove)
  window.removeEventListener('pointerup', stopAgentPanelResize)
  window.removeEventListener('pointercancel', stopAgentPanelResize)
}

const startAgentPanelResize = (event: PointerEvent) => {
  if (event.button !== 0) return
  event.preventDefault()
  agentPanelResizeStartX = event.clientX
  agentPanelResizeStartWidth = agentPanelWidth.value
  agentPanelResizing.value = true
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  window.addEventListener('pointermove', handleAgentPanelResizeMove)
  window.addEventListener('pointerup', stopAgentPanelResize)
  window.addEventListener('pointercancel', stopAgentPanelResize)
}

const resetAgentPanelWidth = () => {
  agentPanelWidth.value = AGENT_PANEL_DEFAULT_WIDTH
  persistAgentPanelWidth()
}

const handleAgentPanelResizeKeydown = (event: KeyboardEvent) => {
  if (event.key === 'Home') {
    agentPanelWidth.value = AGENT_PANEL_MIN_WIDTH
  } else if (event.key === 'End') {
    agentPanelWidth.value = AGENT_PANEL_MAX_WIDTH
  } else if (event.key === 'ArrowLeft') {
    agentPanelWidth.value = clampAgentPanelWidth(agentPanelWidth.value + 8)
  } else if (event.key === 'ArrowRight') {
    agentPanelWidth.value = clampAgentPanelWidth(agentPanelWidth.value - 8)
  } else {
    return
  }

  event.preventDefault()
  persistAgentPanelWidth()
}

const getWorkflowPanelHardMaxHeight = () => {
  const panelHeight = chatPanelRef.value?.clientHeight || window.innerHeight
  const topPanelHeight = contextPanelOpen.value ? contextPanelHeight.value : 30
  // The composer is absolutely positioned and follows the ACG panel edge,
  // so reserving its height here prevents the panel from ever reaching the top.
  const availableHeight = Math.max(0, panelHeight - topPanelHeight)
  return Math.max(WORKFLOW_PANEL_MIN_HEIGHT, Math.floor(availableHeight))
}

const clampWorkflowPanelHeight = (height: number, maxHeight = getWorkflowPanelHardMaxHeight()) => {
  const safeMaxHeight = Math.max(WORKFLOW_PANEL_MIN_HEIGHT, maxHeight)
  return Math.min(safeMaxHeight, Math.max(WORKFLOW_PANEL_MIN_HEIGHT, Math.round(height)))
}

const handleWorkflowPanelViewportResize = () => {
  const nextHeight = clampWorkflowPanelHeight(workflowPanelHeight.value)
  if (nextHeight !== workflowPanelHeight.value) workflowPanelHeight.value = nextHeight
}

const persistWorkflowPanelHeight = () => {
  localStorage.setItem(WORKFLOW_PANEL_HEIGHT_KEY, String(workflowPanelHeight.value))
}

const handleWorkflowPanelResizeMove = (event: PointerEvent) => {
  if (!workflowPanelResizing.value) return
  workflowPanelHeight.value = clampWorkflowPanelHeight(
    workflowPanelResizeStartHeight + workflowPanelResizeStartY - event.clientY,
    workflowPanelResizeMaxHeight
  )
}

const stopWorkflowPanelResize = () => {
  if (!workflowPanelResizing.value) return
  workflowPanelResizing.value = false
  persistWorkflowPanelHeight()
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  window.removeEventListener('pointermove', handleWorkflowPanelResizeMove)
  window.removeEventListener('pointerup', stopWorkflowPanelResize)
  window.removeEventListener('pointercancel', stopWorkflowPanelResize)
}

const startWorkflowPanelResize = (event: PointerEvent) => {
  if (event.button !== 0) return
  event.preventDefault()
  workflowPanelResizeStartY = event.clientY
  workflowPanelResizeStartHeight = workflowPanelHeight.value
  workflowPanelResizeMaxHeight = getWorkflowPanelHardMaxHeight()
  workflowPanelResizing.value = true
  document.body.style.cursor = 'row-resize'
  document.body.style.userSelect = 'none'
  window.addEventListener('pointermove', handleWorkflowPanelResizeMove)
  window.addEventListener('pointerup', stopWorkflowPanelResize)
  window.addEventListener('pointercancel', stopWorkflowPanelResize)
}

const resetWorkflowPanelHeight = () => {
  workflowPanelHeight.value = clampWorkflowPanelHeight(WORKFLOW_PANEL_DEFAULT_HEIGHT)
  persistWorkflowPanelHeight()
}

const setWorkflowPanelOpen = (open: boolean) => {
  workflowPanelOpen.value = open
  localStorage.setItem(WORKFLOW_PANEL_OPEN_KEY, open ? '1' : '0')
}

const toggleWorkflowPanel = () => {
  const open = !workflowPanelOpen.value
  setWorkflowPanelOpen(open)
  if (open && activeWorkflowRunId.value) void loadActiveAcgView(activeWorkflowRunId.value)
}

const handleWorkflowPanelResizeKeydown = (event: KeyboardEvent) => {
  const step = event.shiftKey ? 24 : 8
  if (event.key === 'Home') {
    workflowPanelHeight.value = WORKFLOW_PANEL_MIN_HEIGHT
  } else if (event.key === 'End') {
    workflowPanelHeight.value = getWorkflowPanelHardMaxHeight()
  } else if (event.key === 'ArrowUp') {
    workflowPanelHeight.value = clampWorkflowPanelHeight(
      workflowPanelHeight.value + step,
      getWorkflowPanelHardMaxHeight()
    )
  } else if (event.key === 'ArrowDown') {
    workflowPanelHeight.value = clampWorkflowPanelHeight(workflowPanelHeight.value - step)
  } else {
    return
  }
  event.preventDefault()
  persistWorkflowPanelHeight()
}

const clampContextPanelHeight = (height: number) => {
  return Math.min(CONTEXT_PANEL_MAX_HEIGHT, Math.max(CONTEXT_PANEL_MIN_HEIGHT, Math.round(height)))
}

const persistContextPanelHeight = () => {
  localStorage.setItem(CONTEXT_PANEL_HEIGHT_KEY, String(contextPanelHeight.value))
}

const handleContextPanelResizeMove = (event: PointerEvent) => {
  if (!contextPanelResizing.value) return
  contextPanelHeight.value = clampContextPanelHeight(
    contextPanelResizeStartHeight + event.clientY - contextPanelResizeStartY
  )
}

const stopContextPanelResize = () => {
  if (!contextPanelResizing.value) return
  contextPanelResizing.value = false
  persistContextPanelHeight()
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
  window.removeEventListener('pointermove', handleContextPanelResizeMove)
  window.removeEventListener('pointerup', stopContextPanelResize)
  window.removeEventListener('pointercancel', stopContextPanelResize)
}

const startContextPanelResize = (event: PointerEvent) => {
  if (event.button !== 0) return
  event.preventDefault()
  contextPanelResizeStartY = event.clientY
  contextPanelResizeStartHeight = contextPanelHeight.value
  contextPanelResizing.value = true
  document.body.style.cursor = 'row-resize'
  document.body.style.userSelect = 'none'
  window.addEventListener('pointermove', handleContextPanelResizeMove)
  window.addEventListener('pointerup', stopContextPanelResize)
  window.addEventListener('pointercancel', stopContextPanelResize)
}

const resetContextPanelHeight = () => {
  contextPanelHeight.value = CONTEXT_PANEL_DEFAULT_HEIGHT
  persistContextPanelHeight()
}

const setContextPanelOpen = (open: boolean) => {
  if (open) contextPanelClosing.value = false
  else if (contextPanelOpen.value) contextPanelClosing.value = true
  contextPanelOpen.value = open
  localStorage.setItem(CONTEXT_PANEL_OPEN_KEY, open ? '1' : '0')
}

const finishContextPanelClose = () => {
  contextPanelClosing.value = false
}

const handleContextPanelResizeKeydown = (event: KeyboardEvent) => {
  const step = event.shiftKey ? 24 : 8
  if (event.key === 'Home') {
    contextPanelHeight.value = CONTEXT_PANEL_MIN_HEIGHT
  } else if (event.key === 'End') {
    contextPanelHeight.value = CONTEXT_PANEL_MAX_HEIGHT
  } else if (event.key === 'ArrowUp') {
    contextPanelHeight.value = clampContextPanelHeight(contextPanelHeight.value - step)
  } else if (event.key === 'ArrowDown') {
    contextPanelHeight.value = clampContextPanelHeight(contextPanelHeight.value + step)
  } else {
    return
  }
  event.preventDefault()
  persistContextPanelHeight()
}

const invalidateWorkflowResultRequest = () => {
  workflowResultGeneration += 1
  workflowResultController?.abort()
  workflowResultController = null
  workflowResultInFlight = null
  if (workflowResultRetryTimer !== null) window.clearTimeout(workflowResultRetryTimer)
  workflowResultRetryTimer = null
  workflowResultRetryCount = 0
  isLoadingWorkflowResult.value = false
  workflowResultState.value = 'idle'
  workflowResultError.value = null
}

const scheduleWorkflowResultRetry = (runId: string) => {
  if (workflowResultRetryCount >= 2 || workflowResultRetryTimer !== null) return
  workflowResultRetryCount += 1
  workflowResultRetryTimer = window.setTimeout(() => {
    workflowResultRetryTimer = null
    if (runId === activeWorkflowRunId.value) void loadActiveAcgView(runId)
  }, workflowResultRetryCount * 1500)
}

const loadActiveAcgView = (runId = activeWorkflowRunId.value, force = false): Promise<boolean> => {
  if (!runId || runId !== activeWorkflowRunId.value) return Promise.resolve(false)
  if (workflowResultInFlight?.runId === runId) {
    const inFlight = workflowResultInFlight.promise
    if (!force) return inFlight
    return inFlight.then(() => (
      runId === activeWorkflowRunId.value
        ? loadActiveAcgView(runId, true)
        : false
    ))
  }
  const requestGeneration = ++workflowResultGeneration
  workflowResultController?.abort()
  workflowResultController = new AbortController()
  const signal = workflowResultController.signal
  isLoadingWorkflowResult.value = true
  if (!activeWorkflowRun.value && !activeAcgView.value) workflowResultState.value = 'loading'
  workflowResultError.value = null

  const pending = (async () => {
    const runPromise = agentosApi.getWorkflowRun(runId, { signal })
    const [runResult, viewResult] = await Promise.allSettled([
      runPromise,
      agentosApi.getAcgView(runId, { signal, run: runPromise })
    ])
    if (requestGeneration !== workflowResultGeneration || runId !== activeWorkflowRunId.value) return false

    if (runResult.status === 'fulfilled') {
      activeWorkflowRun.value = runResult.value
      syncWorkflowMessageStatus(runResult.value.runId, runResult.value.status)
    }
    if (viewResult.status === 'fulfilled') activeAcgView.value = viewResult.value

    const cached = workflowResultCache.get(runId) || {}
    workflowResultCache.set(runId, {
      run: activeWorkflowRun.value || cached.run,
      view: activeAcgView.value || cached.view
    })

    const hasRun = Boolean(activeWorkflowRun.value)
    const hasView = Boolean(activeAcgView.value)
    if (hasRun && hasView) {
      workflowResultRetryCount = 0
      workflowResultState.value = 'ready'
      workflowResultError.value = null
      return true
    }

    const rejected = [runResult, viewResult].filter(result => result.status === 'rejected')
    const wasCancelled = rejected.length > 0
      && rejected.every(result => result.status === 'rejected' && axios.isCancel(result.reason))
    workflowResultState.value = hasRun || hasView ? 'partial' : 'error'
    workflowResultError.value = hasRun
      ? '运行详情已恢复，动态拓扑暂时未能加载。'
      : hasView
        ? '动态拓扑已恢复，任务报告暂时未能加载。'
        : '任务报告和动态拓扑均暂时未能加载。'
    if (!wasCancelled) {
      scheduleWorkflowResultRetry(runId)
      if (force) ElMessage.warning('ACG 最终结果暂时未能完整加载')
    }
    return false
  })().finally(() => {
    if (requestGeneration === workflowResultGeneration) {
      workflowResultController = null
      workflowResultInFlight = null
      isLoadingWorkflowResult.value = false
    }
  })
  workflowResultInFlight = { runId, promise: pending }
  return pending
}

const retryWorkflowHistoryDetail = () => {
  if (!activeWorkflowRunId.value) return
  if (workflowResultRetryTimer !== null) window.clearTimeout(workflowResultRetryTimer)
  workflowResultRetryTimer = null
  workflowResultRetryCount = 0
  void loadActiveAcgView(activeWorkflowRunId.value, true)
}

function handleWorkflowProgressChanged(current: WorkflowProgress, previous: WorkflowProgress | null) {
  if (current.runId !== activeWorkflowRunId.value) return
  const conversationId = currentConversationId.value
  chatStore.updateWorkflowBindingStatus(conversationId, current.runId, current.status)
  if (activeWorkflowBinding.value?.runId === current.runId) {
    activeWorkflowBinding.value = { ...activeWorkflowBinding.value, status: current.status }
  }
  syncWorkflowMessageStatus(current.runId, current.status)

  const phaseChanged = previous?.phase !== current.phase
  if (current.phase === 'review' && phaseChanged) {
    void loadActiveAcgView(current.runId)
  } else if (workflowPanelOpen.value && phaseChanged && current.phase === 'executing') {
    void loadActiveAcgView(current.runId)
  }
}

async function handleWorkflowTerminal(progress: WorkflowProgress): Promise<void> {
  if (progress.runId !== activeWorkflowRunId.value || terminalResultLoaded.has(progress.runId)) return
  const loaded = await loadActiveAcgView(progress.runId, true)
  if (loaded) {
    terminalResultLoaded.add(progress.runId)
    window.dispatchEvent(new Event('history-refresh'))
  }
}

const syncWorkflowMessageStatus = (runId: string, status: string) => {
  chatStore.messages.forEach(message => {
    if (message.workflowRunId === runId) message.workflowStatus = status
  })
}

const openActiveWorkflowOperations = () => {
  if (!activeWorkflowRunId.value) return
  void router.push({ path: '/agentos/acg', query: { runId: activeWorkflowRunId.value } })
}

const openActiveWorkflowConsole = () => {
  if (!activeWorkflowRunId.value) return
  void router.push({ path: '/history', query: { tab: 'acg', runId: activeWorkflowRunId.value } })
}

const handleChatWorkflowReviewed = async (run: WorkflowRun) => {
  if (run.runId !== activeWorkflowRunId.value) return
  activeWorkflowRun.value = run
  syncWorkflowMessageStatus(run.runId, run.status)
  chatStore.updateWorkflowBindingStatus(currentConversationId.value, run.runId, run.status)
  await workflowProgressState.refresh()
  await loadActiveAcgView(run.runId)
}

const handleChatReviewConflict = async () => {
  await workflowProgressState.refresh()
  if (activeWorkflowRunId.value) await loadActiveAcgView(activeWorkflowRunId.value)
}

const isAgentMode = computed(() => workspaceMode.value === 'agent')
const agentIcon = computed(() => Cpu)
const heroGreeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 5) return '夜深了，把任务交给 Agent 值守吧'
  if (hour < 9) return '早上好呀，新的一天开始啦'
  if (hour < 12) return '上午好，把想法交给 Agent 去执行'
  if (hour < 14) return '中午好，休息之余也可以派个任务'
  if (hour < 18) return '下午好，继续推进手头的事'
  return '晚上好，适合深度工作的时段'
})
const formatContextTokens = (value: number): string => {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, '')}m`
  if (value >= 1_000) return `${Math.round(value / 1_000)}k`
  return String(value)
}

const contextUsage = computed(() => {
  const used = chatStore.contextUsedTokens
  const windowTokens = chatStore.contextWindowTokens
  if (typeof used !== 'number' || typeof windowTokens !== 'number' || windowTokens <= 0) {
    return { visible: false, percent: 0, level: 'normal', usedLabel: '', windowLabel: '' }
  }
  const ratio = Math.min(1, used / windowTokens)
  const percent = Math.round(ratio * 100)
  const level = ratio >= 0.9 ? 'danger' : ratio >= 0.7 ? 'warning' : 'normal'
  return {
    visible: true,
    percent,
    level,
    usedLabel: formatContextTokens(used),
    windowLabel: formatContextTokens(windowTokens)
  }
})

const latestAssistantMessage = computed(() => [...chatStore.messages]
  .reverse()
  .find(message => message.role === 'assistant'))

const hasAgentActivity = computed(() => {
  const assistant = latestAssistantMessage.value
  return isAgentMode.value && (
    hasActiveWorkflow.value
    || Boolean(assistant?.skillsUsed?.length)
    || Boolean(assistant?.trace?.length)
    || Boolean(assistant?.executionSummary?.length)
  )
})

const showScrollToBottom = computed(() => !isNearBottom.value && chatStore.messages.length > 0)
const isSendDisabled = computed(() => loading.value || (!inputText.value.trim() && !isRecording.value))
const isWorkflowTerminal = computed(() => {
  const phase = workflowProgressState.progress.value?.phase
  const status = workflowProgressState.progress.value?.status || activeWorkflowBinding.value?.status
  const terminal = ['completed', 'failed', 'cancelled']
  return terminal.includes(phase || '') || terminal.includes(status || '')
})
const isWorkflowUnavailable = computed(() =>
  workflowProgressState.syncError.value === '该运行记录不存在或当前账户无权访问'
)
const isWorkflowUpgradeDisabled = computed(() =>
  isSubmittingWorkflow.value
  || (Boolean(activeWorkflowRunId.value) && !isWorkflowTerminal.value && !isWorkflowUnavailable.value)
  || !inputText.value.trim()
)

const resetWorkspace = async () => {
  const previousConversationId = currentConversationId.value
  sessionStorage.removeItem(workflowSubmissionStorageKey(previousConversationId))
  chatStore.clearMessages()
  draftConversationId.value = `draft:${createClientRequestId()}`
  localStorage.setItem(DRAFT_CONVERSATION_KEY, draftConversationId.value)

  conversationGeneration += 1
  workflowProgressState.reset()
  invalidateWorkflowResultRequest()
  activeWorkflowRunId.value = ''
  activeWorkflowBinding.value = null
  activeWorkflowRun.value = null
  activeAcgView.value = null
  workflowStartError.value = null
  pendingMessageCount.value = 0

  const { runId: _runId, contextId: _contextId, ...remainingQuery } = route.query
  await router.replace({
    path: '/chat',
    query: { ...remainingQuery, workspace: workspaceMode.value }
  })
}

const handleNewAgentTask = () => {
  void resetWorkspace()
}

const missionAnchorRef = ref<HTMLElement | null>(null)
const missionMenuOpen = ref(false)
const composerToolsAnchorRef = ref<HTMLElement | null>(null)
const composerToolsOpen = ref(false)
const missionRecordsLoading = ref(false)
const missionRecordsLoaded = ref(false)
const missionRecentRuns = ref<WorkflowRunSummary[]>([])
const missionRecentConversations = ref<Conversation[]>([])

const loadMissionRecords = async () => {
  if (missionRecordsLoaded.value || missionRecordsLoading.value) return
  missionRecordsLoading.value = true
  try {
    if (isAgentMode.value) {
      const page = await workflowApi.listRuns({
        sources: ACG_HISTORY_SOURCES,
        domain: acgHistoryRoleDomain(loadAcgHistoryRole()),
        summary: true,
        page: 1,
        pageSize: 8
      })
      missionRecentRuns.value = page.items || []
    } else {
      const userId = localStorage.getItem('userId') || undefined
      const conversations = await conversationApi.getUserConversations(userId, 'chat')
      missionRecentConversations.value = [...conversations]
        .sort((a, b) => new Date(b.updatedAt || b.createdAt).getTime() - new Date(a.updatedAt || a.createdAt).getTime())
        .slice(0, 8)
    }
    missionRecordsLoaded.value = true
  } catch {
    // 加载失败保持空态提示，不打断输入
  } finally {
    missionRecordsLoading.value = false
  }
}

const toggleMissionMenu = () => {
  missionMenuOpen.value = !missionMenuOpen.value
  if (missionMenuOpen.value) void loadMissionRecords()
}

const toggleComposerTools = () => {
  composerToolsOpen.value = !composerToolsOpen.value
}

const openComposerFileManager = () => {
  composerToolsOpen.value = false
  handleControl('folder')
}

const autoSegment = () => {
  if (inputText.value.length <= 500) return
  const segments = inputText.value.match(/.{1,500}/g) || []
  inputText.value = segments.join('\n\n---\n\n')
  ElMessage.success(t('chat.autoSegment'))
}

const missionRunState = (run: WorkflowRunSummary) => {
  if (run.status === 'completed' || run.phase === 'completed') return '已完成'
  if (run.status === 'failed' || run.phase === 'failed') return '执行失败'
  if (run.status === 'cancelled' || run.phase === 'cancelled') return '已取消'
  if (run.status === 'waiting_review' || run.phase === 'review') return '等待审核'
  return '运行中'
}

const formatMissionTime = (value?: string) => {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}

const openMissionRecord = async (run: WorkflowRunSummary | null, conversation: Conversation | null) => {
  missionMenuOpen.value = false
  if (run) {
    chatStore.clearMessages()
    await router.push({
      path: `/agentos/missions/${encodeURIComponent(run.missionId)}/workspace`,
      query: { runId: run.runId }
    })
    return
  }
  if (conversation) {
    const contextId = conversation.contextId || conversation.id
    await router.push({ path: '/chat', query: { contextId, workspace: 'chat' } })
  }
}

const handleMissionOutsideClick = (event: MouseEvent) => {
  const target = event.target as Node
  if (missionMenuOpen.value && !missionAnchorRef.value?.contains(target)) {
    missionMenuOpen.value = false
  }
  if (composerToolsOpen.value && !composerToolsAnchorRef.value?.contains(target)) {
    composerToolsOpen.value = false
  }
}

const animateComposerToConversation = async (startRect: DOMRect) => {
  await nextTick()
  const composer = composerRef.value
  if (!composer || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

  const endRect = composer.getBoundingClientRect()
  const offsetX = startRect.left - endRect.left
  const offsetY = startRect.top - endRect.top
  if (Math.abs(offsetX) < 1 && Math.abs(offsetY) < 1) return

  const animation = composer.animate(
    [
      { transform: `translate(${offsetX}px, ${offsetY}px)`, opacity: 0.98 },
      { transform: 'translate(0, 0)', opacity: 1 }
    ],
    {
      duration: 480,
      easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
      fill: 'both'
    }
  )

  try {
    await animation.finished
  } catch {
    // The animation may be cancelled when switching routes or roles.
  } finally {
    animation.cancel()
  }
}

const sendAgentWorkspaceMessage = async () => {
  const userText = inputText.value.trim()
  if (!userText) return

  loading.value = true
  const composerStartRect = chatStore.messages.length === 0
    ? composerRef.value?.getBoundingClientRect()
    : undefined

  try {
    inputText.value = userText
    await upgradeChatToWorkflow()
    if (composerStartRect) await animateComposerToConversation(composerStartRect)
    scrollToBottom()
  } catch (error: any) {
    inputText.value = userText
    if (!wasErrorUserNotified(error)) ElMessage.error(error?.message || 'Send failed')
  } finally {
    loading.value = false
  }
}

const sendMessage = async () => {
  if (loading.value) return
  if (!inputText.value.trim() && !isRecording.value) return

  if (isAgentMode.value) {
    await sendAgentWorkspaceMessage()
    return
  }

  loading.value = true
  const userText = inputText.value.trim()
  inputText.value = ''
  const composerStartRect = chatStore.messages.length === 0
    ? composerRef.value?.getBoundingClientRect()
    : undefined

  try {
    const sendPromise = chatStore.sendMessageStream(userText, 'default', loadModelSettings(), workspaceMode.value)
    if (composerStartRect) {
      await animateComposerToConversation(composerStartRect)
    }
    await sendPromise
    scrollToBottom()
  } catch (err: any) {
    if (!wasErrorUserNotified(err)) ElMessage.error(err.message || '发送消息失败')
    inputText.value = userText
  } finally {
    loading.value = false
  }
}

interface PendingWorkflowSubmission {
  conversationId: string
  text: string
  clientRequestId: string
}

const workflowSubmissionStorageKey = (conversationId: string) =>
  `${WORKFLOW_SUBMISSION_KEY_PREFIX}${conversationId}`

const getWorkflowClientRequestId = (conversationId: string, text: string) => {
  try {
    const raw = sessionStorage.getItem(workflowSubmissionStorageKey(conversationId))
    const pending = raw ? JSON.parse(raw) as PendingWorkflowSubmission : null
    if (pending?.conversationId === conversationId && pending.text === text && pending.clientRequestId) {
      return pending.clientRequestId
    }
  } catch {
    // A malformed pending submission is replaced by a new explicit operation.
  }
  const clientRequestId = createClientRequestId()
  sessionStorage.setItem(workflowSubmissionStorageKey(conversationId), JSON.stringify({
    conversationId,
    text,
    clientRequestId
  } satisfies PendingWorkflowSubmission))
  return clientRequestId
}

const activateWorkflowRun = async (
  runId: string,
  binding: ChatWorkflowBinding | null,
  fresh: boolean
) => {
  conversationGeneration += 1
  workflowProgressState.reset()
  invalidateWorkflowResultRequest()
  activeWorkflowRunId.value = runId
  activeWorkflowBinding.value = binding
  activeWorkflowRun.value = null
  activeAcgView.value = null
  workflowStartError.value = null
  void workflowProgressState.start(runId, { fresh })
  await router.replace({ query: { ...route.query, runId } })
}

const workflowStartErrorMessage = (error: unknown) => {
  if (axios.isAxiosError(error)) {
    if (error.response?.status === 409) return '本次请求标识与原任务参数冲突，请重新发起'
    if (error.response?.status === 503 || !error.response) return 'ACG 任务暂时不可用，请稍后重试'
  }
  if (error instanceof Error && error.name === 'WorkflowApiContractError') {
    return 'ACG 启动响应契约无效'
  }
  return 'ACG 任务未能启动'
}

const upgradeChatToWorkflow = async () => {
  if (isSubmittingWorkflow.value || (activeWorkflowRunId.value && !isWorkflowTerminal.value)) return
  const userText = inputText.value.trim()
  if (!userText) {
    ElMessage.warning('请输入要升级为 Workflow 的内容')
    return
  }

  const conversationId = currentConversationId.value
  const clientRequestId = getWorkflowClientRequestId(conversationId, userText)
  isSubmittingWorkflow.value = true
  workflowStartError.value = null
  inputText.value = ''
  try {
    const startWorkflow = isAgentMode.value ? chatStore.startAgentRun : chatStore.upgradeToWorkflow
    const result = await startWorkflow(userText, {
      domain: 'general',
      intent: 'general',
      reviewMode: 'auto',
      conversationId,
      clientRequestId
    })
    if (result) {
      sessionStorage.removeItem(workflowSubmissionStorageKey(conversationId))
      await activateWorkflowRun(result.binding.runId, result.binding, true)
      ElMessage.success(`已创建 WorkflowRun：${result.binding.runId}`)
    }
    scrollToBottom()
  } catch (error: unknown) {
    inputText.value = userText
    workflowStartError.value = workflowStartErrorMessage(error)
    if (axios.isAxiosError(error) && error.response?.status === 409) {
      sessionStorage.removeItem(workflowSubmissionStorageKey(conversationId))
    }
  } finally {
    isSubmittingWorkflow.value = false
  }
}

const startVoiceInput = () => {
  isRecording.value = true
}

const stopVoiceInput = () => {
  isRecording.value = false
}

const handleKeydown = (event: KeyboardEvent) => {
  if (event.isComposing || event.keyCode === 229) return
  if (event.key !== 'Enter') return

  if (event.ctrlKey || event.shiftKey) {
    event.preventDefault()
    const textarea = event.target as HTMLTextAreaElement
    const cursorPosition = textarea.selectionStart
    const textBefore = inputText.value.substring(0, cursorPosition)
    const textAfter = inputText.value.substring(cursorPosition)
    inputText.value = `${textBefore}\n${textAfter}`

    nextTick(() => {
      textarea.selectionStart = cursorPosition + 1
      textarea.selectionEnd = cursorPosition + 1
    })
    return
  }

  event.preventDefault()
  sendMessage()
}

const handleControl = (type: string) => {
  if (type === 'folder' || type === 'image') {
    showFileManager.value = true
  }
}

const handleFileSelected = async (file: any) => {
  const fileUrl = file?.path ? `/api/files/download/${file.path}` : (file?.url || file?.fileUrl)
  if (!fileUrl) {
    ElMessage.warning('文件地址无效，无法发送')
    return
  }

  showFileManager.value = false
  loading.value = true
  const composerStartRect = chatStore.messages.length === 0
    ? composerRef.value?.getBoundingClientRect()
    : undefined

  try {
    const sendPromise = chatStore.sendMessage('', fileUrl, loadModelSettings())
    if (composerStartRect) {
      await animateComposerToConversation(composerStartRect)
    }
    await sendPromise
    scrollToBottom()
    ElMessage.success(`已发送文件: ${file.name}`)
  } catch (error: any) {
    ElMessage.error(error.message || '发送文件失败')
  } finally {
    loading.value = false
  }
}

let pendingScrollFrame: number | null = null

interface ConversationRailItem {
  id: Message['id']
  round: number
  preview: string
}

const CONVERSATION_RAIL_MIN_ROUNDS = 3
const CONVERSATION_RAIL_OVERFLOW_GAP = 120

const conversationRailItems = computed<ConversationRailItem[]>(() => {
  const items: ConversationRailItem[] = []
  chatStore.messages.forEach(message => {
    if (message.role !== 'user') return
    const text = (message.content || '').replace(/\s+/g, ' ').trim()
    const preview = text || (message.fileUrl ? '[文件附件]' : '（空消息）')
    items.push({
      id: message.id,
      round: items.length + 1,
      preview: preview.slice(0, 200)
    })
  })
  return items
})

const conversationRailOverflow = ref(false)
const conversationRailVisible = computed(() =>
  !isAgentMode.value
  && conversationRailItems.value.length >= CONVERSATION_RAIL_MIN_ROUNDS
  && conversationRailOverflow.value
)
const conversationRailRef = ref<HTMLElement | null>(null)
const activeRailTickId = ref<Message['id'] | ''>('')
const railHoverItem = ref<ConversationRailItem | null>(null)
const railPreviewTop = ref(0)
const railFlashId = ref<Message['id'] | ''>('')
let railFlashTimer: number | null = null
let railScrollFallback: number | null = null

// 隐藏页/禁用平滑滚动的环境里 scrollTo smooth 会原地不动：140ms 无位移则瞬时到位兜底
const animateRailScrollTo = (container: HTMLElement, target: number) => {
  if (railScrollFallback !== null) window.clearTimeout(railScrollFallback)
  const start = container.scrollTop
  if (Math.abs(target - start) < 2) return
  container.scrollTo({ top: target, behavior: 'smooth' })
  railScrollFallback = window.setTimeout(() => {
    railScrollFallback = null
    if (Math.abs(container.scrollTop - target) > 4 && Math.abs(container.scrollTop - start) < 2) {
      container.scrollTo({ top: target, behavior: 'auto' })
    }
  }, 140)
}

const updateRailOverflow = () => {
  const el = messagesRef.value
  if (!el) {
    conversationRailOverflow.value = false
    return
  }
  conversationRailOverflow.value = el.scrollHeight > el.clientHeight + CONVERSATION_RAIL_OVERFLOW_GAP
}

const updateRailActiveTick = () => {
  const container = messagesRef.value
  if (!conversationRailVisible.value || !container) {
    activeRailTickId.value = ''
    return
  }
  const box = container.getBoundingClientRect()
  const probe = box.top + box.height * 0.35
  let current: Message['id'] | '' = ''
  container.querySelectorAll<HTMLElement>('[data-role="user"][data-message-id]').forEach(row => {
    if (row.getBoundingClientRect().top <= probe) current = (row.dataset.messageId as Message['id']) || ''
  })
  activeRailTickId.value = current
}

const jumpToRailInteraction = (id: Message['id']) => {
  const container = messagesRef.value
  if (!container) return
  let target: HTMLElement | null = null
  container.querySelectorAll<HTMLElement>('[data-role="user"][data-message-id]').forEach(row => {
    if (row.dataset.messageId === String(id)) target = row
  })
  if (!target) return

  const box = container.getBoundingClientRect()
  const top = container.scrollTop + target.getBoundingClientRect().top - box.top - 18
  animateRailScrollTo(container, Math.max(0, top))
  activeRailTickId.value = id
  railFlashId.value = id
  if (railFlashTimer !== null) window.clearTimeout(railFlashTimer)
  railFlashTimer = window.setTimeout(() => {
    railFlashId.value = ''
    railFlashTimer = null
  }, 1600)
}

const handleRailHover = (item: ConversationRailItem, event: PointerEvent) => {
  railHoverItem.value = item
  const railEl = conversationRailRef.value
  const tick = event.currentTarget as HTMLElement | null
  if (!railEl || !tick) return
  const railRect = railEl.getBoundingClientRect()
  const tickRect = tick.getBoundingClientRect()
  const center = tickRect.top - railRect.top + tickRect.height / 2
  railPreviewTop.value = Math.min(Math.max(center, 48), Math.max(railRect.height - 48, 48))
}

const handleRailLeave = () => {
  railHoverItem.value = null
}

watch(
  () => chatStore.messages.length,
  () => {
    void nextTick(() => {
      updateRailOverflow()
      updateRailActiveTick()
    })
  }
)

const scrollToBottom = (behavior: ScrollBehavior = 'auto') => {
  if (!messagesRef.value) return

  if (pendingScrollFrame !== null) {
    window.cancelAnimationFrame(pendingScrollFrame)
  }

  pendingScrollFrame = window.requestAnimationFrame(() => {
    pendingScrollFrame = null
    void nextTick(() => {
      const messagesElement = messagesRef.value
      if (!messagesElement) return

      messagesElement.scrollTo({
        top: messagesElement.scrollHeight,
        behavior
      })
    })
  })
}

const handleScrollToBottom = () => {
  pendingMessageCount.value = 0
  scrollToBottom('smooth')
}

watch(
  () => route.query.workspace,
  workspace => {
    if (workspace !== 'agent' && workspace !== 'chat') return
    workspaceMode.value = workspace
    localStorage.setItem(WORKSPACE_MODE_KEY, workspace)
  },
  { immediate: true }
)

const handleWorkspaceModeChange = (event: Event) => {
  const mode = (event as CustomEvent<{ mode?: WorkspaceMode }>).detail?.mode
  if (mode !== 'agent' && mode !== 'chat') return
  workspaceModeSwitching.value = true
  workspaceMode.value = mode
  if (mode === 'agent') {
    agentPanelCollapsed.value = showHeroMode.value
    setContextPanelOpen(!showHeroMode.value)
    setWorkflowPanelOpen(!showHeroMode.value)
  } else {
    contextPanelOpen.value = false
    contextPanelClosing.value = false
    workflowPanelOpen.value = false
    localStorage.setItem(CONTEXT_PANEL_OPEN_KEY, '0')
    localStorage.setItem(WORKFLOW_PANEL_OPEN_KEY, '0')
  }
  void nextTick(() => {
    workspaceModeSwitching.value = false
  })
}

watch(
  () => chatStore.messages.length,
  (newLen, oldLen) => {
    if (newLen === 0) {
      setContextPanelOpen(false)
      setWorkflowPanelOpen(false)
      agentPanelCollapsed.value = true
      return
    }
    if (newLen <= oldLen) return
    const latest = chatStore.messages[newLen - 1]
    const isUserMessage = latest?.role === 'user'

    if (isNearBottom.value || isUserMessage) {
      scrollToBottom()
      return
    }

    pendingMessageCount.value = Math.min(99, pendingMessageCount.value + 1)
  }
)

watch(
  () => chatStore.messages[chatStore.messages.length - 1]?.content,
  () => {
    if (isNearBottom.value) scrollToBottom()
  },
  { flush: 'post' }
)

const checkScrollState = () => {
  if (!messagesRef.value) return
  const { scrollTop, scrollHeight, clientHeight } = messagesRef.value
  const isAtBottom = Math.abs(scrollHeight - clientHeight - scrollTop) < 24
  isNearBottom.value = isAtBottom
  if (isAtBottom) pendingMessageCount.value = 0
  updateRailOverflow()
  updateRailActiveTick()
}

const bindMessagesScroll = () => {
  if (!messagesRef.value) return
  messagesRef.value.removeEventListener('scroll', checkScrollState)
  messagesRef.value.addEventListener('scroll', checkScrollState)
  checkScrollState()
}

watch(
  () => route.query.contextId,
  async contextId => {
    const targetContextId = typeof contextId === 'string' ? contextId.trim() : ''
    if (!targetContextId) return
    if (chatStore.contextId === targetContextId) return

    await chatStore.loadHistory(targetContextId)
    scrollToBottom()
  },
  { immediate: true }
)

const restoreWorkflowForConversation = async () => {
  const conversationId = currentConversationId.value
  const binding = chatStore.getActiveWorkflowBinding(conversationId)
    || chatStore.getLatestWorkflowBinding(conversationId)
  const routeRunId = typeof route.query.runId === 'string' ? route.query.runId.trim() : ''
  const runId = routeRunId || binding?.runId || ''

  if (runId && runId === activeWorkflowRunId.value && workflowProgressState.runId.value === runId) return

  const restoreGeneration = ++conversationGeneration
  workflowProgressState.reset()
  invalidateWorkflowResultRequest()
  activeWorkflowRunId.value = ''
  activeWorkflowBinding.value = null
  activeWorkflowRun.value = null
  activeAcgView.value = null
  workflowStartError.value = null
  if (!runId) return

  activeWorkflowRunId.value = runId
  activeWorkflowBinding.value = binding?.runId === runId ? binding : null
  const cachedResult = workflowResultCache.get(runId)
  if (cachedResult) {
    activeWorkflowRun.value = cachedResult.run || null
    activeAcgView.value = cachedResult.view || null
    workflowResultState.value = cachedResult.run && cachedResult.view ? 'ready' : 'partial'
  }
  await workflowProgressState.start(runId, { fresh: false })
  if (restoreGeneration !== conversationGeneration || runId !== activeWorkflowRunId.value) return
  if ((!activeWorkflowRun.value || !activeAcgView.value) && !isLoadingWorkflowResult.value) {
    await loadActiveAcgView(runId)
  }
  if (!routeRunId && binding) {
    await router.replace({ query: { ...route.query, runId } })
  }
}

watch(
  [currentConversationId, () => route.query.runId],
  () => { void restoreWorkflowForConversation() },
  { immediate: true }
)

watch(
  () => chatStore.contextId,
  contextId => {
    if (contextId) setConversationWorkspace(contextId, workspaceMode.value)
  }
)

watch(
  () => workflowProgressState.syncError.value,
  error => {
    if (error !== '该运行记录不存在或当前账户无权访问') return
    const binding = activeWorkflowBinding.value
    if (!binding) return
    chatStore.markWorkflowBindingInvalid(binding.conversationId, binding.runId)
    activeWorkflowBinding.value = { ...binding, invalidAt: new Date().toISOString() }
  }
)

watch(hasAgentActivity, active => {
  if (active) agentPanelCollapsed.value = false
})

watch(
  [isAgentMode, activeWorkflowRunId],
  async ([generalMode], previous) => {
    if (!generalMode) return
    const previousRunId = previous?.[1]
    if (previousRunId === activeWorkflowRunId.value && previous?.[0] === generalMode) return
    await nextTick()
    agentPanelContentRef.value?.scrollTo({ top: 0 })
  }
)

onMounted(async () => {
  heroLogoMotion.reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  window.addEventListener('workspace-mode-change', handleWorkspaceModeChange)
  window.addEventListener('agent-new-task', handleNewAgentTask)
  window.addEventListener('resize', handleWorkflowPanelViewportResize)
  window.addEventListener('pointerdown', handleMissionOutsideClick)
  if (showHeroMode.value) {
    setContextPanelOpen(false)
    setWorkflowPanelOpen(false)
    agentPanelCollapsed.value = true
  }
  workflowPanelHeight.value = clampWorkflowPanelHeight(workflowPanelHeight.value)

  if (composerRef.value) {
    composerResizeObserver = new ResizeObserver(entries => {
      const height = entries[0]?.borderBoxSize?.[0]?.blockSize || entries[0]?.contentRect.height
      if (height) composerHeight.value = Math.ceil(height)
    })
    composerResizeObserver.observe(composerRef.value)
  }

  if (localStorage.getItem(AGENT_PANEL_COLLAPSED_KEY) === null && isAgentMode.value && !hasAgentActivity.value) {
    agentPanelCollapsed.value = true
  }


  void chatStore.fetchContextWindows()

  bindMessagesScroll()
})

onUnmounted(() => {
  window.removeEventListener('workspace-mode-change', handleWorkspaceModeChange)
  window.removeEventListener('agent-new-task', handleNewAgentTask)
  window.removeEventListener('resize', handleWorkflowPanelViewportResize)
  window.removeEventListener('pointerdown', handleMissionOutsideClick)
  if (railFlashTimer !== null) {
    window.clearTimeout(railFlashTimer)
    railFlashTimer = null
  }
  if (railScrollFallback !== null) {
    window.clearTimeout(railScrollFallback)
    railScrollFallback = null
  }
  composerResizeObserver?.disconnect()
  stopAgentPanelResize()
  stopWorkflowPanelResize()
  stopContextPanelResize()
  if (heroLogoMotion.frame !== null) window.cancelAnimationFrame(heroLogoMotion.frame)
  heroLogoMotion.frame = null
  if (pendingScrollFrame !== null) window.cancelAnimationFrame(pendingScrollFrame)
  pendingScrollFrame = null
  workflowProgressState.reset()
  invalidateWorkflowResultRequest()
  if (messagesRef.value) {
    messagesRef.value.removeEventListener('scroll', checkScrollState)
  }
})

type HeroLogoMotionState = {
  x: number
  y: number
  intensity: number
  targetX: number
  targetY: number
  targetIntensity: number
  pointerActive: boolean
  pressed: boolean
  frame: number | null
  reducedMotion: boolean
}

const heroLogoMotion: HeroLogoMotionState = {
  x: 0,
  y: 0,
  intensity: 0,
  targetX: 0,
  targetY: 0,
  targetIntensity: 0,
  pointerActive: false,
  pressed: false,
  frame: null,
  reducedMotion: false
}

const clampHeroLogo = (value: number) => Math.max(-1, Math.min(1, value))

const scheduleHeroLogoMotion = () => {
  if (heroLogoMotion.reducedMotion || heroLogoMotion.frame !== null || typeof window.requestAnimationFrame !== 'function') return
  heroLogoMotion.frame = window.requestAnimationFrame(animateHeroLogoMotion)
}

const animateHeroLogoMotion = (timestamp: number) => {
  heroLogoMotion.frame = null
  const field = heroLogoFieldRef.value
  const logo = field?.querySelector<HTMLImageElement>('.hero-watermark')
  const turbulence = heroLogoTurbulenceRef.value
  const displacement = heroLogoDisplacementRef.value

  if (!field || !logo || !turbulence || !displacement || heroLogoMotion.reducedMotion) return

  const smoothing = heroLogoMotion.intensity > 0.02 ? 0.14 : 0.1
  heroLogoMotion.x += (heroLogoMotion.targetX - heroLogoMotion.x) * smoothing
  heroLogoMotion.y += (heroLogoMotion.targetY - heroLogoMotion.y) * smoothing
  heroLogoMotion.intensity += (heroLogoMotion.targetIntensity - heroLogoMotion.intensity) * smoothing

  const wave = Math.sin(timestamp / 780) * heroLogoMotion.intensity
  const intensity = heroLogoMotion.intensity
  const rotation = heroLogoMotion.x * 2.4 - heroLogoMotion.y * 1.1
  const skewX = heroLogoMotion.x * intensity * 2.2
  const skewY = heroLogoMotion.y * intensity * -1.4
  const scale = 1 + intensity * 0.035
  const displacementScale = 5 + intensity * 24 + wave * 2
  const frequencyX = 0.009 + intensity * 0.006 + wave * 0.0007
  const frequencyY = 0.014 + intensity * 0.007 - wave * 0.0007

  logo.style.transform = `translate3d(${(heroLogoMotion.x * intensity * 4).toFixed(2)}px, ${(heroLogoMotion.y * intensity * 3).toFixed(2)}px, 0) rotate(${rotation.toFixed(2)}deg) skew(${skewX.toFixed(2)}deg, ${skewY.toFixed(2)}deg) scale(${scale.toFixed(4)})`
  displacement.setAttribute('scale', displacementScale.toFixed(2))
  turbulence.setAttribute('baseFrequency', `${frequencyX.toFixed(4)} ${frequencyY.toFixed(4)}`)
  field.style.setProperty('--hero-logo-aura-opacity', (0.12 + intensity * 0.2).toFixed(3))
  field.style.setProperty('--hero-logo-aura-scale', (1 + intensity * 0.12).toFixed(3))

  const settled = Math.abs(heroLogoMotion.targetIntensity - intensity) < 0.006
    && Math.abs(heroLogoMotion.targetX - heroLogoMotion.x) < 0.006
    && Math.abs(heroLogoMotion.targetY - heroLogoMotion.y) < 0.006

  if (heroLogoMotion.pointerActive || heroLogoMotion.pressed || !settled) scheduleHeroLogoMotion()
}

const updateHeroLogoPointer = (event: PointerEvent) => {
  const field = heroLogoFieldRef.value
  if (!field || heroLogoMotion.reducedMotion) return

  const rect = field.getBoundingClientRect()
  const x = clampHeroLogo(((event.clientX - rect.left) / rect.width) * 2 - 1)
  const y = clampHeroLogo(((event.clientY - rect.top) / rect.height) * 2 - 1)
  const distance = Math.min(1, Math.hypot(x, y) * 0.72 + 0.08)

  heroLogoMotion.targetX = x
  heroLogoMotion.targetY = y
  heroLogoMotion.targetIntensity = Math.max(distance, heroLogoMotion.pressed ? 0.72 : 0)
  scheduleHeroLogoMotion()
}

const handleHeroLogoPointerMove = (event: PointerEvent) => {
  heroLogoMotion.pointerActive = true
  updateHeroLogoPointer(event)
}

const handleHeroLogoPointerLeave = () => {
  heroLogoMotion.pointerActive = false
  heroLogoMotion.pressed = false
  heroLogoPressed.value = false
  heroLogoMotion.targetX = 0
  heroLogoMotion.targetY = 0
  heroLogoMotion.targetIntensity = 0
  scheduleHeroLogoMotion()
}

const handleHeroLogoPointerDown = (event: PointerEvent) => {
  heroLogoMotion.pointerActive = true
  heroLogoMotion.pressed = true
  heroLogoPressed.value = true
  updateHeroLogoPointer(event)
  const field = event.currentTarget
  if (field instanceof HTMLElement && field.setPointerCapture) field.setPointerCapture(event.pointerId)
}

const handleHeroLogoPointerUp = () => {
  heroLogoMotion.pressed = false
  heroLogoPressed.value = false
  heroLogoMotion.targetIntensity = heroLogoMotion.pointerActive
    ? Math.min(heroLogoMotion.targetIntensity, 0.18)
    : 0
  scheduleHeroLogoMotion()
}
</script>

<style scoped>
.chat-view {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: transparent;
}


.chat-main {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 1fr;
  gap: 0;
  padding: 0;
  transition: grid-template-columns 0.24s var(--ease-out);
}

.chat-main.has-agent-results {
  grid-template-columns: minmax(0, 1fr) var(--agent-panel-width, 340px);
  gap: 0;
  padding: 0;
}

.chat-main.has-agent-results.agent-panel-collapsed {
  grid-template-columns: minmax(0, 1fr) 52px;
}

.chat-main.agent-panel-resizing {
  transition: none;
}


.chat-panel {
  min-height: 0;
  display: flex;
  flex-direction: column;
  position: relative;
  overflow: hidden;
  border: 0;
  border-radius: 0;
  background: var(--bg-app);
}

.context-panel {
  position: relative;
  z-index: 6;
  flex: 0 0 auto;
  min-height: 170px;
  overflow: hidden;
  background: color-mix(in srgb, var(--bg-card) 91%, var(--primary-fade));
  box-shadow: 0 12px 30px rgba(26, 31, 58, 0.035);
  transition: height 0.22s var(--ease-out);
}

.context-panel.resizing { transition: none; }

.context-panel__header {
  height: 42px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 0 16px;
  border-bottom: 1px solid color-mix(in srgb, var(--border-light) 72%, transparent);
}

.context-panel__identity,
.context-panel__metrics,
.context-panel__tabs,
.context-panel-dock {
  display: flex;
  align-items: center;
}

.context-panel__identity { min-width: 0; gap: 8px; }
.context-panel__identity .el-icon { color: var(--primary-color); }
.context-panel__identity strong { flex: 0 0 auto; font-size: 12px; color: var(--text-primary); }
.context-panel__identity span {
  overflow: hidden;
  color: var(--text-muted);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.context-panel__metrics { flex: 0 0 auto; gap: 6px; }
.context-panel__metrics > span {
  padding: 3px 7px;
  border-radius: 999px;
  background: var(--primary-fade);
  color: var(--text-secondary);
  font-size: 9px;
  font-weight: 650;
}

.context-panel__metrics button {
  width: 26px;
  height: 26px;
  display: inline-grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}
.context-panel__metrics button:hover { background: var(--primary-fade); color: var(--primary-color); }

.context-panel__tabs {
  height: 34px;
  gap: 4px;
  padding: 4px 12px 0;
}

.context-panel__tabs button {
  height: 30px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 11px;
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  font-size: 10px;
  cursor: pointer;
}
.context-panel__tabs button.active { border-bottom-color: var(--primary-color); color: var(--primary-color); }
.context-panel__tabs button span {
  min-width: 16px;
  height: 16px;
  display: inline-grid;
  place-items: center;
  border-radius: 999px;
  background: var(--primary-fade);
  font-size: 8px;
  font-weight: 700;
}

.context-panel__body {
  height: calc(100% - 76px);
  padding: 10px 14px 14px;
  overflow: auto;
}

.context-panel__empty {
  height: 100%;
  display: grid;
  place-items: center;
  color: var(--text-disabled);
  font-size: 11px;
}

.context-lineage {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 7px;
}
.context-lineage__row {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto minmax(0, 1fr);
  align-items: center;
  gap: 7px;
  padding: 7px 9px;
  border: 1px solid color-mix(in srgb, var(--border-light) 76%, transparent);
  border-radius: 9px;
  background: color-mix(in srgb, var(--bg-card) 68%, transparent);
}
.context-node-pill {
  overflow: hidden;
  color: var(--text-primary);
  font-size: 10px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.context-node-pill.target { color: var(--primary-color); }
.context-edge-label { color: var(--text-muted); font-size: 8px; }
.context-lineage__arrow { color: var(--primary-color); font-size: 12px; }

.context-node-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(158px, 1fr));
  gap: 8px;
}
.context-node-card {
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid color-mix(in srgb, var(--border-light) 78%, transparent);
  border-radius: 10px;
  background: color-mix(in srgb, var(--bg-card) 70%, transparent);
}
.context-node-card__type {
  display: block;
  margin-bottom: 5px;
  color: var(--primary-color);
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.08em;
}
.context-node-card strong,
.context-node-card small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.context-node-card strong { color: var(--text-primary); font-size: 10px; }
.context-node-card small { margin-top: 4px; color: var(--text-muted); font-size: 8px; }

.context-step-list { display: flex; flex-direction: column; gap: 6px; }
.context-step-item {
  display: grid;
  grid-template-columns: 26px minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
  padding: 7px 9px;
  border-radius: 9px;
  background: color-mix(in srgb, var(--bg-card) 66%, transparent);
}
.context-step-item__index { color: var(--text-disabled); font-size: 9px; font-variant-numeric: tabular-nums; }
.context-step-item strong,
.context-step-item small { display: block; }
.context-step-item strong { color: var(--text-primary); font-size: 10px; }
.context-step-item small { margin-top: 2px; color: var(--text-muted); font-size: 8px; }
.context-step-item__status { color: var(--text-muted); font-size: 9px; }
.context-step-item__status.done { color: var(--success); }

.context-panel__resizer {
  position: absolute;
  z-index: 10;
  right: 0;
  bottom: -5px;
  left: 0;
  height: 11px;
  cursor: row-resize;
  touch-action: none;
  outline: none;
}
.context-panel__resizer::before {
  content: '';
  position: absolute;
  right: 0;
  bottom: 5px;
  left: 0;
  height: 1px;
  background: transparent;
}
.context-panel__resizer > span {
  position: absolute;
  bottom: 3px;
  left: 50%;
  width: 34px;
  height: 4px;
  border-radius: 999px;
  background: var(--border-light);
  opacity: 0;
  transform: translateX(-50%);
}
.context-panel__resizer:hover::before,
.context-panel__resizer:focus-visible::before,
.context-panel.resizing .context-panel__resizer::before { background: var(--primary-color); }
.context-panel__resizer:hover > span,
.context-panel__resizer:focus-visible > span,
.context-panel.resizing .context-panel__resizer > span { opacity: 1; background: var(--primary-color); }

.context-panel-dock {
  flex: 0 0 30px;
  width: 100%;
  height: 30px;
  justify-content: center;
  gap: 7px;
  padding: 0 14px;
  border: 0;
  background: color-mix(in srgb, var(--bg-card) 94%, var(--primary-fade));
  color: var(--text-muted);
  font: inherit;
  font-size: 9px;
  cursor: pointer;
}
.context-panel-dock strong { color: var(--text-secondary); font-size: 10px; }
.context-panel-dock:hover { background: color-mix(in srgb, var(--bg-card) 88%, var(--primary-fade)); color: var(--primary-color); }
.context-panel-dock__pulse {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--primary-color);
  box-shadow: 0 0 0 4px var(--primary-fade);
  animation: acg-dock-pulse 1.8s ease-in-out infinite;
}

.context-panel-slide-enter-active,
.context-panel-slide-leave-active { transition: opacity 0.2s ease, transform 0.24s var(--ease-out); }
.context-panel-slide-enter-from,
.context-panel-slide-leave-to { opacity: 0; transform: translateY(-18px); }

.workflow-acg-panel {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 34%);
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 6;
  min-height: 180px;
  overflow: hidden;
  background: color-mix(in srgb, var(--bg-card) 94%, var(--primary-fade));
  box-shadow: 0 -12px 30px rgba(26, 31, 58, 0.035);
  transition: height 0.2s var(--ease-out);
}

.workflow-acg-panel > :deep(.chat-runtime-timeline) {
  height: 100%;
  overflow: auto;
  border-top: 0;
  border-right: 0;
  border-bottom: 0;
  border-radius: 0;
  background: color-mix(in srgb, var(--bg-card) 96%, var(--primary-fade));
}

.workflow-acg-panel.resizing {
  transition: none;
}

.workflow-panel-resizer {
  grid-column: 1 / -1;
  position: absolute;
  z-index: 10;
  top: -5px;
  right: 0;
  left: 0;
  height: 11px;
  cursor: row-resize;
  touch-action: none;
  outline: none;
}

.workflow-panel-resizer::before {
  content: '';
  position: absolute;
  top: 5px;
  right: 0;
  left: 0;
  height: 1px;
  background: transparent;
  transition: background-color 0.16s ease, box-shadow 0.16s ease;
}

.workflow-panel-resizer > span {
  position: absolute;
  top: 3px;
  left: 50%;
  width: 34px;
  height: 4px;
  border-radius: 999px;
  background: var(--border-light);
  opacity: 0;
  transform: translateX(-50%);
  transition: opacity 0.16s ease, background-color 0.16s ease;
}

.workflow-panel-resizer:hover::before,
.workflow-panel-resizer:focus-visible::before,
.workflow-acg-panel.resizing .workflow-panel-resizer::before {
  background: var(--primary-color);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--primary-color) 16%, transparent);
}

.workflow-panel-resizer:hover > span,
.workflow-panel-resizer:focus-visible > span,
.workflow-acg-panel.resizing .workflow-panel-resizer > span {
  opacity: 1;
  background: var(--primary-color);
}

.workflow-acg-panel :deep(.acg-topology) {
  height: 100%;
  padding: 10px 12px 8px;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.workflow-acg-panel :deep(.panel-head) {
  flex: 0 0 auto;
  min-height: 28px;
  margin-bottom: 4px;
}

.workflow-acg-panel :deep(.graph-stage) {
  flex: 1 1 auto;
  min-height: 0;
}

.workflow-acg-panel :deep(.graph-canvas) {
  flex: 1 1 auto;
  height: auto;
  min-height: 0;
}

.workflow-acg-panel :deep(.node-detail) {
  height: auto;
  min-height: 0;
}

.workflow-acg-panel :deep(.legend) {
  flex: 0 0 auto;
  margin-top: 4px;
  padding-top: 6px;
}

.workflow-acg-loading {
  grid-column: 1 / -1;
  position: absolute;
  inset: 42px 0 0;
  display: grid;
  place-items: center;
  color: var(--text-disabled);
  font-size: 12px;
  pointer-events: none;
}

@media (max-width: 900px) {
  .workflow-acg-panel {
    grid-template-columns: minmax(0, 1fr) minmax(220px, 38%);
  }
}

.workflow-acg-dock {
  flex: 0 0 30px;
  width: 100%;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 0 14px;
  border: 0;
  background: color-mix(in srgb, var(--bg-card) 94%, var(--primary-fade));
  color: var(--text-secondary);
  font: inherit;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.16s ease, background-color 0.16s ease;
}

.workflow-acg-dock:hover,
.workflow-acg-dock:focus-visible {
  background: var(--primary-fade);
  color: var(--primary-color);
  outline: none;
}

.workflow-acg-dock__pulse {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--primary-color);
  box-shadow: 0 0 0 4px var(--primary-fade);
  animation: acg-dock-pulse 2s ease-in-out infinite;
}

.workflow-acg-dock.idle .workflow-acg-dock__pulse {
  background: var(--text-disabled);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--text-disabled) 12%, transparent);
  animation: none;
}

.workflow-acg-dock__meta {
  color: var(--text-disabled);
  font-weight: 500;
}

.workflow-acg-dock .el-icon {
  margin-left: 2px;
}

@keyframes acg-dock-pulse {
  50% { opacity: 0.55; transform: scale(0.86); }
}

.workflow-acg-slide-enter-active,
.workflow-acg-slide-leave-active {
  transition: opacity 0.2s ease, transform 0.24s var(--ease-out);
}

.workflow-acg-slide-enter-from,
.workflow-acg-slide-leave-to {
  opacity: 0;
  transform: translateY(18px);
}

.chat-panel.hero-mode {
  --hero-composer-center-y: 57%;
  --hero-slogan-offset-y: 236px;
}

.chat-panel.hero-mode .messages {
  overflow: hidden;
  padding-bottom: 0;
}

.chat-panel.hero-mode .empty-state {
  position: absolute;
  top: calc(var(--hero-composer-center-y) - var(--hero-slogan-offset-y));
  left: 50%;
  z-index: 3;
  width: min(calc(100% - 48px), 640px);
  margin: 0;
  transform: translate(-50%, -50%);
  pointer-events: none;
  animation: hero-fade-in 0.28s var(--ease-out);
}

.chat-panel.hero-mode .composer {
  position: absolute;
  top: var(--hero-composer-center-y);
  right: 0;
  left: 0;
  z-index: 4;
  transform: translateY(-50%);
}

@keyframes hero-fade-in {
  from { opacity: 0; transform: translate(-50%, calc(-50% + 8px)); }
  to { opacity: 1; transform: translate(-50%, -50%); }
}

.chat-panel:not(.hero-mode) .composer {
  position: absolute;
  right: 0;
  left: 0;
  z-index: 5;
}

.messages {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 22px 16px var(--composer-clearance, 220px);
  scroll-padding-bottom: var(--composer-clearance, 220px);
}

.messages::-webkit-scrollbar {
  width: 5px;
}

.messages::-webkit-scrollbar-track {
  background: transparent;
}

.messages::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb);
  border-radius: 999px;
}

.empty-state {
  margin: 64px auto;
  text-align: center;
  max-width: 640px;
  animation: fade-in 0.28s var(--ease-out);
}

@keyframes fade-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.hero-watermark {
  display: block;
  width: 190px;
  height: auto;
  margin: 0 auto 4px;
  opacity: 1;
  user-select: none;
  pointer-events: none;
}

.hero-greeting {
  font-family: var(--font-serif);
  font-size: 30px;
  font-weight: 600;
  letter-spacing: 0.01em;
  color: var(--text-primary);
  margin: 0;
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: 26px;
}

.messages-shell {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.conversation-rail {
  position: absolute;
  top: 50%;
  left: 6px;
  z-index: 6;
  display: flex;
  max-height: 76%;
  flex-direction: column;
  transform: translateY(-50%);
}

.conversation-rail__ticks {
  display: flex;
  flex: 0 1 auto;
  min-height: 0;
  flex-direction: column;
  gap: 2px;
  padding: 4px 7px;
  overflow-y: auto;
  border-radius: 12px;
  scrollbar-width: none;
}

.conversation-rail__ticks::-webkit-scrollbar {
  display: none;
}

.conversation-rail__tick {
  flex: none;
  /* 统一宽度：18px 横杠 + 左右各 6px 命中区，静止时全部刻度左右边缘对齐 */
  width: 30px;
  height: 10px;
  padding: 0 6px;
  display: flex;
  align-items: center;
  border: 0;
  background: transparent;
  cursor: pointer;
  box-sizing: border-box;
}

.conversation-rail__tick::after {
  content: '';
  width: 100%;
  height: 2px;
  border-radius: 0;
  background: color-mix(in srgb, var(--text-secondary) 36%, transparent);
  transition: background-color 0.16s var(--ease-out), height 0.16s var(--ease-out);
}

.conversation-rail__tick:hover::after {
  height: 3px;
  background: color-mix(in srgb, var(--text-primary) 64%, transparent);
}

.conversation-rail__tick.is-active::after {
  background: var(--accent-color);
}

.conversation-rail__tick.is-active:hover::after {
  background: var(--accent-color);
}

.conversation-rail__preview {
  position: absolute;
  top: 0;
  left: calc(100% + 2px);
  z-index: 8;
  width: min(320px, 56vw);
  padding: 10px 12px 11px;
  border: 1px solid var(--border-light);
  border-radius: 12px;
  background: var(--bg-panel);
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.36);
  transform: translateY(-50%);
  text-align: left;
  pointer-events: none;
}

.conversation-rail__preview-round {
  display: block;
  margin-bottom: 4px;
  font-size: 11px;
  letter-spacing: 0.04em;
  color: var(--text-secondary);
}

.conversation-rail__preview p {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--text-primary);
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 5;
  overflow: hidden;
  overflow-wrap: anywhere;
}

.rail-preview-enter-active,
.rail-preview-leave-active {
  transition: opacity 0.14s ease, transform 0.14s ease;
}

.rail-preview-enter-from,
.rail-preview-leave-to {
  opacity: 0;
  transform: translateY(-50%) translateX(-4px);
}

.message-row.rail-flash {
  border-radius: 12px;
  animation: rail-flash-highlight 1.6s var(--ease-out);
}

@keyframes rail-flash-highlight {
  0% {
    background: var(--accent-fade);
    box-shadow: inset 2px 0 0 var(--accent-color);
  }
  100% {
    background: transparent;
    box-shadow: inset 2px 0 0 transparent;
  }
}

.workflow-history-detail {
  display: flex;
  width: min(100%, 920px);
  margin: 0 auto;
  flex-direction: column;
  gap: 18px;
  animation: fade-in 0.24s var(--ease-out);
}

.workflow-history-loading {
  display: flex;
  min-height: 220px;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text-secondary);
}
.workflow-history-loading.is-error { flex-direction: column; }
.workflow-history-loading strong { color: var(--text-primary); font-size: 14px; }
.workflow-history-loading button,
.workflow-history-partial button {
  min-height: 30px;
  padding: 0 10px;
  border: 1px solid var(--primary-line);
  border-radius: 6px;
  background: var(--primary-fade);
  color: var(--primary-color);
  cursor: pointer;
}
.workflow-history-partial {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 9px 12px;
  border: 1px solid color-mix(in srgb, var(--warning) 34%, var(--border-light));
  border-radius: 7px;
  background: var(--warning-fade);
  color: var(--text-secondary);
  font-size: 12px;
}


.workflow-history-request {
  overflow: hidden;
  border: 1px solid var(--border-light);
  border-radius: 14px;
  background: var(--surface-solid);
  box-shadow: var(--shadow-sm);
}

.workflow-history-request header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--border-light);
}

.workflow-history-eyebrow {
  color: var(--primary-color);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.workflow-history-request h3 {
  margin: 5px 0 0;
  color: var(--text-primary);
  font-size: 17px;
}

.workflow-history-identity {
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  color: var(--text-secondary);
  font-size: 11px;
}

.workflow-history-identity code {
  max-width: 240px;
  overflow: hidden;
  color: var(--text-primary);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workflow-history-request pre {
  max-height: 320px;
  margin: 0;
  padding: 18px 20px;
  overflow: auto;
  color: var(--text-primary);
  font: inherit;
  font-size: 14px;
  line-height: 1.75;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.template-row {
  display: flex;
  gap: 8px;
  padding: 10px 16px 0;
  overflow-x: auto;
}

/* 右侧工作台滑入动画 */
.agent-panel-slide-enter-active {
  transition: opacity 0.22s var(--ease-out), transform 0.22s var(--ease-out);
}
.agent-panel-slide-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.agent-panel-slide-enter-from {
  opacity: 0;
  transform: translateX(12px);
}
.agent-panel-slide-leave-to {
  opacity: 0;
  transform: translateX(12px);
}

@media (prefers-reduced-motion: reduce) {
  .agent-panel-slide-enter-active,
  .agent-panel-slide-leave-active {
    transition: none;
  }
}

.template-item {
  border: 1px solid var(--border-light);
  background: var(--bg-card);
  border-radius: 8px;
  padding: 6px 14px;
  white-space: nowrap;
  cursor: pointer;
  font-size: 13px;
  transition: var(--transition);
}

.template-item:hover {
  border-color: var(--primary-color);
  background: var(--primary-fade);
}

.composer {
  flex-shrink: 0;
  position: relative;
  display: flex;
  flex-direction: column;
  padding: 8px 14px 12px;
  background: transparent;
  will-change: transform;
}

.chat-workflow-progress,
.chat-workflow-review,
.chat-workflow-error {
  order: 0;
  width: 50%;
  margin: 0 auto 7px;
}
.chat-workflow-error {
  padding: 8px 10px;
  border: 1px solid color-mix(in srgb, var(--danger) 36%, var(--border-light));
  border-radius: 6px;
  background: var(--danger-fade);
  color: var(--danger);
  font-size: 12px;
  line-height: 1.45;
  text-wrap: pretty;
}

.workflow-run-strip {
  order: 0;
  width: 50%;
  min-height: 34px;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 auto 7px;
  padding: 5px 7px 5px 10px;
  overflow: hidden;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: var(--bg-card);
  color: var(--text-secondary);
  box-shadow: var(--shadow-sm);
}

.workflow-run-strip__state {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
  font-size: 11px;
  font-weight: 650;
}

.workflow-run-strip__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--primary-color);
}

.workflow-run-strip.waiting_review .workflow-run-strip__dot,
.workflow-run-strip.retrying .workflow-run-strip__dot {
  background: var(--warning);
}

.workflow-run-strip.completed .workflow-run-strip__dot {
  background: var(--success);
}

.workflow-run-strip.failed .workflow-run-strip__dot {
  background: var(--danger);
}

.workflow-run-strip.cancelled .workflow-run-strip__dot { background: var(--text-muted); }

.workflow-run-strip code {
  min-width: 96px;
  max-width: 180px;
  overflow: hidden;
  color: var(--text-primary);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workflow-run-strip__workflow {
  min-width: 0;
  flex: 1 1 auto;
  overflow: hidden;
  color: var(--text-muted);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workflow-run-strip__actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 0 0 auto;
}

.workflow-run-strip__actions button {
  height: 24px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0 7px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--primary-color);
  font: inherit;
  font-size: 10px;
  font-weight: 600;
  cursor: pointer;
}

.workflow-run-strip__actions button:hover,
.workflow-run-strip__actions button:focus-visible {
  background: var(--primary-fade);
  outline: none;
}

.workflow-run-strip__actions button:disabled {
  cursor: wait;
  opacity: 0.55;
}

.composer-popover {
  order: 0;
  width: 50%;
  margin: 0 auto 7px;
  border: 1px solid var(--border-light);
  border-radius: 12px;
  background: var(--bg-card);
  box-shadow: var(--shadow-md);
}

.composer-popover.template-row {
  padding: 6px;
}

.composer-popover.template-row .template-item {
  padding: 4px 10px;
  font-size: 12px;
}

.composer-shelf {
  order: 2;
  position: relative;
  z-index: 1;
  width: calc(50% - 24px);
  min-height: 46px;
  display: flex;
  align-items: center;
  gap: 4px;
  margin: -2px auto 0;
  padding: 7px 14px 6px;
  overflow-x: auto;
  border: 1px solid color-mix(in srgb, var(--primary-color) 14%, var(--border-light));
  border-top-color: color-mix(in srgb, var(--primary-color) 9%, var(--border-light));
  border-radius: 0 0 16px 16px;
  background:
    linear-gradient(120deg,
      color-mix(in srgb, var(--primary-fade) 42%, transparent),
      color-mix(in srgb, var(--bg-sidebar) 78%, transparent) 28%,
      color-mix(in srgb, var(--bg-sidebar) 72%, transparent) 72%,
      color-mix(in srgb, var(--accent-fade) 34%, transparent));
  backdrop-filter: blur(16px) saturate(1.08);
  -webkit-backdrop-filter: blur(16px) saturate(1.08);
  box-shadow:
    0 12px 30px color-mix(in srgb, var(--text-primary) 6%, transparent),
    -16px 8px 30px color-mix(in srgb, var(--bg-app) 42%, transparent),
    16px 8px 30px color-mix(in srgb, var(--bg-app) 42%, transparent);
}

.composer-shelf-action {
  height: 26px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
  padding: 0 7px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: 11px;
  cursor: pointer;
  transition: background-color 0.16s ease, color 0.16s ease;
}

.composer-shelf-action:hover,
.composer-shelf-action.active {
  background: var(--bg-panel);
  color: var(--text-primary);
}

.composer-shelf-action:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.composer-card {
  order: 1;
  position: relative;
  z-index: 2;
  width: 50%;
  min-height: 112px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  margin: 0 auto;
  overflow: hidden;
  border: 1px solid transparent;
  border-radius: 18px;
  background:
    linear-gradient(color-mix(in srgb, var(--bg-card) 82%, transparent), color-mix(in srgb, var(--bg-card) 82%, transparent)) padding-box,
    linear-gradient(115deg,
      color-mix(in srgb, var(--primary-color) 26%, var(--border-light)),
      color-mix(in srgb, var(--border-light) 76%, transparent) 34%,
      color-mix(in srgb, var(--accent-color) 18%, var(--border-light)) 76%,
      color-mix(in srgb, var(--primary-color) 30%, var(--border-light))) border-box;
  backdrop-filter: blur(18px) saturate(1.08);
  -webkit-backdrop-filter: blur(18px) saturate(1.08);
  box-shadow:
    0 18px 44px color-mix(in srgb, var(--text-primary) 9%, transparent),
    0 4px 16px color-mix(in srgb, var(--primary-color) 8%, transparent),
    -28px 10px 46px color-mix(in srgb, var(--bg-app) 58%, transparent),
    28px 10px 46px color-mix(in srgb, var(--bg-app) 58%, transparent);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.composer-card:focus-within {
  border-color: var(--border-focus);
  box-shadow: 0 0 0 4px var(--primary-fade), var(--shadow-md);
}

.composer-card > .el-textarea,
.composer-card > .el-input {
  flex: 1 1 auto;
  display: block;
  width: 100%;
  padding: 13px 16px 0;
  background: transparent;
}

.composer :deep(.el-textarea__inner) {
  min-height: 50px !important;
  padding: 2px 0 0 !important;
  border: 0 !important;
  background: transparent !important;
  box-shadow: none !important;
  font-size: 14px;
  line-height: 1.6;
}

/* Conversation state: collapse the capability composer into a Codex-like input bar. */
.chat-panel:not(.hero-mode) .composer-shelf {
  display: none;
}

.chat-panel:not(.hero-mode) .composer-card {
  min-height: 76px;
  border-radius: 18px;
}

.chat-panel:not(.hero-mode) .composer-card > .el-textarea,
.chat-panel:not(.hero-mode) .composer-card > .el-input {
  padding: 9px 14px 0;
}

.chat-panel:not(.hero-mode) .composer :deep(.el-textarea__inner) {
  min-height: 28px !important;
  line-height: 1.45;
}

.chat-panel:not(.hero-mode) .composer-footer {
  padding: 2px 9px 7px;
}

.composer-footer {
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 4px 10px 8px;
}

/* ZCode 式两层输入卡：上层深一档托盘条与卡片同宽（略内收），下层浅色卡片叠压其上 */
.composer-missions {
  order: 0;
  position: relative;
  z-index: 1;
  width: calc(60% - 32px);
  margin: 0 auto;
  display: flex;
  padding: 10px 12px 28px;
  border: 1px solid var(--border-light);
  border-radius: 14px;
  background: color-mix(in srgb, var(--text-secondary) 7%, var(--bg-card));
}

.chat-panel.hero-mode .composer-card {
  width: 60%;
  margin-top: -20px;
  min-height: 140px;
  box-shadow:
    0 22px 48px color-mix(in srgb, var(--text-primary) 13%, transparent),
    0 4px 16px color-mix(in srgb, var(--primary-color) 9%, transparent),
    -28px 10px 46px color-mix(in srgb, var(--bg-app) 58%, transparent),
    28px 10px 46px color-mix(in srgb, var(--bg-app) 58%, transparent);
}

.mission-anchor {
  position: relative;
}

.mission-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 9px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background-color 0.16s ease, color 0.16s ease;
}

.mission-chip > .el-icon {
  font-size: 12px;
  color: var(--primary-color);
}

.mission-chip__chevron {
  color: var(--text-disabled) !important;
  font-size: 9px !important;
}

.mission-chip:hover {
  background: color-mix(in srgb, var(--text-secondary) 10%, transparent);
  color: var(--text-primary);
}

.mission-chip:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--primary-color) 58%, transparent);
  outline-offset: 2px;
}

.mission-menu {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 0;
  z-index: 40;
  width: 300px;
  max-height: 340px;
  overflow-y: auto;
  padding: 5px;
  border: 1px solid var(--border-light);
  border-radius: 12px;
  background: var(--bg-card);
  box-shadow: var(--shadow-md);
  scrollbar-width: thin;
}

.mission-menu-hint {
  padding: 12px 8px;
  color: var(--text-disabled);
  font-size: 11.5px;
  text-align: center;
}

.mission-option {
  width: 100%;
  display: grid;
  gap: 1px;
  padding: 7px 9px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background-color 0.14s ease;
}

.mission-option strong {
  overflow: hidden;
  color: var(--text-primary);
  font-size: 12.5px;
  font-weight: 550;
  line-height: 1.3;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mission-option span {
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.4;
}

.mission-option:hover {
  background: var(--bg-panel);
}

.mission-pop-enter-active,
.mission-pop-leave-active {
  transition: opacity 0.16s ease, transform 0.16s ease;
}

.mission-pop-enter-from,
.mission-pop-leave-to {
  opacity: 0;
  transform: translateY(6px);
}


.left-actions,
.right-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.composer-icon-action {
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  padding: 0;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: 16px;
  cursor: pointer;
  transition: background-color 0.16s ease, color 0.16s ease;
}

.composer-icon-action:hover,
.composer-icon-action.active {
  background: var(--primary-fade);
  color: var(--primary-color);
}

.composer-acg-toggle {
  height: 25px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 0 8px;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.16s ease, background-color 0.16s ease;
}

.composer-acg-toggle:hover,
.composer-acg-toggle:focus-visible,
.composer-acg-toggle.active {
  background: var(--primary-fade);
  color: var(--primary-color);
  outline: none;
}

.composer-acg-toggle:disabled {
  cursor: not-allowed;
  opacity: 0.42;
}

.composer-send.el-button {
  width: 34px;
  height: 34px;
  margin-left: 2px;
  padding: 0;
  border-radius: 50%;
}

.word-count {
  color: var(--text-muted);
  font-size: 12px;
  white-space: nowrap;
}

.hidden-file-input {
  display: none;
}

.word-count.warning {
  color: #f59e0b;
}

.context-usage {
  min-height: 22px;
  padding: 2px 8px;
  border: 1px solid var(--border-light);
  border-radius: 999px;
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.4;
  white-space: nowrap;
  cursor: default;
  transition: color 160ms ease, border-color 160ms ease;
}

.context-usage.normal {
  color: var(--text-secondary);
}

.context-usage.warning {
  color: #f59e0b;
  border-color: color-mix(in srgb, #f59e0b 45%, transparent);
}

.context-usage.danger {
  color: #ef4444;
  border-color: color-mix(in srgb, #ef4444 45%, transparent);
}

.context-usage-tip {
  text-align: center;
  line-height: 1.6;
}

.agent-panel {
  position: relative;
  background: var(--bg-sidebar);
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 0;
  border: 0;
  border-radius: 0;
  transition: background-color 0.2s ease;
}

.agent-panel-resizer {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  z-index: 12;
  width: 8px;
  cursor: col-resize;
  touch-action: none;
  outline: none;
}

.agent-panel-resizer::after {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  width: 2px;
  background: var(--primary-color);
  opacity: 0;
  transform: scaleY(0.96);
  transition: opacity 0.16s ease, transform 0.16s ease;
}

.agent-panel-resizer:hover::after,
.agent-panel-resizer:focus-visible::after,
.agent-panel.resizing .agent-panel-resizer::after {
  opacity: 0.8;
  transform: scaleY(1);
}

.agent-panel-toggle-row {
  position: absolute;
  top: 0;
  right: 8px;
  z-index: 20;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
}

.agent-panel-toggle {
  min-width: 30px;
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  padding: 0;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  box-shadow: none;
  cursor: pointer;
  transition: border-color 0.16s ease, background-color 0.16s ease, color 0.16s ease, box-shadow 0.16s ease;
}

.agent-panel-toggle:hover {
  background: var(--bg-panel);
  color: var(--text-primary);
  box-shadow: none;
}

.agent-panel-toggle span {
  display: none;
}

.agent-panel-toggle:focus-visible {
  outline: 2px solid var(--primary-color);
  outline-offset: 2px;
}

.agent-panel.collapsed .agent-panel-toggle-row {
  position: static;
  flex: 0 0 54px;
  height: 54px;
  justify-content: center;
  padding: 0;
}

.agent-panel.collapsed .agent-panel-toggle {
  width: 38px;
  padding: 0;
  font-size: 16px;
}

.agent-panel-content {
  flex: 1;
  min-height: 0;
  padding: 0;
  overflow: auto;
}

.agent-panel-rail {
  flex: 1;
  display: flex;
  justify-content: center;
  padding-top: 14px;
}

.agent-panel-rail-icon {
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 9px;
  background: var(--primary-fade);
  color: var(--primary-color);
  font-size: 17px;
}
@media (max-width: 900px) {
  .workflow-run-strip,
  .chat-workflow-progress,
  .chat-workflow-review,
  .chat-workflow-error {
    width: calc(100% - 32px);
  }


}

@media (max-width: 620px) {
  .composer-card,
  .workflow-run-strip,
  .chat-workflow-progress,
  .chat-workflow-review,
  .chat-workflow-error {
    width: 100%;
  }

  .composer-missions {
    width: calc(100% - 32px);
  }

  .workflow-run-strip {
    flex-wrap: wrap;
    overflow: visible;
  }

  .workflow-run-strip__workflow {
    display: none;
  }

  .workflow-run-strip__actions {
    margin-left: auto;
  }


  .chat-main .empty-state {
    margin: 18px auto;
    padding: 0 12px;
  }

  .chat-main .hero-watermark {
    width: 128px;
  }

  .chat-main .hero-greeting {
    font-size: 24px;
  }

  .chat-main .template-row {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    overflow: visible;
  }

  .chat-main .template-item {
    min-width: 0;
    padding: 6px 8px;
    white-space: normal;
  }


  .chat-main .composer-footer {
    flex-direction: column;
    align-items: stretch;
  }

  .composer-footer .left-actions {
    width: 100%;
  }


  .composer-footer .right-actions {
    display: grid;
    grid-template-columns: 1fr auto;
    width: 100%;
  }

  .composer-footer .right-actions :deep(.model-runtime-controls) {
    grid-column: 1 / -1;
    width: 100%;
  }

}

@media (max-width: 1100px) {
  .chat-main.has-agent-results {
    grid-template-columns: 1fr;
  }

  .agent-panel {
    border-left: none;
    border-top: 1px solid var(--border-light);
    max-height: 300px;
  }

  .agent-panel-resizer {
    display: none;
  }

}

/* Screenshot refinement: quieter surfaces, clearer focus, and a lighter hero rhythm. */
.chat-panel.hero-mode {
  --hero-composer-center-y: 55.5%;
  --hero-slogan-offset-y: 218px;
}

.chat-panel.hero-mode .empty-state {
  width: min(calc(100% - 48px), 720px);
}

.hero-watermark {
  width: 170px;
  margin-bottom: 12px;
  opacity: 0.94;
  filter: saturate(0.9) brightness(0.94);
}

.hero-logo-field {
  --hero-logo-aura-opacity: 0.12;
  --hero-logo-aura-scale: 1;
  position: relative;
  width: 170px;
  aspect-ratio: 1;
  display: grid;
  place-items: center;
  margin: 0 auto 12px;
  isolation: isolate;
  pointer-events: auto;
  cursor: default;
  touch-action: none;
}

.hero-logo-field::before {
  position: absolute;
  inset: 22%;
  z-index: -1;
  border-radius: 50%;
  background: radial-gradient(circle, color-mix(in srgb, var(--primary-color) 18%, transparent), transparent 70%);
  content: '';
  opacity: var(--hero-logo-aura-opacity);
  transform: scale(var(--hero-logo-aura-scale));
  filter: blur(18px);
  pointer-events: none;
  transition: opacity 260ms ease, transform 260ms ease;
}

.hero-logo-filter-defs {
  position: absolute;
  width: 0;
  height: 0;
  overflow: hidden;
  pointer-events: none;
}

.hero-logo-field .hero-watermark {
  width: 100%;
  margin: 0;
  filter: url('#hero-logo-fluid') saturate(0.9) brightness(0.94);
  transform-origin: center;
  will-change: transform, filter;
  pointer-events: none;
  transition: filter 240ms ease;
}

.hero-logo-field.is-pressed::before {
  opacity: 0.38;
}

.hero-greeting {
  font-size: 32px;
  font-weight: 580;
  letter-spacing: 0.015em;
  text-wrap: balance;
}

.composer-card {
  border: 0;
  border-radius: 22px;
  background: color-mix(in srgb, var(--bg-card) 94%, var(--bg-panel));
  overflow: visible;
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.3);
}

.composer-card:focus-within {
  box-shadow:
    0 18px 44px rgba(0, 0, 0, 0.38),
    0 0 30px color-mix(in srgb, var(--accent-color) 12%, transparent);
}

.chat-panel.hero-mode .composer-card {
  margin-top: -16px;
  min-height: 134px;
  box-shadow: 0 20px 46px rgba(0, 0, 0, 0.36);
}

.composer-footer {
  margin-top: 0;
  padding-top: 4px;
  border-top: 0;
}

.composer-missions {
  padding: 8px 12px 24px;
  border: 0;
  border-radius: 18px 18px 0 0;
  background: color-mix(in srgb, var(--bg-card) 54%, transparent);
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  box-shadow: none;
}

.composer-card :deep(.model-runtime-controls) {
  gap: 2px;
}

.composer-card :deep(.model-runtime-controls .el-select__wrapper) {
  min-height: 26px;
  padding: 0 4px;
  border: 0 !important;
  border-radius: 0;
  background: transparent !important;
  box-shadow: none !important;
}

.composer-card :deep(.model-runtime-controls .el-select__wrapper:hover),
.composer-card :deep(.model-runtime-controls .el-select__wrapper.is-focused) {
  background: color-mix(in srgb, var(--text-primary) 6%, transparent) !important;
  box-shadow: none !important;
}

.composer-tools-anchor {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.composer-tools-toggle.active {
  background: color-mix(in srgb, var(--primary-color) 14%, transparent);
  color: var(--primary-color);
}

.composer-tools-menu {
  position: absolute;
  bottom: calc(100% + 12px);
  left: 0;
  z-index: 30;
  width: min(360px, calc(100vw - 36px));
  padding: 10px 12px;
  border: 0;
  border-radius: 16px;
  background: color-mix(in srgb, var(--bg-card) 96%, var(--bg-panel));
  box-shadow: 0 18px 42px rgba(0, 0, 0, 0.34);
}

.composer-tools-menu__item {
  width: 100%;
  height: 32px;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0 7px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}

.composer-tools-menu__item:hover,
.composer-tools-menu__item:focus-visible {
  background: color-mix(in srgb, var(--text-primary) 7%, transparent);
  color: var(--text-primary);
  outline: none;
}

.composer-tools-menu__runtime {
  display: grid;
  gap: 4px;
  margin-top: 6px;
  padding: 4px 0 0;
}

.composer-tools-menu__label {
  padding: 0 7px;
  color: var(--text-muted);
  font-size: 10px;
  line-height: 1.4;
}

.composer-tools-menu__runtime :deep(.model-runtime-controls) {
  width: 100%;
  justify-content: space-between;
}





.mission-chip {
  height: 28px;
  color: var(--text-muted);
}

.mission-chip:hover,
.mission-chip:focus-visible {
  background: var(--bg-card);
  color: var(--text-primary);
  outline: none;
}

.composer-icon-action:hover,
.composer-icon-action.active {
  background: color-mix(in srgb, var(--primary-color) 18%, transparent);
}

/* 按钮配色取自首页花环：白花 #E2E1DA / 松果褐 #482E19 */
.composer-send.el-button {
  width: 38px;
  height: 38px;
  border-color: transparent;
  background: #E2E1DA;
  color: #482E19;
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.2);
}

.composer-send.el-button:hover,
.composer-send.el-button:focus-visible {
  border-color: transparent;
  background: #EFEEE6;
  color: #482E19;
}

.composer-send.el-button:active {
  background: #D6D4C9;
}

.composer-send.el-button:focus-visible {
  outline: 2px solid rgba(226, 225, 218, 0.42);
  outline-offset: 2px;
}

/* 放在 hover 之后：同优先级下靠源顺序压过 hover，避免禁用态悬停变亮 */
.composer-send.el-button:disabled {
  border-color: transparent;
  background: color-mix(in srgb, #E2E1DA 14%, var(--bg-panel));
  color: rgba(226, 225, 218, 0.38);
  box-shadow: none;
}

@media (max-width: 900px) {
  .hero-watermark { width: 128px; }
  .hero-logo-field { width: 128px; }
  .hero-greeting { font-size: 24px; }
  .composer-footer { margin-top: 8px; }
}

@media (prefers-reduced-motion: reduce) {
  .hero-logo-field::before {
    display: none;
  }

  .hero-logo-field .hero-watermark {
    filter: saturate(0.9) brightness(0.94);
    transform: none !important;
    transition: none;
  }
}
</style>
