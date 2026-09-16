<!-- 主对话页面 — 角色快速导航（律师/教师/程序员/作家）与聊天工作台 -->
<template>
  <div class="chat-view detail-interface">
    <div
      class="chat-main"
      :class="[
        chatMainClass,
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
              <img class="hero-watermark" src="/logo.png" alt="" />
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
              <div v-if="showLawyerHistoryFeedback" class="lawyer-history-conversation">
                <MessageBubble
                  :message="{
                    id: `history-user-${activeWorkflowRun.runId}`,
                    role: 'user',
                    content: workflowHistoryInput,
                    createdAt: workflowHistoryMessageTime
                  }"
                />
                <ContractReviewReportMessage
                  :deliverables="workflowHistoryStepOutputs"
                  :report="lawyerHistoryReply"
                  :risks="activeContractReviewArtifacts.risks"
                />
              </div>
              <template v-else>
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
            </template>
          </section>

          <div v-else class="message-list">
            <div
              v-for="msg in chatStore.messages"
              :key="msg.id"
              class="message-row"
              :class="msg.role"
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

        <div ref="composerRef" class="composer" :style="{ bottom: composerDockOffset }">
          <div
            v-if="(isSubmittingWorkflow || activeWorkflowRunId) && !isGeneralAgentMode"
            class="chat-workflow-progress"
          >
            <div
              v-if="isLawyerMode"
              class="lawyer-workflow-progress"
              :class="[activeWorkflowStatus, { collapsed: lawyerWorkflowProgressCollapsed }]"
            >
              <template v-if="!lawyerWorkflowProgressCollapsed">
                <WorkflowProgressBar
                  id="lawyer-workflow-progress-detail"
                  :progress="workflowProgressState.progress.value"
                  :loading="isSubmittingWorkflow || workflowProgressState.isLoading.value"
                  :sync-error="workflowProgressState.syncError.value"
                  variant="compact"
                />
                <button
                  type="button"
                  class="lawyer-workflow-progress__toggle"
                  aria-label="折叠 ACG 执行状态"
                  aria-expanded="true"
                  aria-controls="lawyer-workflow-progress-detail"
                  title="折叠执行状态"
                  @click="lawyerWorkflowProgressCollapsed = true"
                >
                  <el-icon><ArrowUp /></el-icon>
                </button>
              </template>
              <button
                v-else
                type="button"
                class="lawyer-workflow-progress__collapsed-row"
                aria-label="展开 ACG 执行状态"
                aria-expanded="false"
                aria-controls="lawyer-workflow-progress-detail"
                @click="lawyerWorkflowProgressCollapsed = false"
              >
                <span class="lawyer-workflow-progress__identity">
                  <span class="lawyer-workflow-progress__dot" aria-hidden="true"></span>
                  <strong>ACG 执行状态</strong>
                  <span>{{ activeWorkflowStatusLabel }}</span>
                </span>
                <span class="lawyer-workflow-progress__expand">
                  <span v-if="workflowProgressState.progress.value?.percent != null">
                    {{ workflowProgressState.progress.value.percent }}%
                  </span>
                  <span>展开</span>
                  <el-icon><ArrowUp /></el-icon>
                </span>
              </button>
            </div>
            <WorkflowProgressBar
              v-else
              :progress="workflowProgressState.progress.value"
              :loading="isSubmittingWorkflow || workflowProgressState.isLoading.value"
              :sync-error="workflowProgressState.syncError.value"
              variant="compact"
            />
            <AgentOsRunSummaryCard
              v-if="!isLawyerMode"
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
            v-if="activeWorkflowRunId && !isGeneralAgentMode"
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

          <div v-if="isTeacherMode" class="composer-shelf">
            <button class="composer-shelf-action" type="button" @click="openTeacherUploadDialog">
              <el-icon><UploadFilled /></el-icon>
              <span>上传作业</span>
            </button>
            <input
              ref="teacherUploadInputRef"
              class="hidden-file-input"
              type="file"
              accept=".png,.jpg,.jpeg,.pdf,.txt,.doc,.docx"
              @change="handleTeacherFileUpload"
            />
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
                <button
                  class="composer-agent-mode"
                  type="button"
                  aria-haspopup="dialog"
                  :aria-expanded="roleTemplateDialogOpen"
                  title="切换角色与模板"
                  @click="openRoleTemplateDialog"
                >
                  <el-icon class="composer-agent-mode__icon"><component :is="agentIcon" /></el-icon>
                  {{ composerModeLabel }}
                  <el-icon class="composer-agent-mode__chevron"><ArrowDownBold /></el-icon>
                </button>
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
              v-if="isGeneralAgentMode"
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
            <LawyerSkillPanel
              v-else-if="isLawyerMode"
              :skills-used="latestLawyerMeta.skillsUsed"
              :trace="latestLawyerMeta.trace"
              :federated="latestLawyerMeta.federated"
              :risk-level="latestLawyerMeta.riskLevel"
              :result-count="availableLawyerResultPanels.length"
              @open-federated-console="openFederatedConsole"
              @optimize-federated="handleFederatedOptimize"
            >
          <template #results>
            <div v-if="!availableLawyerResultPanels.length" class="results-empty">
              <el-icon class="empty-icon"><Notebook /></el-icon>
              <span>暂无技能调用结果</span>
              <span class="results-empty-hint">发送消息后，这里会整理 Agent 的结构化结果</span>
            </div>
            <el-collapse v-else v-model="activeLawyerResultPanels">
              <el-collapse-item
                v-if="availableLawyerResultPanels.includes('evidence')"
                title="证据分析结果"
                name="evidence"
              >
                <EvidenceAnalysisCard :data="latestLawyerSkillResults.evidenceAnalysis" />
              </el-collapse-item>

              <el-collapse-item
                v-if="availableLawyerResultPanels.includes('limitation')"
                title="诉讼时效结果"
                name="limitation"
              >
                <LimitationTimeline :data="latestLawyerSkillResults.limitationCalc" />
              </el-collapse-item>

              <el-collapse-item
                v-if="availableLawyerResultPanels.includes('jurisdiction')"
                title="管辖法院建议"
                name="jurisdiction"
              >
                <JurisdictionCard :data="latestLawyerSkillResults.jurisdiction" />
              </el-collapse-item>

              <el-collapse-item
                v-if="availableLawyerResultPanels.includes('hearing')"
                title="庭审提纲"
                name="hearing"
              >
                <HearingOutlineViewer :data="latestLawyerSkillResults.hearingOutline" />
              </el-collapse-item>

              <el-collapse-item
                v-if="availableLawyerResultPanels.includes('contractRisks')"
                title="合同风险识别"
                name="contractRisks"
              >
                <ContractRiskPanel :risks="activeContractReviewArtifacts.risks" />
              </el-collapse-item>

              <el-collapse-item
                v-if="availableLawyerResultPanels.includes('contractEvidence')"
                title="法律依据链"
                name="contractEvidence"
              >
                <ContractEvidencePanel :evidences="activeContractReviewArtifacts.evidences" />
              </el-collapse-item>

              <el-collapse-item
                v-if="availableLawyerResultPanels.includes('contractReport')"
                title="合同审查报告"
                name="contractReport"
              >
                <ContractReportPreview :report-markdown="activeContractReviewArtifacts.reportMarkdown" />
              </el-collapse-item>
            </el-collapse>
          </template>
        </LawyerSkillPanel>

        <TeacherSkillPanel
          v-else-if="isTeacherMode"
          :skills-used="latestTeacherMeta.skillsUsed"
          :trace="latestTeacherMeta.trace"
          :federated="latestTeacherMeta.federated"
          :result-count="availableTeacherResultPanels.length"
          @open-federated-console="openFederatedConsole"
          @optimize-federated="handleFederatedOptimize"
        >
          <template #results>
            <div v-if="!availableTeacherResultPanels.length" class="results-empty">
              <el-icon class="empty-icon"><Reading /></el-icon>
              <span>暂无技能调用结果</span>
              <span class="results-empty-hint">发送消息后，这里会整理 Agent 的结构化结果</span>
            </div>
            <el-collapse v-else v-model="activeTeacherResultPanels">
              <el-collapse-item
                v-if="availableTeacherResultPanels.includes('diagnosis')"
                title="学情诊断"
                name="diagnosis"
              >
                <DiagnosisRadar :data="latestTeacherSkillResults.studentDiagnosis" />
              </el-collapse-item>

              <el-collapse-item
                v-if="availableTeacherResultPanels.includes('lessonPlan')"
                title="个性化教案"
                name="lessonPlan"
              >
                <LessonPlanViewer :data="latestTeacherSkillResults.lessonPlan" />
              </el-collapse-item>

              <el-collapse-item
                v-if="availableTeacherResultPanels.includes('grading')"
                title="作业批改"
                name="grading"
              >
                <GradingResultCard :data="latestTeacherSkillResults.homeworkGrading" />
              </el-collapse-item>

              <el-collapse-item
                v-if="availableTeacherResultPanels.includes('questionPush')"
                title="错题归因与推题"
                name="questionPush"
              >
                <QuestionPushList :data="latestTeacherSkillResults.errorQuestionPush" />
              </el-collapse-item>
            </el-collapse>
          </template>
        </TeacherSkillPanel>

        <ProgrammerSkillPanel
          v-else-if="isProgrammerMode"
          :skills-used="latestProgrammerMeta.skillsUsed"
          :trace="latestProgrammerMeta.trace"
          :federated="latestProgrammerMeta.federated"
          :result-count="availableProgrammerResultPanels.length"
          @open-federated-console="openFederatedConsole"
          @optimize-federated="handleFederatedOptimize"
        >
          <template #results>
            <div v-if="!availableProgrammerResultPanels.length" class="results-empty">
              <el-icon class="empty-icon"><Cpu /></el-icon>
              <span>暂无技能调用结果</span>
              <span class="results-empty-hint">发送消息后，这里会整理 Agent 的结构化结果</span>
            </div>
            <el-collapse v-else v-model="activeProgrammerResultPanels">
              <el-collapse-item
                v-if="availableProgrammerResultPanels.includes('requirement')"
                title="需求分析"
                name="requirement"
              >
                <div class="programmer-block">
                  <div class="programmer-grid two-cols">
                    <div class="programmer-card">
                      <div class="card-title">功能需求</div>
                      <ul>
                        <li v-for="(item, idx) in (latestProgrammerSkillResults.requirementAnalysis?.functional_requirements || [])" :key="`fr-${idx}`">
                          {{ item }}
                        </li>
                      </ul>
                    </div>
                    <div class="programmer-card">
                      <div class="card-title">边界条件</div>
                      <ul>
                        <li v-for="(item, idx) in (latestProgrammerSkillResults.requirementAnalysis?.boundary_conditions || [])" :key="`bc-${idx}`">
                          {{ item }}
                        </li>
                      </ul>
                    </div>
                  </div>
                  <div class="programmer-grid two-cols">
                    <div class="programmer-card">
                      <div class="card-title">输入</div>
                      <ul>
                        <li v-for="(item, idx) in (latestProgrammerSkillResults.requirementAnalysis?.inputs || [])" :key="`in-${idx}`">{{ item }}</li>
                      </ul>
                    </div>
                    <div class="programmer-card">
                      <div class="card-title">输出</div>
                      <ul>
                        <li v-for="(item, idx) in (latestProgrammerSkillResults.requirementAnalysis?.outputs || [])" :key="`out-${idx}`">{{ item }}</li>
                      </ul>
                    </div>
                  </div>
                </div>
              </el-collapse-item>

              <el-collapse-item
                v-if="availableProgrammerResultPanels.includes('search')"
                title="代码库语义检索"
                name="search"
              >
                <div class="programmer-block">
                  <div class="programmer-meta">
                    命中 {{ latestProgrammerSkillResults.searchHits.length }} 条 · 向量检索
                    {{ latestProgrammerSkillResults.codebaseSemanticSearch?.index_status?.vector_enabled ? '已启用' : '未启用（关键词降级）' }}
                  </div>
                  <div class="programmer-search-list">
                    <div
                      v-for="(hit, idx) in latestProgrammerSkillResults.searchHits"
                      :key="`hit-${idx}`"
                      class="search-item"
                    >
                      <div class="search-head">
                        <span class="path">{{ hit.file_path || 'unknown file' }}</span>
                        <span class="score">score: {{ Number(hit.score || 0).toFixed(3) }}</span>
                      </div>
                      <pre>{{ hit.content }}</pre>
                    </div>
                  </div>
                </div>
              </el-collapse-item>

              <el-collapse-item
                v-if="availableProgrammerResultPanels.includes('code')"
                title="代码生成"
                name="code"
              >
                <div class="programmer-block">
                  <div class="programmer-meta">{{ latestProgrammerSkillResults.codeGeneration?.explanation || '暂无说明' }}</div>
                  <pre class="code-block">{{ latestProgrammerSkillResults.generatedCode || '// 暂无代码输出' }}</pre>
                  <div v-if="latestProgrammerSkillResults.suggestedTests.length" class="programmer-card">
                    <div class="card-title">建议测试点</div>
                    <ul>
                      <li v-for="(item, idx) in latestProgrammerSkillResults.suggestedTests" :key="`test-${idx}`">{{ item }}</li>
                    </ul>
                  </div>
                </div>
              </el-collapse-item>

              <el-collapse-item
                v-if="availableProgrammerResultPanels.includes('diagram')"
                title="Mermaid 图表"
                name="diagram"
              >
                <DiagramViewer :data="latestProgrammerSkillResults.diagramData" />
              </el-collapse-item>
            </el-collapse>
          </template>
        </ProgrammerSkillPanel>

        <WriterSkillPanel
          v-else-if="isWriterMode"
          :skills-used="latestWriterMeta.skillsUsed"
          :trace="latestWriterMeta.trace"
          :federated="latestWriterMeta.federated"
          :result-count="availableWriterResultPanels.length"
          @open-federated-console="openFederatedConsole"
          @optimize-federated="handleFederatedOptimize"
        >
          <template #results>
            <div v-if="!availableWriterResultPanels.length" class="results-empty">
              <el-icon class="empty-icon"><EditPen /></el-icon>
              <span>暂无技能调用结果</span>
              <span class="results-empty-hint">发送消息后，这里会整理 Agent 的结构化结果</span>
            </div>
            <el-collapse v-else v-model="activeWriterResultPanels">
              <el-collapse-item
                v-if="availableWriterResultPanels.includes('inspiration')"
                title="创意树思维导图"
                name="inspiration"
              >
                <MindMapViewer
                  title="创意树"
                  :creative-tree="latestWriterSkillResults.creativeTree"
                />
              </el-collapse-item>

              <el-collapse-item
                v-if="availableWriterResultPanels.includes('outline')"
                title="章节大纲思维导图"
                name="outline"
              >
                <MindMapViewer
                  title="章节大纲"
                  :outline-markdown="latestWriterSkillResults.outlineMarkdown"
                />
              </el-collapse-item>

              <el-collapse-item
                v-if="availableWriterResultPanels.includes('content')"
                title="正文撰写"
                name="content"
              >
                <div class="writer-content-preview">
                  {{ latestWriterSkillResults.content || '暂无正文内容' }}
                </div>
              </el-collapse-item>

              <el-collapse-item
                v-if="availableWriterResultPanels.includes('relation')"
                title="人物关系图"
                name="relation"
              >
                <RelationGraph :data="latestWriterSkillResults.characterRelationMap" />
              </el-collapse-item>
            </el-collapse>
          </template>
        </WriterSkillPanel>
          </div>
      </aside>
      </Transition>
    </div>

    <RoleTemplateSwitchDialog
      :open="roleTemplateDialogOpen"
      :current-role-name="currentRole?.name"
      :current-template-key="selectedChatTemplateKey"
      @close="roleTemplateDialogOpen = false"
      @confirm="applyRoleTemplateSelection"
    />

    <el-drawer v-model="showRoleDrawer" direction="rtl" :size="320" :with-header="false">
      <div class="drawer-head">
        <h3>角色列表</h3>
        <el-button text @click="showRoleDrawer = false"><el-icon><Close /></el-icon></el-button>
      </div>
      <div class="role-list">
        <div
          class="role-item"
          :class="{ active: !currentRole && !selectedRoleId }"
          @click="selectGeneralMode"
        >
          <el-avatar :size="36">通</el-avatar>
          <div class="role-text">
            <div class="name">通用模式</div>
            <div class="desc">不绑定角色，按任务智能路由</div>
          </div>
          <el-icon v-if="!currentRole && !selectedRoleId"><Check /></el-icon>
        </div>
        <div
          v-for="role in roles"
          :key="role.id"
          class="role-item"
          :class="{ active: roleStore.currentRole?.id === role.id || selectedRoleId === role.id }"
          @click="selectRole(role)"
        >
          <el-avatar :size="36" :src="role.avatar">{{ role.name?.charAt(0) }}</el-avatar>
          <div class="role-text">
            <div class="name">{{ role.name }}</div>
            <div class="desc">{{ role.description || 'AI Assistant' }}</div>
          </div>
          <el-icon v-if="roleStore.currentRole?.id === role.id || selectedRoleId === role.id"><Check /></el-icon>
        </div>
      </div>
    </el-drawer>

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
  Check,
  Clock,
  Close,
  Cpu,
  DArrowLeft,
  DArrowRight,
  EditPen,
  Loading,
  Microphone,
  Notebook,
  Plus,
  Reading,
  ScaleToOriginal,
  Share,
  School,
  UploadFilled
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import MessageBubble from '@/components/MessageBubble.vue'
import ModelRuntimeControls from '@/components/ModelRuntimeControls.vue'
import FileManager from '@/components/FileManager.vue'
import LawyerSkillPanel from '@/components/agent/LawyerSkillPanel.vue'
import TeacherSkillPanel from '@/components/agent/TeacherSkillPanel.vue'
import ProgrammerSkillPanel from '@/components/agent/ProgrammerSkillPanel.vue'
import WriterSkillPanel from '@/components/agent/WriterSkillPanel.vue'
import EvidenceAnalysisCard from '@/components/agent/EvidenceAnalysisCard.vue'
import LimitationTimeline from '@/components/agent/LimitationTimeline.vue'
import JurisdictionCard from '@/components/agent/JurisdictionCard.vue'
import HearingOutlineViewer from '@/components/agent/HearingOutlineViewer.vue'
import DiagnosisRadar from '@/components/agent/DiagnosisRadar.vue'
import LessonPlanViewer from '@/components/agent/LessonPlanViewer.vue'
import GradingResultCard from '@/components/agent/GradingResultCard.vue'
import QuestionPushList from '@/components/agent/QuestionPushList.vue'
const DiagramViewer = defineAsyncComponent(() => import('@/components/agent/DiagramViewer.vue'))
const MindMapViewer = defineAsyncComponent(() => import('@/components/agent/MindMapViewer.vue'))
const RelationGraph = defineAsyncComponent(() => import('@/components/agent/RelationGraph.vue'))
import RoleTemplateSwitchDialog from '@/components/RoleTemplateSwitchDialog.vue'
const AcgTopologyGraph = defineAsyncComponent(() => import('@/components/agentos/AcgTopologyGraph.vue'))
import WorkflowProgressBar from '@/components/agentos/WorkflowProgressBar.vue'
import WorkflowReviewPanel from '@/components/agentos/WorkflowReviewPanel.vue'
import AgentOsRunSummaryCard from '@/components/agentos/AgentOsRunSummaryCard.vue'
import RuntimeAuditTimeline from '@/components/agentos/RuntimeAuditTimeline.vue'
import AcgRunInspector from '@/components/agentos/AcgRunInspector.vue'
import ContractReviewReportMessage from '@/components/agentos/ContractReviewReportMessage.vue'
import ContractRiskPanel from '@/components/agentos/ContractRiskPanel.vue'
import ContractEvidencePanel from '@/components/agentos/ContractEvidencePanel.vue'
import ContractReportPreview from '@/components/agentos/ContractReportPreview.vue'
import GenericArtifactPanel from '@/features/acg/GenericArtifactPanel.vue'
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
import { agentTeacherApi } from '@/services/api/agentTeacher'
import { federatedModelApi } from '@/services/api/federatedModel'
import { fileApi } from '@/services/api/file'
import { useChatStore, type ChatWorkflowBinding } from '@/stores/chat'
import { useRoleStore } from '@/stores/role'
import { useWorkflowProgress } from '@/composables/useWorkflowProgress'
import { extractContractReviewArtifacts } from '@/utils/agentos/contractReviewArtifactExtractor'
import { setConversationWorkspace } from '@/utils/conversationWorkspace'
import { wasErrorUserNotified } from '@/utils/request'
import { resolveAcgTaskTitle } from '@/utils/acgTaskTitle'
import { ACG_HISTORY_SOURCES, acgHistoryRoleDomain, loadAcgHistoryRole } from '@/utils/acgHistoryFilter'
import { loadModelSettings } from '@/config/modelSettings'
import { roleTemplateGroups, type RoleId } from '@/config/agentWorkbench'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const roleStore = useRoleStore()
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

const selectedRoleId = ref<string | null>(null)
const inputText = ref('')
const loading = ref(false)
const showRoleDrawer = ref(false)
const roleTemplateDialogOpen = ref(false)
const CHAT_TEMPLATE_KEY = 'chat.active_template_key'
const selectedChatTemplateKey = ref(localStorage.getItem(CHAT_TEMPLATE_KEY) || '')
const showFileManager = ref(false)
const isRecording = ref(false)
const messagesRef = ref<HTMLElement | null>(null)
const composerRef = ref<HTMLElement | null>(null)
const chatPanelRef = ref<HTMLElement | null>(null)
const heroLogoFieldRef = ref<HTMLElement | null>(null)
const heroLogoTurbulenceRef = ref<SVGFETurbulenceElement | null>(null)
const heroLogoDisplacementRef = ref<SVGFEDisplacementMapElement | null>(null)
const heroLogoPressed = ref(false)
const teacherUploadInputRef = ref<HTMLInputElement | null>(null)
const showAssistTools = ref(false)
const isNearBottom = ref(true)
const pendingMessageCount = ref(0)
const federatedOptimizing = ref(false)
const activeLawyerResultPanels = ref<string[]>([])
const activeTeacherResultPanels = ref<string[]>([])
const activeProgrammerResultPanels = ref<string[]>([])
const activeWriterResultPanels = ref<string[]>([])
const ASSIST_TOOL_VISIBLE_KEY = 'chat.composer_templates_visible'
const AGENT_PANEL_COLLAPSED_KEY = 'chat.agent_panel_collapsed'
const LAWYER_WORKFLOW_PROGRESS_COLLAPSED_KEY = 'chat.lawyer_workflow_progress_collapsed'
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
const lawyerWorkflowProgressCollapsed = ref(
  localStorage.getItem(LAWYER_WORKFLOW_PROGRESS_COLLAPSED_KEY) === '1'
)
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
      && isLawyerMode.value
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

const roles = computed(() => roleStore.roles)
const currentRole = computed(() => roleStore.currentRole)
const inferredWorkflowRoleId = computed<RoleId | null>(() => {
  const workflowId = (activeWorkflowRun.value?.workflowId || '').toLowerCase()
  const domain = (activeWorkflowRun.value?.domain || '').toLowerCase()
  if (domain === 'legal' || workflowId.includes('legal') || workflowId.includes('lawyer')) return 'lawyer'
  if (domain === 'education' || workflowId.includes('education') || workflowId.includes('teacher')) return 'teacher'
  if (domain === 'programming' || workflowId.includes('programmer') || workflowId.includes('code')) return 'programmer'
  if (domain === 'writing' || workflowId.includes('writer') || workflowId.includes('writing')) return 'writer'
  return null
})

const isLawyerMode = computed(() => {
  const name = (currentRole.value?.name || '').toLowerCase()
  return name.includes('律师') || name.includes('lawyer') || name.includes('法律')
    || (!currentRole.value && inferredWorkflowRoleId.value === 'lawyer')
})

const showLawyerHistoryFeedback = computed(() => inferredWorkflowRoleId.value === 'lawyer')

const isTeacherMode = computed(() => {
  const name = (currentRole.value?.name || '').toLowerCase()
  return name.includes('教师') || name.includes('teacher') || name.includes('教学')
    || (!currentRole.value && inferredWorkflowRoleId.value === 'teacher')
})

const isProgrammerMode = computed(() => {
  const name = (currentRole.value?.name || '').toLowerCase()
  return name.includes('程序') || name.includes('programmer') || name.includes('开发')
    || (!currentRole.value && inferredWorkflowRoleId.value === 'programmer')
})

const isWriterMode = computed(() => {
  const name = (currentRole.value?.name || '').toLowerCase()
  return name.includes('作家') || name.includes('writer') || name.includes('写作')
    || (!currentRole.value && inferredWorkflowRoleId.value === 'writer')
})

const isAgentMode = computed(() => workspaceMode.value === 'agent')
const isGeneralAgentMode = computed(() => isAgentMode.value
  && !isLawyerMode.value
  && !isTeacherMode.value
  && !isProgrammerMode.value
  && !isWriterMode.value)

const chatMainClass = computed(() => {
  if (isLawyerMode.value) return 'lawyer'
  if (isTeacherMode.value) return 'teacher'
  if (isProgrammerMode.value) return 'programmer'
  if (isWriterMode.value) return 'writer'
  return ''
})

const agentIcon = computed(() => {
  if (isLawyerMode.value) return ScaleToOriginal
  if (isTeacherMode.value) return School
  if (isProgrammerMode.value) return Cpu
  if (isWriterMode.value) return EditPen
  return Cpu
})

const heroGreeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 5) return '夜深了，把任务交给 Agent 值守吧'
  if (hour < 9) return '早上好呀，新的一天开始啦'
  if (hour < 12) return '上午好，把想法交给 Agent 去执行'
  if (hour < 14) return '中午好，休息之余也可以派个任务'
  if (hour < 18) return '下午好，继续推进手头的事'
  return '晚上好，适合深度工作的时段'
})

const composerModeLabel = computed(() => {
  if (currentRole.value?.name) return `${currentRole.value.name} 模式`
  if (isLawyerMode.value) return '律师模式'
  if (isTeacherMode.value) return '教师模式'
  if (isProgrammerMode.value) return '程序员模式'
  if (isWriterMode.value) return '作家模式'
  return isAgentMode.value ? '通用 Agent' : '通用 Chat'
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

const latestLawyerMessage = computed(() => {
  return [...chatStore.messages]
    .reverse()
    .find(msg => msg.role === 'assistant' && msg.agentMode === 'lawyer')
})

const latestTeacherMessage = computed(() => {
  return [...chatStore.messages]
    .reverse()
    .find(msg => msg.role === 'assistant' && msg.agentMode === 'teacher')
})

const latestProgrammerMessage = computed(() => {
  return [...chatStore.messages]
    .reverse()
    .find(msg => msg.role === 'assistant' && msg.agentMode === 'programmer')
})

const latestWriterMessage = computed(() => {
  return [...chatStore.messages]
    .reverse()
    .find(msg => msg.role === 'assistant' && msg.agentMode === 'writer')
})

const activeContractReviewArtifacts = computed(() => extractContractReviewArtifacts(workflowHistoryStepOutputs.value))
const workflowHistoryMessageTime = computed(() => {
  const raw = activeWorkflowRun.value?.updatedAt || activeWorkflowRun.value?.createdAt
  const value = raw ? new Date(raw) : new Date()
  return Number.isNaN(value.getTime()) ? new Date() : value
})
const lawyerHistoryReply = computed(() => {
  const report = historyText(activeContractReviewArtifacts.value.reportMarkdown)
    || historyText(workflowHistoryFinalArtifacts.value.find(item => historyText(item.content))?.content)
    || historyText(workflowHistoryFinalReport.value)
  if (report) return report

  const { risks, evidences, revisionSuggestions } = activeContractReviewArtifacts.value
  const lines = ['# 合同审查意见']
  if (risks.length) {
    lines.push('', '## 风险识别')
    risks.forEach((risk, index) => {
      const level = ({ high: '高风险', medium: '中风险', low: '低风险' } as Record<string, string>)[
        String(risk.level || '').toLowerCase()
      ] || '未分级'
      lines.push('', `${index + 1}. **${level}｜${historyText(risk.title) || historyText(risk.id) || '合同风险'}**`)
      if (historyText(risk.reason)) lines.push(`   - 原因：${historyText(risk.reason)}`)
      if (historyText(risk.consequence)) lines.push(`   - 影响：${historyText(risk.consequence)}`)
      if (historyText(risk.suggestion)) lines.push(`   - 建议：${historyText(risk.suggestion)}`)
    })
  }
  if (evidences.length) {
    lines.push('', '## 法律依据')
    evidences.forEach(item => {
      const source = historyText(item.sourceName) || historyText(item.title) || historyText(item.sourceType) || '依据'
      const content = historyText(item.citationText) || historyText(item.content)
      lines.push(`- **${source}**${content ? `：${content}` : ''}`)
    })
  }
  if (revisionSuggestions.length) {
    lines.push('', '## 修改建议')
    revisionSuggestions.forEach(item => {
      const suggestion = typeof item === 'string'
        ? item
        : historyText(item.suggestion) || historyText(item.content) || historyText(item.description)
      if (suggestion) lines.push(`- ${suggestion}`)
    })
  }
  if (lines.length === 1) lines.push('', '律师审查任务已完成，暂未保存可展示的报告正文。')
  return lines.join('\n')
})
const activeLawyerWorkflowSteps = computed(() => (activeWorkflowRun.value?.steps || [])
  .filter(step => ['completed', 'waiting_review', 'running'].includes(step.status)))
const activeLawyerWorkflowRiskLevel = computed(() => {
  const levels = activeContractReviewArtifacts.value.risks.map(item => (item.level || '').toLowerCase())
  if (levels.includes('high')) return 'high'
  if (levels.includes('medium')) return 'medium'
  if (levels.includes('low')) return 'low'
  return ''
})

const latestLawyerMeta = computed(() => {
  const lastAssistant = latestLawyerMessage.value
  const fallbackSteps = activeLawyerWorkflowSteps.value
  const hasCurrentRunSteps = fallbackSteps.length > 0
  return {
    // The active Run is the source of truth while it is available. A chat
    // message can be written before late runtime nodes, such as report generation,
    // have completed.
    skillsUsed: hasCurrentRunSteps
      ? fallbackSteps.map(step => step.stepId)
      : lastAssistant?.skillsUsed || [],
    trace: hasCurrentRunSteps
      ? fallbackSteps.map((step, index) => ({
        step: index + 1,
        thought: step.agentName || step.stepId,
        action: step.stepId,
        observation: step.status
      }))
      : lastAssistant?.trace || [],
    federated: lastAssistant?.federated || {},
    riskLevel: lastAssistant?.riskLevel || activeLawyerWorkflowRiskLevel.value
  }
})

const latestTeacherMeta = computed(() => {
  const lastAssistant = latestTeacherMessage.value
  return {
    skillsUsed: lastAssistant?.skillsUsed || [],
    trace: lastAssistant?.trace || [],
    federated: lastAssistant?.federated || {}
  }
})

const latestProgrammerMeta = computed(() => {
  const lastAssistant = latestProgrammerMessage.value
  return {
    skillsUsed: lastAssistant?.skillsUsed || [],
    trace: lastAssistant?.trace || [],
    federated: lastAssistant?.federated || {}
  }
})

const latestWriterMeta = computed(() => {
  const lastAssistant = latestWriterMessage.value
  return {
    skillsUsed: lastAssistant?.skillsUsed || [],
    trace: lastAssistant?.trace || [],
    federated: lastAssistant?.federated || {}
  }
})

const latestLawyerSkillResults = computed(() => {
  const lastAssistant = latestLawyerMessage.value
  return {
    evidenceAnalysis: lastAssistant?.evidenceAnalysis,
    limitationCalc: lastAssistant?.limitationCalc,
    jurisdiction: lastAssistant?.jurisdiction,
    hearingOutline: lastAssistant?.hearingOutline
  }
})

const latestTeacherSkillResults = computed(() => {
  const lastAssistant = latestTeacherMessage.value
  return {
    studentDiagnosis: lastAssistant?.studentDiagnosis,
    lessonPlan: lastAssistant?.lessonPlan,
    homeworkGrading: lastAssistant?.homeworkGrading,
    errorQuestionPush: lastAssistant?.errorQuestionPush
  }
})

const latestProgrammerSkillResults = computed(() => {
  const lastAssistant = latestProgrammerMessage.value
  const searchPayload = lastAssistant?.codebaseSemanticSearch
  const codeGenerationPayload = lastAssistant?.codeGeneration
  const diagramPayload = lastAssistant?.diagramGeneration
  const generationMermaidCode = codeGenerationPayload?.mermaid_code
  const diagramMermaidCode = diagramPayload?.mermaid_code
  const searchHits = Array.isArray(searchPayload?.hits) ? searchPayload?.hits : []
  const suggestedTests = Array.isArray(codeGenerationPayload?.suggested_tests) ? codeGenerationPayload?.suggested_tests : []

  const diagramData = diagramPayload?.mermaid_code
    ? diagramPayload
    : (generationMermaidCode
      ? {
        title: 'Generated Diagram',
        diagram_type: 'flowchart',
        mermaid_code: generationMermaidCode
      }
      : undefined)

  return {
    requirementAnalysis: lastAssistant?.requirementAnalysis,
    codebaseSemanticSearch: searchPayload,
    codeGeneration: codeGenerationPayload,
    diagramGeneration: diagramPayload,
    generatedCode: codeGenerationPayload?.code || '',
    suggestedTests,
    searchHits,
    diagramData,
    diagramCode: diagramMermaidCode || generationMermaidCode || ''
  }
})

const latestWriterSkillResults = computed(() => {
  const lastAssistant = latestWriterMessage.value
  return {
    creativeTree: lastAssistant?.inspirationExpand?.creative_tree || lastAssistant?.inspirationExpand?.creativeTree,
    outlineMarkdown: lastAssistant?.outlineGenerate?.outline_markdown || lastAssistant?.outlineGenerate?.outlineMarkdown,
    content: lastAssistant?.contentWrite?.content,
    characterRelationMap: lastAssistant?.characterRelationMap
  }
})

const availableLawyerResultPanels = computed(() => {
  const skillSet = new Set(latestLawyerMeta.value.skillsUsed || [])
  const panels: string[] = []
  if (latestLawyerSkillResults.value.evidenceAnalysis || skillSet.has('evidence_analysis')) panels.push('evidence')
  if (latestLawyerSkillResults.value.limitationCalc || skillSet.has('limitation_calculation')) panels.push('limitation')
  if (latestLawyerSkillResults.value.jurisdiction || skillSet.has('jurisdiction_determination')) panels.push('jurisdiction')
  if (latestLawyerSkillResults.value.hearingOutline || skillSet.has('hearing_outline_generation')) panels.push('hearing')
  if (activeContractReviewArtifacts.value.risks.length || skillSet.has('risk_detect')) panels.push('contractRisks')
  if (activeContractReviewArtifacts.value.evidences.length || skillSet.has('legal_evidence_match')) panels.push('contractEvidence')
  if (activeContractReviewArtifacts.value.reportMarkdown || skillSet.has('report_generate')) panels.push('contractReport')
  return panels
})

const availableTeacherResultPanels = computed(() => {
  const skillSet = new Set(latestTeacherMeta.value.skillsUsed || [])
  const panels: string[] = []
  if (latestTeacherSkillResults.value.studentDiagnosis || skillSet.has('student_diagnosis')) panels.push('diagnosis')
  if (latestTeacherSkillResults.value.lessonPlan || skillSet.has('lesson_plan_generation') || skillSet.has('lesson_plan')) panels.push('lessonPlan')
  if (latestTeacherSkillResults.value.homeworkGrading || skillSet.has('homework_grading') || skillSet.has('grading')) panels.push('grading')
  if (latestTeacherSkillResults.value.errorQuestionPush || skillSet.has('error_analysis_question_push') || skillSet.has('error_attribution')) panels.push('questionPush')
  return panels
})

const availableProgrammerResultPanels = computed(() => {
  const skillSet = new Set(latestProgrammerMeta.value.skillsUsed || [])
  const panels: string[] = []
  if (latestProgrammerSkillResults.value.requirementAnalysis || skillSet.has('requirement_analysis')) panels.push('requirement')
  if (latestProgrammerSkillResults.value.searchHits.length || skillSet.has('codebase_semantic_search')) panels.push('search')
  if (latestProgrammerSkillResults.value.generatedCode || skillSet.has('code_generation')) panels.push('code')
  if (latestProgrammerSkillResults.value.diagramCode || skillSet.has('diagram_generation')) panels.push('diagram')
  return panels
})

const availableWriterResultPanels = computed(() => {
  const skillSet = new Set(latestWriterMeta.value.skillsUsed || [])
  const panels: string[] = []
  if (latestWriterSkillResults.value.creativeTree || skillSet.has('inspiration_expand')) panels.push('inspiration')
  if (latestWriterSkillResults.value.outlineMarkdown || skillSet.has('outline_generate')) panels.push('outline')
  if (latestWriterSkillResults.value.content || skillSet.has('content_write')) panels.push('content')
  if (latestWriterSkillResults.value.characterRelationMap || skillSet.has('character_relation_map')) panels.push('relation')
  return panels
})

// 右侧工作台：仅当当前模式有技能调用结果时才显示
const hasAgentResults = computed(() => {
  if (isLawyerMode.value) return availableLawyerResultPanels.value.length > 0
  if (isTeacherMode.value) return availableTeacherResultPanels.value.length > 0
  if (isProgrammerMode.value) return availableProgrammerResultPanels.value.length > 0
  if (isWriterMode.value) return availableWriterResultPanels.value.length > 0
  return false
})

const hasAgentActivity = computed(() => {
  if (isGeneralAgentMode.value && hasActiveWorkflow.value) return true
  if (hasAgentResults.value) return true
  if (isLawyerMode.value) return latestLawyerMeta.value.skillsUsed.length > 0 || latestLawyerMeta.value.trace.length > 0
  if (isTeacherMode.value) return latestTeacherMeta.value.skillsUsed.length > 0 || latestTeacherMeta.value.trace.length > 0
  if (isProgrammerMode.value) return latestProgrammerMeta.value.skillsUsed.length > 0 || latestProgrammerMeta.value.trace.length > 0
  if (isWriterMode.value) return latestWriterMeta.value.skillsUsed.length > 0 || latestWriterMeta.value.trace.length > 0
  return false
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

const currentTemplates = computed(() => {
  const roleName = currentRole.value?.name || ''
  const lower = roleName.toLowerCase()

  if (roleName.includes('律师') || lower.includes('lawyer')) {
    return ['合同纠纷咨询', '劳动仲裁流程', '法律风险评估', '文书草稿生成']
  }
  if (roleName.includes('教师') || lower.includes('teacher')) {
    return ['制定学习计划', '错题归因推题', '生成课堂互动脚本', '学情报告总结']
  }
  if (roleName.includes('程序') || lower.includes('developer') || lower.includes('programmer')) {
    return ['帮我做需求技术规格分析', '检索代码库中登录相关函数', '根据规格生成后端接口代码', '生成用户登录流程 Mermaid 图']
  }
  if (roleName.includes('作家') || lower.includes('writer')) {
    return ['灵感拓展并生成创意树', '生成章节大纲思维导图', '按鲁迅体写第一章', '分析角色并生成人物关系图']
  }
  return ['日常问答', '帮我做个计划', '总结这段内容', '给我几个建议']
})

const getLawyerRole = () => {
  return roles.value.find(role => {
    const roleName = (role.name || '').toLowerCase()
    return roleName.includes('律师') || roleName.includes('法律') || roleName.includes('lawyer')
  })
}

const getTeacherRole = () => {
  return roles.value.find(role => {
    const roleName = (role.name || '').toLowerCase()
    return roleName.includes('教师') || roleName.includes('教学') || roleName.includes('teacher')
  })
}

const getProgrammerRole = () => {
  return roles.value.find(role => {
    const roleName = (role.name || '').toLowerCase()
    return roleName.includes('程序') || roleName.includes('开发') || roleName.includes('programmer')
  })
}

const getWriterRole = () => {
  return roles.value.find(role => {
    const roleName = (role.name || '').toLowerCase()
    return roleName.includes('作家') || roleName.includes('写作') || roleName.includes('writer')
  })
}

const switchRoleWithoutReset = async (role: any) => {
  selectedRoleId.value = role.id
  await roleStore.setCurrentRole(role)
  chatStore.setRole(role.id)
}

const activateLawyerAgent = async () => {
  if (isLawyerMode.value) {
    ElMessage.info('当前已在律师模式')
    return
  }

  const lawyerRole = getLawyerRole()
  if (!lawyerRole) {
    ElMessage.warning('未找到律师角色，请先在角色管理中启用律师角色')
    showRoleDrawer.value = true
    return
  }
  await switchRoleWithoutReset(lawyerRole)
  ElMessage.success('已切换到律师 Agent')
}

const activateTeacherAgent = async () => {
  if (isTeacherMode.value) {
    ElMessage.info('当前已在教师模式')
    return
  }

  const teacherRole = getTeacherRole()
  if (!teacherRole) {
    ElMessage.warning('未找到教师角色，请先在角色管理中启用教师角色')
    showRoleDrawer.value = true
    return
  }
  await switchRoleWithoutReset(teacherRole)
  ElMessage.success('已切换到教师 Agent')
}

const activateProgrammerAgent = async () => {
  if (isProgrammerMode.value) {
    ElMessage.info('当前已在程序员模式')
    return
  }

  const programmerRole = getProgrammerRole()
  if (!programmerRole) {
    ElMessage.warning('未找到程序员角色，请先在角色管理中启用程序员角色')
    showRoleDrawer.value = true
    return
  }
  await switchRoleWithoutReset(programmerRole)
  ElMessage.success('已切换到程序员 Agent')
}

const activateWriterAgent = async () => {
  if (isWriterMode.value) {
    ElMessage.info('当前已在作家模式')
    return
  }

  const writerRole = getWriterRole()
  if (!writerRole) {
    ElMessage.warning('未找到作家角色，请先在角色管理中启用作家角色')
    showRoleDrawer.value = true
    return
  }
  await switchRoleWithoutReset(writerRole)
  ElMessage.success('已切换到作家 Agent')
}

const toggleLawyerMode = async () => {
  if (isLawyerMode.value) {
    ElMessage.info('当前已在律师模式')
    return
  }
  await activateLawyerAgent()
}

const toggleTeacherMode = async () => {
  if (isTeacherMode.value) {
    ElMessage.info('当前已在教师模式')
    return
  }
  await activateTeacherAgent()
}

const toggleProgrammerMode = async () => {
  if (isProgrammerMode.value) {
    ElMessage.info('当前已在程序员模式')
    return
  }
  await activateProgrammerAgent()
}

const toggleWriterMode = async () => {
  if (isWriterMode.value) {
    ElMessage.info('当前已在作家模式')
    return
  }
  await activateWriterAgent()
}

const openFederatedConsole = () => {
  router.push('/agentos/resources?tab=federated')
}

const handleFederatedOptimize = async () => {
  if (federatedOptimizing.value) return
  federatedOptimizing.value = true
  try {
    const result = await federatedModelApi.optimizeModel('advanced', 'federated', 'quality', 1)
    if (result?.success) {
      ElMessage.success('联邦优化已触发')
      return
    }
    ElMessage.warning('联邦优化请求未成功')
  } catch (error: any) {
    ElMessage.error(error?.message || '联邦优化触发失败')
  } finally {
    federatedOptimizing.value = false
  }
}

const toggleAssistTools = () => {
  showAssistTools.value = !showAssistTools.value
}

const useTemplate = (text: string) => {
  if (!text) return
  inputText.value = text
  nextTick(() => {
    const textarea = document.querySelector('.composer textarea') as HTMLTextAreaElement | null
    if (textarea) {
      textarea.focus()
      textarea.setSelectionRange(text.length, text.length)
    }
  })
}

const autoSegment = () => {
  if (inputText.value.length <= 500) return
  const segments = inputText.value.match(/.{1,500}/g) || []
  inputText.value = segments.join('\n\n---\n\n')
  ElMessage.success(t('chat.autoSegment'))
}

const hasCurrentWorkspaceContext = () => Boolean(
  chatStore.messages.length
  || activeWorkflowRunId.value
  || chatStore.contextId
  || (typeof route.query.contextId === 'string' && route.query.contextId.trim())
)

const resetWorkspaceForRoleSwitch = async () => {
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
  void resetWorkspaceForRoleSwitch()
}

const prepareRoleSwitch = async (targetLabel: string): Promise<boolean> => {
  if (!hasCurrentWorkspaceContext()) return true
  const createLabel = isAgentMode.value ? '新建一个 Agent 任务' : '新建一段对话'
  const currentLabel = isAgentMode.value ? '当前 Agent 任务' : '当前对话'
  try {
    await ElMessageBox.confirm(
      `切换到${targetLabel}将${createLabel}；${currentLabel}会保留在记录中。是否继续？`,
      '切换角色与模板',
      {
        confirmButtonText: '新建并切换',
        cancelButtonText: '留在当前任务',
        type: 'warning'
      }
    )
    await resetWorkspaceForRoleSwitch()
    return true
  } catch {
    return false
  }
}

const selectRole = async (role: any): Promise<boolean> => {
  if (role.id === currentRole.value?.id) {
    showRoleDrawer.value = false
    return true
  }
  if (!await prepareRoleSwitch(`角色“${role.name}”`)) return false

  selectedRoleId.value = role.id
  await roleStore.setCurrentRole(role)
  chatStore.setRole(role.id)
  showRoleDrawer.value = false
  ElMessage.success(`已切换到角色: ${role.name}`)
  return true
}

const selectGeneralMode = async (): Promise<boolean> => {
  if (!currentRole.value && !selectedRoleId.value) {
    showRoleDrawer.value = false
    return true
  }
  if (!await prepareRoleSwitch('通用模式')) return false

  selectedRoleId.value = null
  roleStore.clearCurrentRole()
  chatStore.setRole(null)
  selectedChatTemplateKey.value = 'general-auto'
  localStorage.setItem(CHAT_TEMPLATE_KEY, 'general-auto')
  showRoleDrawer.value = false
  ElMessage.success('已切换到通用模式')
  return true
}

const roleNameAliases: Record<RoleId, string[]> = {
  lawyer: ['律师', '法律', 'lawyer'],
  teacher: ['教师', '教学', 'teacher'],
  programmer: ['程序', '开发', 'programmer', 'developer'],
  writer: ['作家', '写作', 'writer']
}

const openRoleTemplateDialog = () => {
  roleTemplateDialogOpen.value = true
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

const findRuntimeRole = (roleId: RoleId) => {
  const aliases = roleNameAliases[roleId]
  return roles.value.find(role => {
    const name = (role.name || '').toLowerCase()
    return aliases.some(alias => name.includes(alias))
  })
}

const applyRoleTemplateSelection = async (selection: { roleId: RoleId | 'general'; templateKey: string }) => {
  const templateChanged = selection.templateKey !== selectedChatTemplateKey.value
  if (selection.roleId === 'general') {
    roleTemplateDialogOpen.value = false
    const alreadyGeneral = !currentRole.value && !selectedRoleId.value
    const switched = alreadyGeneral && templateChanged
      ? await prepareRoleSwitch('通用模式的新模板')
      : await selectGeneralMode()
    if (switched) {
      selectedChatTemplateKey.value = selection.templateKey
      localStorage.setItem(CHAT_TEMPLATE_KEY, selection.templateKey)
    }
    return
  }

  const targetRole = findRuntimeRole(selection.roleId)
  const template = roleTemplateGroups
    .find(role => role.id === selection.roleId)
    ?.templates.find(item => item.key === selection.templateKey)

  if (!targetRole) {
    ElMessage.warning('该角色尚未启用，请先在角色管理中启用后再切换')
    return
  }

  roleTemplateDialogOpen.value = false
  if (targetRole.id !== currentRole.value?.id) {
    const switched = await selectRole(targetRole)
    if (!switched) return
  } else if (templateChanged) {
    const switched = await prepareRoleSwitch(`“${targetRole.name} / ${template?.name || '新模板'}”`)
    if (!switched) return
  } else {
    ElMessage.success(`已选择 ${targetRole.name}${template ? ` / ${template.name}` : ''}`)
  }

  selectedChatTemplateKey.value = selection.templateKey
  localStorage.setItem(CHAT_TEMPLATE_KEY, selection.templateKey)
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
  inputText.value = ''
  const composerStartRect = chatStore.messages.length === 0
    ? composerRef.value?.getBoundingClientRect()
    : undefined

  try {
    let response: any
    if (isLawyerMode.value) {
      response = await chatStore.sendLawyerMessage(userText)
    } else if (isTeacherMode.value) {
      response = await chatStore.sendTeacherMessage(userText)
    } else if (isProgrammerMode.value) {
      response = await chatStore.sendProgrammerMessage(userText)
    } else if (isWriterMode.value) {
      response = await chatStore.sendWriterMessage(userText)
    } else {
      loading.value = false
      inputText.value = userText
      await upgradeChatToWorkflow()
      return
    }

    if (composerStartRect) await animateComposerToConversation(composerStartRect)
    const acgTaskId = response?.acgTaskId || response?.workflowRunId
    if (acgTaskId) {
      const binding = chatStore.getLatestWorkflowBinding(currentConversationId.value)
      await activateWorkflowRun(
        acgTaskId,
        binding?.runId === acgTaskId ? binding : null,
        false
      )
      ElMessage.success(`专业任务已进入 ACG：${acgTaskId}`)
    }
    scrollToBottom()
  } catch (error: any) {
    inputText.value = userText
    if (!wasErrorUserNotified(error)) ElMessage.error(error?.message || '发送消息失败')
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
    const agentMode = isLawyerMode.value
      ? 'lawyer'
      : isTeacherMode.value
        ? 'teacher'
        : isProgrammerMode.value
          ? 'programmer'
          : isWriterMode.value
            ? 'writer'
            : 'default'
    const sendPromise = chatStore.sendMessageStream(userText, agentMode, loadModelSettings(), workspaceMode.value)
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
      domain: isLawyerMode.value ? 'legal' : 'general',
      intent: isLawyerMode.value ? 'case_analysis' : 'general',
      workflowId: isLawyerMode.value ? 'legal_case_analysis_v1' : undefined,
      reviewMode: isLawyerMode.value ? 'human_in_loop' : 'auto',
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

const openTeacherUploadDialog = () => {
  if (!teacherUploadInputRef.value) return
  teacherUploadInputRef.value.value = ''
  teacherUploadInputRef.value.click()
}

const handleTeacherFileUpload = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  loading.value = true
  try {
    // Reuse FileManager upload backend.
    await fileApi.uploadFile(file, 'teacher').catch(() => undefined)

    const ocr = await agentTeacherApi.extractOcrText(file)
    if (!ocr.text) {
      ElMessage.warning('未识别到文本，请更换更清晰的文件后重试')
      return
    }

    const injected = `\n\n[OCR识别文本 - ${file.name}]\n${ocr.text}`
    inputText.value = `${inputText.value}${injected}`.trim()
    ElMessage.success('OCR 识别完成，已注入输入框')
  } catch (error: any) {
    ElMessage.error(error.message || '上传或 OCR 处理失败')
  } finally {
    loading.value = false
  }
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

  if (isTeacherMode.value) {
    showFileManager.value = false
    ElMessage.info('教师模式建议使用“上传作业”按钮自动 OCR 注入文本')
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

watch(
  availableLawyerResultPanels,
  panels => {
    activeLawyerResultPanels.value = [...panels]
  },
  { immediate: true }
)

watch(
  availableTeacherResultPanels,
  panels => {
    activeTeacherResultPanels.value = [...panels]
  },
  { immediate: true }
)

watch(
  availableProgrammerResultPanels,
  panels => {
    activeProgrammerResultPanels.value = [...panels]
  },
  { immediate: true }
)

watch(
  availableWriterResultPanels,
  panels => {
    activeWriterResultPanels.value = [...panels]
  },
  { immediate: true }
)

const checkScrollState = () => {
  if (!messagesRef.value) return
  const { scrollTop, scrollHeight, clientHeight } = messagesRef.value
  const isAtBottom = Math.abs(scrollHeight - clientHeight - scrollTop) < 24
  isNearBottom.value = isAtBottom
  if (isAtBottom) pendingMessageCount.value = 0
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

watch(
  () => roleStore.currentRole,
  newRole => {
    selectedRoleId.value = newRole?.id || null
    chatStore.setRole(newRole?.id || null)
  },
  { immediate: true }
)

watch(showAssistTools, visible => {
  localStorage.setItem(ASSIST_TOOL_VISIBLE_KEY, visible ? '1' : '0')
})

watch(agentPanelCollapsed, collapsed => {
  localStorage.setItem(AGENT_PANEL_COLLAPSED_KEY, collapsed ? '1' : '0')
})

watch(lawyerWorkflowProgressCollapsed, collapsed => {
  localStorage.setItem(LAWYER_WORKFLOW_PROGRESS_COLLAPSED_KEY, collapsed ? '1' : '0')
})

const restoreWorkflowForConversation = async () => {
  const conversationId = currentConversationId.value
  const binding = chatStore.getActiveWorkflowBinding(conversationId)
    || chatStore.getLatestWorkflowBinding(conversationId)
  const routeRunId = typeof route.query.runId === 'string' ? route.query.runId.trim() : ''
  // A run selected from Agent history is explicit navigation state. It must win over
  // conversation-local bindings, especially while clearMessages() changes contextId.
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
  [isGeneralAgentMode, activeWorkflowRunId],
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
  await roleStore.loadRoles()
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

  const assistToolVisible = localStorage.getItem(ASSIST_TOOL_VISIBLE_KEY)
  if (assistToolVisible === '1') {
    showAssistTools.value = true
  }

  selectedRoleId.value = roleStore.currentRole?.id || null
  chatStore.setRole(roleStore.currentRole?.id || null)

  void chatStore.fetchContextWindows()

  bindMessagesScroll()
})

onUnmounted(() => {
  window.removeEventListener('workspace-mode-change', handleWorkspaceModeChange)
  window.removeEventListener('agent-new-task', handleNewAgentTask)
  window.removeEventListener('resize', handleWorkflowPanelViewportResize)
  window.removeEventListener('pointerdown', handleMissionOutsideClick)
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
  border-bottom: 1px solid var(--border-light);
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
  border-bottom: 1px solid var(--border-light);
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
  border-top: 1px solid var(--border-light);
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
  border-top: 1px solid var(--border-light);
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

.lawyer-history-conversation {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 26px;
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

.lawyer-workflow-progress {
  position: relative;
  min-width: 0;
}

.lawyer-workflow-progress :deep(.workflow-progress__header) {
  padding-right: 28px;
}

.lawyer-workflow-progress__toggle {
  position: absolute;
  z-index: 2;
  top: 6px;
  right: 7px;
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: color 160ms ease, background-color 160ms ease, transform 160ms ease;
}

.lawyer-workflow-progress__toggle:hover,
.lawyer-workflow-progress__toggle:focus-visible {
  background: var(--primary-fade);
  color: var(--primary-color);
  outline: none;
}

.lawyer-workflow-progress__toggle:active {
  transform: translateY(1px);
}

.lawyer-workflow-progress__collapsed-row {
  box-sizing: border-box;
  width: 100%;
  min-height: 36px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 7px 10px 7px 12px;
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: var(--bg-card);
  color: var(--text-secondary);
  font: inherit;
  cursor: pointer;
  transition: border-color 160ms ease, background-color 160ms ease;
}

.lawyer-workflow-progress__collapsed-row:hover,
.lawyer-workflow-progress__collapsed-row:focus-visible {
  border-color: var(--border-hover);
  background: color-mix(in srgb, var(--primary-fade) 34%, var(--bg-card));
  outline: none;
}

.lawyer-workflow-progress__identity,
.lawyer-workflow-progress__expand {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 7px;
  font-size: 11px;
}

.lawyer-workflow-progress__identity strong {
  color: var(--text-primary);
  font-size: 12px;
}

.lawyer-workflow-progress__dot {
  width: 7px;
  height: 7px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--primary-color);
  box-shadow: 0 0 0 3px var(--primary-fade);
}

.lawyer-workflow-progress.completed .lawyer-workflow-progress__dot {
  background: var(--success);
  box-shadow: 0 0 0 3px var(--success-fade);
}

.lawyer-workflow-progress.waiting_review .lawyer-workflow-progress__dot,
.lawyer-workflow-progress.retrying .lawyer-workflow-progress__dot {
  background: var(--warning);
  box-shadow: 0 0 0 3px var(--warning-fade);
}

.lawyer-workflow-progress.failed .lawyer-workflow-progress__dot,
.lawyer-workflow-progress.cancelled .lawyer-workflow-progress__dot {
  background: var(--danger);
  box-shadow: 0 0 0 3px var(--danger-fade);
}

.lawyer-workflow-progress__expand {
  flex: 0 0 auto;
  color: var(--primary-color);
  font-weight: 650;
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

.composer-agent-mode {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 28px;
  padding: 4px 8px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: color 160ms ease, background 160ms ease, border-color 160ms ease;
}

.composer-agent-mode:hover {
  border-color: color-mix(in srgb, var(--primary-color) 26%, var(--border-light));
  background: color-mix(in srgb, var(--primary-color) 9%, transparent);
}

.composer-agent-mode:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--primary-color) 58%, transparent);
  outline-offset: 2px;
}

.composer-agent-mode__chevron {
  font-size: 9px;
  color: var(--text-muted);
  opacity: 0.9;
}

.composer-agent-mode__icon {
  color: var(--text-muted);
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
  --agent-panel-accent: var(--primary-color);
  background: var(--bg-sidebar);
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 0;
  border: 0;
  border-left: 1px solid var(--border-light);
  border-radius: 0;
  transition: border-color 0.2s ease, background-color 0.2s ease;
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

.chat-main.lawyer .agent-panel {
  --agent-panel-accent: #496b8f;
  border-left-color: rgba(73, 107, 143, 0.22);
}

.chat-main.teacher .agent-panel {
  --agent-panel-accent: #3d7656;
  border-left-color: rgba(61, 118, 86, 0.22);
}

.chat-main.programmer .agent-panel {
  --agent-panel-accent: #6f668f;
  border-left-color: rgba(111, 102, 143, 0.22);
}

.chat-main.writer .agent-panel {
  --agent-panel-accent: #9a7432;
  border-left-color: rgba(154, 116, 50, 0.22);
}

.results-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  gap: 7px;
  padding: 52px 18px 24px;
  color: var(--text-secondary);
  font-size: 13px;
}

.results-empty .empty-icon {
  width: 34px;
  height: 34px;
  padding: 8px;
  border-radius: 9px;
  background: var(--bg-panel);
  color: var(--agent-panel-accent);
  font-size: 18px;
  opacity: 1;
}

.results-empty-hint {
  max-width: 230px;
  color: var(--text-disabled);
  font-size: 11px;
  line-height: 1.55;
  text-align: center;
  text-wrap: pretty;
}

.agent-panel-content :deep(.skill-panel) {
  height: 100%;
  border: 0;
  border-radius: 0;
  background: transparent;
}

.agent-panel-content :deep(.lawyer-panel),
.agent-panel-content :deep(.teacher-panel),
.agent-panel-content :deep(.programmer-panel),
.agent-panel-content :deep(.writer-panel) {
  border-top: 0;
}

.agent-panel-content :deep(.panel-header) {
  min-height: 64px;
  padding: 10px 46px 10px 14px;
  gap: 8px;
  background: transparent;
  border-bottom: 1px solid var(--border-light);
}

.agent-panel-content :deep(.header-left) {
  min-width: 0;
  gap: 9px;
}

.agent-panel-content :deep(.agent-avatar) {
  flex: 0 0 30px;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: var(--primary-fade);
  color: var(--agent-panel-accent);
  box-shadow: none;
  font-size: 15px;
}

.agent-panel-content :deep(.header-text) {
  min-width: 0;
  gap: 1px;
}

.agent-panel-content :deep(.panel-header h3) {
  overflow: hidden;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-panel-content :deep(.header-sub) {
  overflow: hidden;
  color: var(--text-disabled);
  font-size: 10px;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-panel-content :deep(.header-badges) {
  flex: 0 0 auto;
}

.agent-panel-content :deep(.skill-pill),
.agent-panel-content :deep(.risk-pill) {
  padding: 3px 7px;
  border: 0;
  background: var(--bg-panel);
  color: var(--text-secondary);
  font-size: 10px;
  box-shadow: none;
}

.agent-panel-content :deep(.pill-dot) {
  width: 5px;
  height: 5px;
  background: var(--agent-panel-accent);
  animation: none;
}

.agent-panel-content :deep(.panel-tabs) {
  height: 32px;
  min-height: 32px;
  padding: 0 8px;
  background: transparent;
  border-bottom: 1px solid var(--border-light);
}

.agent-panel-content :deep(.tab-btn) {
  gap: 4px;
  height: 32px !important;
  min-height: 32px !important;
  max-height: 32px !important;
  box-sizing: border-box;
  padding: 0 6px !important;
  border-bottom-width: 1px;
  background: transparent;
  color: var(--text-disabled);
  font-size: 10px;
  font-weight: 600;
}

.agent-panel-content :deep(.tab-btn:hover) {
  background: transparent;
  color: var(--text-primary);
}

.agent-panel-content :deep(.tab-btn.active) {
  background: transparent;
  color: var(--text-primary);
  border-bottom-color: var(--agent-panel-accent);
}

.agent-panel-content :deep(.tab-icon) {
  display: none;
}

.agent-panel-content :deep(.tab-badge),
.agent-panel-content :deep(.tab-btn.active .tab-badge) {
  min-width: 13px;
  height: 13px;
  padding: 0 3px;
  line-height: 13px;
  background: var(--bg-panel);
  color: var(--text-secondary);
  font-size: 8px;
}

.agent-panel-content :deep(.empty) {
  justify-content: flex-start;
  min-height: 0;
  padding: 48px 18px 24px;
  color: var(--text-secondary);
}

.agent-panel-content :deep(.empty-illustration) {
  width: 34px;
  height: 34px;
  border: 0;
  border-radius: 9px;
  background: var(--bg-panel);
  color: var(--agent-panel-accent);
  box-shadow: none;
  font-size: 18px;
}

.agent-panel-content :deep(.empty-hint) {
  max-width: 230px;
  color: var(--text-disabled);
  font-size: 11px;
  line-height: 1.55;
  text-wrap: pretty;
}

.writer-content-preview {
  border: 1px solid rgba(154, 116, 50, 0.18);
  background: rgba(154, 116, 50, 0.05);
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.6;
  color: #67491c;
  white-space: pre-wrap;
}

.programmer-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.programmer-grid {
  display: grid;
  gap: 10px;
}

.programmer-grid.two-cols {
  grid-template-columns: 1fr 1fr;
}

.programmer-card {
  border: 1px solid rgba(111, 102, 143, 0.16);
  background: rgba(111, 102, 143, 0.05);
  border-radius: 8px;
  padding: 10px;
}

.programmer-card .card-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--accent-color);
  margin-bottom: 6px;
}

.programmer-card ul {
  margin: 0;
  padding-left: 16px;
  font-size: 13px;
  color: var(--text-regular);
  line-height: 1.5;
}

.programmer-meta {
  font-size: 12px;
  color: var(--text-regular);
}

.programmer-search-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.search-item {
  border: 1px solid var(--border-light);
  border-radius: 8px;
  background: var(--bg-card);
  padding: 8px 10px;
}

.search-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
  margin-bottom: 6px;
}

.search-head .path {
  font-size: 12px;
  font-weight: 600;
  color: var(--primary-color);
  word-break: break-all;
}

.search-head .score {
  font-size: 11px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.search-item pre,
.code-block {
  margin: 0;
  border-radius: 8px;
  background: #1f2428;
  color: #e8ece8;
  padding: 10px;
  font-size: 12px;
  line-height: 1.45;
  overflow: auto;
}

.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid var(--border-light);
}

.role-list {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.role-item {
  display: flex;
  align-items: center;
  gap: 10px;
  border: 1px solid var(--border-light);
  border-radius: 10px;
  padding: 10px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.role-item:hover {
  border-color: var(--primary-color);
  background: var(--primary-fade);
}

.role-item.active {
  border-color: var(--primary-color);
  background: var(--primary-fade);
}

.role-text .name {
  font-size: 14px;
  font-weight: 600;
}

.role-text .desc {
  font-size: 12px;
  color: var(--text-secondary);
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

  .programmer-grid.two-cols {
    grid-template-columns: 1fr;
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

.composer-agent-mode:hover {
  border-color: transparent;
  background: color-mix(in srgb, var(--primary-color) 9%, transparent);
}

.composer-agent-mode:hover,
.composer-agent-mode[aria-expanded='true'] {
  color: var(--text-primary);
}

.composer-agent-mode:hover .composer-agent-mode__icon,
.composer-agent-mode[aria-expanded='true'] .composer-agent-mode__icon {
  color: var(--primary-color);
}

.composer-agent-mode:hover .composer-agent-mode__chevron,
.composer-agent-mode[aria-expanded='true'] .composer-agent-mode__chevron {
  color: var(--text-secondary);
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
