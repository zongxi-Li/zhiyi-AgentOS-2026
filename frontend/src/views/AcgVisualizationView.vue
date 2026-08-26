<!-- 知弈OS 原生 ACG 工作台 — 专业语义通过编译期 Plugin UI Extension 增量注入。 -->
<template>
  <div class="acg-view ui-shell" :class="{ 'has-progress': isSubmitting || progressTracker.progress.value || progressTracker.syncError.value, 'has-run': !!activeRunId, 'is-draft': !activeRunId }">
    <header class="ui-hero ui-hero--compact">
      <div class="hero-left">
        <div class="ui-icon-badge"><el-icon><Cpu /></el-icon></div>
        <h3>ACG 动态群体智能引擎</h3>
      </div>
      <div class="hero-right">
        <span v-if="displayedMissionId" class="hero-run-chip" :title="`任务 ID: ${displayedMissionId}`">
          <span>任务 ID</span>
          <code>{{ displayedMissionId }}</code>
        </span>
        <button class="hero-operations" type="button" @click="openOperations">
          <el-icon><Monitor /></el-icon>
          <span>运维查看</span>
        </button>
      </div>
    </header>

    <!-- 控制台 -->
    <section class="ui-surface ui-surface--pad control-bar" :class="{ collapsed: inputPanelCompact, 'advanced-open': advancedSettingsExpanded }">
      <button
        class="input-panel-toggle"
        type="button"
        :title="inputPanelExpanded ? '收起任务配置' : '展开任务配置'"
        :aria-label="inputPanelExpanded ? '收起任务配置' : '展开任务配置'"
        :aria-expanded="inputPanelExpanded"
        @click="inputPanelExpanded = !inputPanelExpanded"
      >
        <el-icon><ArrowUp v-if="inputPanelExpanded" /><ArrowDown v-else /></el-icon>
      </button>
      <div v-if="inputPanelCompact" class="input-summary">
        <span class="input-summary__copy">
          <el-icon><Document /></el-icon>
          <strong>{{ taskName || '未命名 ACG 任务' }}</strong>
          <small>任务材料 · {{ taskMaterialLength.toLocaleString('zh-CN') }} 字｜{{ planningModeSummary }}｜{{ advancedSettingsSummary }}｜{{ activePluginSummary }}</small>
        </span>
      </div>
      <Transition
        :duration="380"
        @before-enter="beforeInputPanelEnter"
        @enter="enterInputPanel"
        @after-enter="afterInputPanelEnter"
        @before-leave="beforeInputPanelLeave"
        @leave="leaveInputPanel"
        @after-leave="afterInputPanelLeave"
      >
        <div v-show="inputPanelExpanded" class="input-panel-expandable">
      <div class="workbench-identity">
        <!-- <div><strong>知弈OS 原生任务工作台</strong><small>默认只使用 Native 能力；专业能力包按 Run 显式启用</small></div> -->
      </div>
      <div class="input-fields">
        <div class="input-pane contract-pane">
          <span class="pane-heading">任务材料</span>
          <div class="ctrl-row">
            <label class="ctrl-label">文本材料（可选）</label>
            <el-input class="contract-textarea" v-model="contractText" type="textarea" :autosize="{ minRows: 6, maxRows: 14 }" placeholder="粘贴需求、背景资料、研究材料或其他任务上下文" />
          </div>
          <div class="contract-upload" :class="{ dragging: uploadDragging, populated: selectedContractFile, loading: loading.upload }" @dragenter.prevent="uploadDragging = true" @dragover.prevent="uploadDragging = true" @dragleave.prevent="uploadDragging = false" @drop.prevent="handleContractDrop">
            <input ref="contractFileInput" class="contract-file-input" type="file" accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown" @change="handleContractFileSelection" />
            <span class="contract-upload__icon" aria-hidden="true"><el-icon><Document v-if="selectedContractFile" /><UploadFilled v-else /></el-icon></span>
            <span class="contract-upload__copy">
              <strong>{{ selectedContractFile?.originalFilename || (uploadState === 'parsing' ? '正在解析任务文件' : loading.upload ? '正在上传任务文件' : '补充任务文件') }}</strong>
              <small v-if="selectedContractFile">{{ formatFileSize(selectedContractFile.size) }} · 已提取 {{ selectedContractFile.textLength.toLocaleString('zh-CN') }} 字</small>
              <small v-if="uploadError" class="contract-upload__error">{{ uploadError }}</small>
              <small v-else-if="!selectedContractFile">拖放到此处，或选择 PDF、DOCX、TXT、MD，最大 10MB</small>
            </span>
            <span class="contract-upload__actions">
              <el-button size="small" :loading="loading.upload" @click="openContractFilePicker"><el-icon><UploadFilled /></el-icon>{{ selectedContractFile ? '替换文件' : '选择文件' }}</el-button>
              <el-button v-if="selectedContractFile" circle size="small" title="移除任务文件" aria-label="移除任务文件" @click="clearContractFile"><el-icon><Delete /></el-icon></el-button>
            </span>
          </div>
        </div>
        <div class="input-pane definition-pane">
          <span class="pane-heading">任务定义</span>
          <label class="ctrl-label">任务名称</label>
          <el-input v-model="taskName" placeholder="为本次任务命名" />
          <div class="ctrl-row">
            <label class="ctrl-label">任务目标</label>
            <el-input class="intent-textarea" v-model="userIntent" type="textarea" :autosize="{ minRows: 5, maxRows: 12 }" placeholder="描述目标、范围和成功标准" />
          </div>
          <label class="ctrl-label">执行约束</label>
          <el-input v-model="constraintsText" placeholder="使用逗号分隔，例如：两周内完成、控制预算" />
          <label class="ctrl-label">预期交付物</label>
          <el-input v-model="expectedArtifactsText" placeholder="使用逗号分隔，例如：实施方案、风险清单" />
        </div>
      </div>
      <section class="plugin-selector" aria-label="专业能力扩展">
        <header><div><strong>专业能力扩展</strong><small>Native Core 始终启用；每个 Run 最多叠加一个专业能力包</small></div></header>
        <div class="plugin-options">
          <button type="button" class="plugin-card native-card" :class="{ selected: !draft.enabledPluginIds.length }" :aria-pressed="!draft.enabledPluginIds.length" :disabled="scopeLocked" @click="clearPlugins">
            <span class="plugin-card__top"><strong>Native Core · 始终启用</strong><span class="plugin-card__state">{{ !draft.enabledPluginIds.length ? '已启用' : '基础' }}</span></span>
            <small>{{ draft.enabledPluginIds.length ? '作为专业能力包的运行基础' : '当前仅使用通用规划、分析与交付能力' }}</small>
            <code>不叠加专业能力包</code>
          </button>
          <button v-for="plugin in installedPlugins" :key="plugin.pluginId" type="button" class="plugin-card" :class="{ selected: draft.enabledPluginIds[0] === plugin.pluginId }" :aria-pressed="draft.enabledPluginIds[0] === plugin.pluginId" :disabled="scopeLocked || !plugin.available" @click="togglePlugin(plugin.pluginId)">
            <span class="plugin-card__top"><strong>{{ plugin.displayName }}</strong><span class="plugin-card__state">{{ draft.enabledPluginIds[0] === plugin.pluginId ? '已启用' : '选择' }}</span></span>
            <small>{{ plugin.description }}</small>
            <code>{{ plugin.pluginId }} · v{{ plugin.version }}</code>
          </button>
        </div>
      </section>
      <PluginExtensionHost :extensions="draftExtensions" :draft="draft" :readonly="scopeLocked" @update:plugin-data="draft.pluginData = $event" />
        </div>
      </Transition>
      <div class="ctrl-options">
        <div v-show="inputPanelExpanded" class="primary-options">
          <div class="primary-config">
            <span class="ctrl-label">规划方式</span>
            <div class="segmented-control" role="radiogroup" aria-label="规划方式">
              <button type="button" role="radio" class="segment-option" :aria-checked="planningMode === 'dynamic'" :class="{ selected: planningMode === 'dynamic' }" @click="planningMode = 'dynamic'">动态规划</button>
              <button type="button" role="radio" class="segment-option" :aria-checked="planningMode === 'template_preferred'" :class="{ selected: planningMode === 'template_preferred' }" @click="planningMode = 'template_preferred'">模板优先</button>
            </div>
          </div>
          <div class="primary-config">
            <span class="ctrl-label">审核方式</span>
            <div class="segmented-control" role="radiogroup" aria-label="审核方式">
              <button type="button" role="radio" class="segment-option" :aria-checked="draft.reviewMode === 'auto'" :class="{ selected: draft.reviewMode === 'auto' }" @click="draft.reviewMode = 'auto'">自动</button>
              <button type="button" role="radio" class="segment-option" :aria-checked="draft.reviewMode === 'human_in_loop'" :class="{ selected: draft.reviewMode === 'human_in_loop' }" @click="draft.reviewMode = 'human_in_loop'">人工介入</button>
            </div>
          </div>
          <div class="advanced-settings-popover">
            <button ref="advancedSettingsToggle" class="advanced-toggle" type="button" :aria-expanded="advancedSettingsExpanded" @click="toggleAdvancedSettings">
              <span class="advanced-toggle__copy"><strong>高级设置</strong><small>{{ advancedSettingsSummary }}</small></span>
              <el-icon><ArrowUp v-if="advancedSettingsExpanded" /><ArrowDown v-else /></el-icon>
            </button>
            <Teleport to="body">
            <div v-if="advancedSettingsExpanded" ref="advancedSettingsElement" class="advanced-settings" :style="{ left: `${advancedSettingsPosition.x}px`, top: `${advancedSettingsPosition.y}px` }">
              <header class="advanced-settings__head">
                <div>
                  <strong>高级运行策略</strong>
                  <small>仅在需要控制推理、规划或调试行为时调整</small>
                </div>
                <div class="advanced-settings__head-actions">
                  <span>{{ advancedSettingsSummary }}</span>
                  <button class="advanced-settings__close" type="button" title="关闭高级设置" aria-label="关闭高级设置" @click="closeAdvancedSettings">
                    <el-icon><Close /></el-icon>
                  </button>
                </div>
              </header>
              <section class="advanced-presets" aria-label="高级设置快速方案">
                <div class="advanced-presets__intro">
                  <strong>快速方案</strong>
                  <small>一键应用常用的运行组合</small>
                </div>
                <div class="advanced-presets__options">
                  <button type="button" class="advanced-preset" :class="{ selected: advancedPreset === 'fast' }" @click="applyAdvancedPreset('fast')">
                    <strong>快速</strong><small>低耗时 · 稳定规划</small>
                  </button>
                  <button type="button" class="advanced-preset" :class="{ selected: advancedPreset === 'balanced' }" @click="applyAdvancedPreset('balanced')">
                    <strong>均衡</strong><small>标准思考 · 联网检索</small>
                  </button>
                  <button type="button" class="advanced-preset" :class="{ selected: advancedPreset === 'deep' }" @click="applyAdvancedPreset('deep')">
                    <strong>深度</strong><small>深度思考 · 探索规划</small>
                  </button>
                </div>
              </section>
              <div class="advanced-item advanced-item--segmented">
                <div class="advanced-item__heading"><span>思考强度</span><small>影响耗时与推理深度</small></div>
                <div class="segmented-control" role="radiogroup" aria-label="思考强度">
                  <button type="button" role="radio" class="segment-option" :aria-checked="thinkingMode === 'disabled'" :class="{ selected: thinkingMode === 'disabled' }" @click="thinkingMode = 'disabled'">关闭</button>
                  <button type="button" role="radio" class="segment-option" :aria-checked="thinkingMode === 'standard'" :class="{ selected: thinkingMode === 'standard' }" @click="thinkingMode = 'standard'">标准</button>
                  <button type="button" role="radio" class="segment-option" :aria-checked="thinkingMode === 'deep'" :class="{ selected: thinkingMode === 'deep' }" @click="thinkingMode = 'deep'">深度</button>
                </div>
              </div>
              <div class="advanced-item advanced-item--switch">
                <div class="advanced-item__heading"><span>联网检索</span><small>优先补充公开网页信息</small></div>
                <button class="settings-switch" type="button" role="switch" :aria-checked="draft.webSearchEnabled" :disabled="isSubmitting" @click="draft.webSearchEnabled = !draft.webSearchEnabled">
                  <span class="settings-switch__track"><span></span></span>
                  <span>{{ draft.webSearchEnabled ? '开启' : '关闭' }}</span>
                </button>
              </div>
              <label class="advanced-item">
                <span class="advanced-item__label">图规划多样性</span>
                <el-select v-model="draft.planningDiversity" aria-label="图规划多样性">
                  <el-option label="稳定（可重复）" value="stable" />
                  <el-option label="均衡（推荐）" value="balanced" />
                  <el-option label="探索（变化更大）" value="exploratory" />
                </el-select>
              </label>
              <label class="advanced-item">
                <span class="advanced-item__label">随机种子（可选）</span>
                <el-input-number v-model="draft.planningSeed" :min="0" :max="2147483647" :controls="false" placeholder="留空则自动生成" />
              </label>
              <label v-if="activeRunId && draft.planningDiversity !== 'stable'" class="advanced-item">
                <span class="advanced-item__label">规划变体</span>
                <el-button @click="rerunWithNewPlanningSeed">换一种规划</el-button>
              </label>
              <div class="advanced-item advanced-item--switch">
                <div class="advanced-item__heading"><span>调试轨迹</span><small>记录更详细的执行诊断</small></div>
                <button class="settings-switch" type="button" role="switch" :aria-checked="debugTraceEnabled" @click="debugTraceEnabled = !debugTraceEnabled">
                  <span class="settings-switch__track"><span></span></span>
                  <span>{{ debugTraceEnabled ? '开启' : '关闭' }}</span>
                </button>
              </div>
              <div class="advanced-item advanced-item--switch">
                <div class="advanced-item__heading"><span>通信血缘</span><small>保留低熵通信的来源与去向记录</small></div>
                <button class="settings-switch" type="button" role="switch" :aria-checked="lowEntropyOptions.includes('trace_provenance')" @click="lowEntropyOptions = lowEntropyOptions.includes('trace_provenance') ? [] : ['trace_provenance']">
                  <span class="settings-switch__track"><span></span></span>
                  <span>{{ lowEntropyOptions.includes('trace_provenance') ? '记录' : '不记录' }}</span>
                </button>
              </div>
            </div>
            </Teleport>
          </div>
        </div>
        <el-button
          class="main-action"
          :class="`main-action--${mainAction.action}`"
          :type="mainAction.type"
          :loading="mainAction.loading"
          :disabled="mainAction.disabled"
          @click="handleMainAction"
        >
          <span class="main-action__label">{{ mainAction.label }}</span>
          <el-icon v-if="!mainAction.loading" class="main-action__arrow" aria-hidden="true"><ArrowRight /></el-icon>
        </el-button>
      </div>
    </section>

    <section
      v-if="activeRunId || isSubmitting || progressTracker.progress.value || progressTracker.syncError.value"
      class="run-overview ui-surface"
      aria-label="ACG 运行概览"
    >
    <section v-if="activeRunId" class="run-scope">
      <header><strong>运行状态来自执行运行时</strong><el-tag effect="plain" type="info">引用式只读</el-tag></header>
      <div class="snapshot-list">
        <span>{{ activePluginSummary }}</span>
        <code v-if="activeRun?.executionState?.checkpointId">Checkpoint {{ activeRun.executionState.checkpointId }}</code>
      </div>
    </section>

    <WorkflowProgressBar
      v-if="isSubmitting || progressTracker.progress.value || progressTracker.syncError.value"
      :progress="progressTracker.progress.value"
      :loading="isSubmitting || progressTracker.isLoading.value"
      :sync-error="progressTracker.syncError.value"
    />
    <AgentOsRunSummaryCard
      v-if="activeRunId"
      class="run-summary-card"
      :progress="progressTracker.progress.value"
      :run="activeRun"
      :view="acgView"
      :events="acgAuditEvents"
    />
    <RunResourceStrip
      v-if="activeRunId"
      :usage="resourceUsage"
      @open="openResourceInspector"
    />
    <AcgExecutionContractBar
      v-if="acgView"
      :view="acgView"
      @open-run="openRelatedRun"
    />
    </section>

    <el-drawer
      id="acg-resource-drawer"
      v-model="resourceDrawerOpen"
      class="resource-drawer"
      direction="rtl"
      size="520px"
      :with-header="true"
      :destroy-on-close="false"
      aria-label="资源详情"
    >
      <template #header>
        <div class="resource-drawer__header">
          <div>
            <strong>资源详情</strong>
            <span>当前 Run 的 API、用量与上下文观测</span>
          </div>
          <el-tag v-if="activeRun" effect="plain" type="info">{{ activeRun.status }}</el-tag>
        </div>
      </template>
      <div class="resource-drawer__body">
        <AcgResourceInspector
          v-if="activeRunId"
          :run-id="activeRunId"
          :usage="resourceUsage"
        />
      </div>
    </el-drawer>

    <p v-if="startError" class="run-error" role="alert">{{ startError }}</p>

    <WorkflowReviewPanel
      v-if="reviewPending"
      :run-id="activeRunId"
      :progress="progressTracker.progress.value"
      :run="activeRun"
      @reviewed="handleAcgReviewed"
      @conflict="handleAcgReviewConflict"
    />

    <!-- 主区：拓扑 + 指标/血缘 -->
    <div
      v-if="acgView"
      class="acg-grid"
      :class="{ 'is-side-collapsed': sidePanelCollapsed }"
    >
      <div class="grid-main">
        <AcgTopologyGraph
          :blueprint="acgView.acgBlueprint"
          :completed-step-ids="acgView.completedStepIds"
          :step-states="acgView.stepStates"
        />
        <template v-if="artifactRenderers.length">
          <component v-for="renderer in artifactRenderers" :key="renderer.pluginId" :is="renderer.component" :deliverables="acgView.deliverables" :final-report="acgView.finalReport" />
        </template>
        <GenericArtifactPanel
          v-else
          :step-outputs="acgView.stepOutputs || acgView.deliverables"
          :final-artifacts="acgView.finalArtifacts || []"
          :final-report="acgView.finalReport"
          :status="acgView.status"
        />
        <div class="schedule-strip ui-surface" v-if="scheduleBatches.length">
          <h4>就绪集调度轨迹（动态拓扑）</h4>
          <div class="batch-row">
            <div v-for="b in scheduleBatches" :key="b.id" class="batch">
              <span class="batch-idx">第{{ b.round }}轮</span>
              <span v-for="sid in b.nodes" :key="sid" class="batch-node">{{ sid }}</span>
            </div>
          </div>
        </div>
      </div>
      <aside v-if="sidePanelCollapsed" class="side-rail" aria-label="运行详情折叠栏">
        <button
          class="side-rail__toggle"
          type="button"
          title="展开运行详情"
          aria-label="展开运行详情"
          :aria-expanded="false"
          aria-controls="acg-run-details"
          @click="setSidePanelCollapsed(false)"
        >
          <el-icon><ArrowLeft /></el-icon>
        </button>
      </aside>
      <aside
        id="acg-run-details"
        class="grid-side"
        :aria-hidden="sidePanelCollapsed"
      >
        <div class="grid-side__content">
          <button
            class="grid-side__collapse"
            type="button"
            title="收起运行详情"
            aria-label="收起运行详情"
            :aria-expanded="true"
            aria-controls="acg-run-details"
            @click="setSidePanelCollapsed(true)"
          >
            <el-icon><ArrowRight /></el-icon>
            <span>收起运行详情</span>
          </button>
          <AcgOperationalInspector
            :view="acgView"
            :audit-events="acgAuditEvents"
            :patch-refs="activeRun?.executionState?.graphPatchRefs || []"
            @export-audit="exportAudit"
          />
          <section class="side-provenance ui-surface" aria-label="数据血缘与通信轨迹">
            <AcgProvenancePanel
              :consumptions="acgView.provenance.consumptions"
              :interactions="acgView.interactions"
              :recovery-trace="acgView.recoveryTrace"
              :contract-violations="acgView.contractViolations"
              @export-json="exportAudit('json')"
              @export-csv="exportAudit('csv')"
            />
          </section>
        </div>
      </aside>
    </div>

    <div v-else class="ui-surface task-brief">
      <strong>ACG 动态智能体长程任务</strong>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch, type DeepReadonly } from 'vue'
import axios from 'axios'
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Close, Cpu, Delete, Document, Monitor, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import {
  workflowApi,
  type AcgView,
  type WorkflowRun,
  type WorkflowProgress,
  type RunResourceUsage
} from '@/services/api/workflow'
import AcgTopologyGraph from '@/components/agentos/AcgTopologyGraph.vue'
import AcgExecutionContractBar from '@/components/agentos/AcgExecutionContractBar.vue'
import AcgOperationalInspector from '@/components/agentos/AcgOperationalInspector.vue'
import AcgProvenancePanel from '@/components/agentos/AcgProvenancePanel.vue'
import WorkflowProgressBar from '@/components/agentos/WorkflowProgressBar.vue'
import WorkflowReviewPanel from '@/components/agentos/WorkflowReviewPanel.vue'
import AgentOsRunSummaryCard from '@/components/agentos/AgentOsRunSummaryCard.vue'
import RunResourceStrip from '@/components/agentos/RunResourceStrip.vue'
import AcgResourceInspector from '@/components/agentos/AcgResourceInspector.vue'
import { useWorkflowProgress } from '@/composables/useWorkflowProgress'
import { useWorkflowRunsStore } from '@/stores/workflowRuns'
import type { ThinkingMode } from '@/config/modelSettings'
import { fileApi } from '@/services/api/file'
import { buildAcgAuditCsv, buildAcgAuditExport } from '@/utils/acgAuditExport'
import { isWorkflowReviewPending } from '@/utils/workflowReviewState'
import { resolveAcgTaskTitle, resolveAcgTaskTitleAutoUpdate } from '@/utils/acgTaskTitle'
import { notifyAcgRunInvalidated } from '@/utils/acgHistoryFilter'
import PluginExtensionHost from '@/features/acg/PluginExtensionHost.vue'
import GenericArtifactPanel from '@/features/acg/GenericArtifactPanel.vue'
import {
  buildWorkbenchStartRequest,
  createNativeWorkbenchDraft,
  restoreWorkbenchDraft,
  type WorkbenchDraft
} from '@/features/acg/workbench'
import { pluginUiExtensions } from '@/plugins'

const draft = reactive<WorkbenchDraft>(createNativeWorkbenchDraft())
const taskName = computed({ get: () => draft.title, set: value => { draft.title = value } })
const contractText = computed({ get: () => draft.materialText, set: value => { draft.materialText = value } })
const userIntent = computed({ get: () => draft.taskGoal, set: value => { draft.taskGoal = value } })
const planningMode = computed({ get: () => draft.planningMode, set: value => { draft.planningMode = value } })
const thinkingMode = computed<ThinkingMode>({ get: () => draft.thinkingMode, set: value => { draft.thinkingMode = value } })
const constraintsText = computed({
  get: () => draft.constraints.join('，'),
  set: value => { draft.constraints = value.split(/[,，\n]/).map(item => item.trim()).filter(Boolean) }
})
const expectedArtifactsText = computed({
  get: () => draft.expectedArtifacts.join('，'),
  set: value => { draft.expectedArtifacts = value.split(/[,，\n]/).map(item => item.trim()).filter(Boolean) }
})
const advancedSettingsExpanded = ref(false)
const advancedSettingsToggle = ref<HTMLButtonElement | null>(null)
const advancedSettingsElement = ref<HTMLElement | null>(null)
const advancedSettingsPosition = reactive({ x: 0, y: 0 })
const debugTraceEnabled = ref(false)
const lowEntropyOptions = ref(['trace_provenance'])
const autoGeneratedTaskName = ref('')

const positionAdvancedSettings = async () => {
  await nextTick()
  const trigger = advancedSettingsToggle.value
  const panel = advancedSettingsElement.value
  if (!trigger || !panel) return
  const rect = trigger.getBoundingClientRect()
  const gutter = 16
  const panelWidth = panel.offsetWidth
  const panelHeight = panel.offsetHeight
  advancedSettingsPosition.x = Math.max(gutter, Math.min(rect.right - panelWidth, window.innerWidth - panelWidth - gutter))
  advancedSettingsPosition.y = Math.max(gutter, Math.min(rect.bottom + 10, window.innerHeight - panelHeight - gutter))
}

const toggleAdvancedSettings = async () => {
  advancedSettingsExpanded.value = !advancedSettingsExpanded.value
  if (advancedSettingsExpanded.value) await positionAdvancedSettings()
}

const closeAdvancedSettings = () => {
  advancedSettingsExpanded.value = false
}

const applyAdvancedPreset = (preset: AdvancedPreset) => {
  if (preset === 'fast') {
    thinkingMode.value = 'disabled'
    draft.webSearchEnabled = false
    draft.planningDiversity = 'stable'
    return
  }
  if (preset === 'balanced') {
    thinkingMode.value = 'standard'
    draft.webSearchEnabled = true
    draft.planningDiversity = 'balanced'
    return
  }
  thinkingMode.value = 'deep'
  draft.webSearchEnabled = true
  draft.planningDiversity = 'exploratory'
}

const handleAdvancedSettingsViewportChange = () => {
  if (advancedSettingsExpanded.value) void positionAdvancedSettings()
}

const handleAdvancedSettingsDismiss = (event: PointerEvent) => {
  const target = event.target as Node | null
  if (!target) return
  if (advancedSettingsElement.value?.contains(target) || advancedSettingsToggle.value?.contains(target)) return
  if (target instanceof Element && target.closest('.el-popper')) return
  closeAdvancedSettings()
}

const handleAdvancedSettingsKeydown = (event: KeyboardEvent) => {
  if (event.key !== 'Escape' || !advancedSettingsExpanded.value) return
  closeAdvancedSettings()
  nextTick(() => advancedSettingsToggle.value?.focus())
}

watch(userIntent, value => {
  if (activeRunId.value) return
  const update = resolveAcgTaskTitleAutoUpdate({
    currentTitle: taskName.value,
    previousAutoTitle: autoGeneratedTaskName.value,
    taskGoal: value,
    defaultTitle: createNativeWorkbenchDraft().title
  })
  taskName.value = update.title
  autoGeneratedTaskName.value = update.autoTitle
})

const acgView = ref<AcgView | null>(null)
const activeRun = ref<WorkflowRun | null>(null)
const resourceUsage = ref<RunResourceUsage | null>(null)
const resourceDrawerOpen = ref(false)
const openResourceInspector = () => {
  resourceDrawerOpen.value = true
}
const acgAuditEvents = computed(() => {
  const events = [
    ...(acgView.value?.recoveryTrace || []),
    ...(acgView.value?.scheduleTrace || []),
    ...(acgView.value?.contractViolations || [])
  ]
  const seen = new Set<string>()
  return events.filter((event, index) => {
    const key = event.eventId || `${event.eventType}:${event.createdAt || index}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
})
const taskMaterialLength = computed(() => {
  const legalDraft = draft.pluginData['kinlin.legal']
  const candidates = [
    contractText.value,
    typeof legalDraft?.contractText === 'string' ? legalDraft.contractText : ''
  ]
  return (candidates.find(value => value.trim()) || '').length
})
const loading = reactive({ upload: false })
const isSubmitting = ref(false)
const isAcgLoading = ref(false)
const startError = ref<string | null>(null)
const route = useRoute()
const router = useRouter()
const workflowRunsStore = useWorkflowRunsStore()
const activeRunId = ref('')
const installedPlugins = computed(() => pluginUiExtensions.all().map(extension => ({
  pluginId: extension.pluginId,
  displayName: extension.displayName,
  description: '随前端扩展与应用 Pack 一同部署',
  version: 'workspace',
  available: true
})))
const scopeLocked = computed(() => Boolean(activeRunId.value))
const draftExtensions = computed(() => pluginUiExtensions.resolve(draft.enabledPluginIds))
const activePluginIds = computed(() => draft.enabledPluginIds)
const activeExtensions = computed(() => pluginUiExtensions.resolve(activePluginIds.value))
const artifactRenderers = computed(() => activeExtensions.value
  .filter(item => item.artifactRenderer)
  .map(item => ({ pluginId: item.pluginId, component: item.artifactRenderer! })))
const activePluginSummary = computed(() => activePluginIds.value.length
  ? activePluginIds.value.join('、')
  : 'Native only')
const inputPanelExpanded = ref(true)
const inputPanelCompact = ref(false)
const sidePanelCollapsed = ref(false)
const sidePanelManuallySet = ref(false)
const loadedRunId = ref('')

const isCompletedRun = computed(() => (
  acgView.value?.status === 'completed'
  || activeRun.value?.status === 'completed'
))

const setSidePanelCollapsed = (collapsed: boolean) => {
  sidePanelManuallySet.value = true
  sidePanelCollapsed.value = collapsed
}

watch(activeRunId, () => {
  sidePanelManuallySet.value = false
  sidePanelCollapsed.value = false
})

watch(isCompletedRun, completed => {
  if (sidePanelManuallySet.value) return
  sidePanelCollapsed.value = completed
}, { immediate: true })
const contractFileInput = ref<HTMLInputElement | null>(null)
const uploadDragging = ref(false)
type SelectedMaterial = { originalFilename: string; size: number; textLength: number; extractedText: string }
const selectedContractFile = ref<SelectedMaterial | null>(null)
const uploadState = ref<'idle' | 'uploading' | 'parsing' | 'ready' | 'error'>('idle')
const uploadError = ref('')

const resetDraftContent = () => {
  Object.assign(draft, createNativeWorkbenchDraft())
  autoGeneratedTaskName.value = ''
  selectedContractFile.value = null
  uploadState.value = 'idle'
  uploadError.value = ''
}

const applyExtensionDefaults = (pluginId: string) => {
  const defaults = pluginUiExtensions.get(pluginId)?.createDefaults?.()
  if (!defaults) return
  const nativeDefaults = createNativeWorkbenchDraft()
  if (defaults.title && draft.title === nativeDefaults.title) draft.title = defaults.title
  if (defaults.taskGoal && draft.taskGoal === nativeDefaults.taskGoal) draft.taskGoal = defaults.taskGoal
  if (defaults.expectedArtifacts && draft.expectedArtifacts.join('\u0000') === nativeDefaults.expectedArtifacts.join('\u0000')) {
    draft.expectedArtifacts = [...defaults.expectedArtifacts]
  }
  if (defaults.reviewMode) draft.reviewMode = defaults.reviewMode
  if (defaults.pluginData) draft.pluginData = { ...draft.pluginData, ...defaults.pluginData }
}

const removeExtensionDefaults = (pluginId: string) => {
  const defaults = pluginUiExtensions.get(pluginId)?.createDefaults?.()
  const nativeDefaults = createNativeWorkbenchDraft()
  if (defaults?.title && draft.title === defaults.title) draft.title = nativeDefaults.title
  if (defaults?.taskGoal && draft.taskGoal === defaults.taskGoal) draft.taskGoal = nativeDefaults.taskGoal
  if (defaults?.expectedArtifacts && draft.expectedArtifacts.join('\u0000') === defaults.expectedArtifacts.join('\u0000')) {
    draft.expectedArtifacts = [...nativeDefaults.expectedArtifacts]
  }
}

const togglePlugin = (pluginId: string) => {
  if (scopeLocked.value) return
  if (draft.enabledPluginIds[0] === pluginId) {
    clearPlugins()
    return
  }
  for (const selectedPluginId of draft.enabledPluginIds) removeExtensionDefaults(selectedPluginId)
  draft.enabledPluginIds = [pluginId]
  draft.pluginData = {}
  draft.reviewMode = 'auto'
  applyExtensionDefaults(pluginId)
}

const clearPlugins = () => {
  if (scopeLocked.value) return
  for (const pluginId of draft.enabledPluginIds) removeExtensionDefaults(pluginId)
  draft.enabledPluginIds = []
  draft.pluginData = {}
  draft.reviewMode = 'auto'
}

const progressTracker = useWorkflowProgress({
  intervalMs: 2000,
  onProgressChanged: value => workflowRunsStore.updateObservedState(
    value.runId,
    value.status,
    value.phase,
    value.updatedAt
  ),
  onTerminal: handleTerminal
})
const displayedMissionId = computed(() =>
  activeRun.value?.missionId || progressTracker.progress.value?.missionId || ''
)
const reviewPending = computed(() => Boolean(
  activeRunId.value && isWorkflowReviewPending(progressTracker.progress.value, activeRun.value)
))

const CONTRACT_FILE_MAX_SIZE = 10 * 1024 * 1024
const CONTRACT_FILE_EXTENSIONS = ['pdf', 'docx', 'txt', 'md']

const formatFileSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const openContractFilePicker = () => {
  if (!loading.upload) contractFileInput.value?.click()
}

const validateContractFile = (file: File) => {
  const extension = file.name.split('.').pop()?.toLowerCase() || ''
  if (!CONTRACT_FILE_EXTENSIONS.includes(extension)) {
    throw new Error('仅支持 PDF、DOCX、TXT、MD 格式')
  }
  if (file.size <= 0) throw new Error('文件内容为空')
  if (file.size > CONTRACT_FILE_MAX_SIZE) throw new Error('文件不能超过 10MB')
}

const processContractFile = async (file: File) => {
  if (loading.upload) return

  try {
    validateContractFile(file)
    loading.upload = true
    uploadState.value = 'uploading'
    uploadError.value = ''
    uploadState.value = 'parsing'
    const result = await fileApi.extractDocumentText(file)
    const extractedText = (result.text || result.content || '').trim()
    if (!extractedText) throw new Error('未能从文件中提取到文本，请确认文档包含可复制文字')

    contractText.value = extractedText
    draft.materialIds = []
    selectedContractFile.value = {
      originalFilename: result.filename || file.name,
      size: file.size,
      textLength: extractedText.length,
      extractedText
    }
    uploadState.value = 'ready'
    ElMessage.success(`已载入任务文件：${file.name}`)
  } catch (error: any) {
    const message = materialErrorMessage(error)
    uploadState.value = 'error'
    uploadError.value = message
    ElMessage.error(message)
  } finally {
    loading.upload = false
    uploadDragging.value = false
    if (contractFileInput.value) contractFileInput.value.value = ''
  }
}

const handleContractFileSelection = (event: Event) => {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (file) void processContractFile(file)
}

const handleContractDrop = (event: DragEvent) => {
  uploadDragging.value = false
  const file = event.dataTransfer?.files?.[0]
  if (file) void processContractFile(file)
}

const clearContractFile = () => {
  const selected = selectedContractFile.value
  if (selected?.extractedText && contractText.value === selected.extractedText) contractText.value = ''
  draft.materialIds = []
  selectedContractFile.value = null
  uploadState.value = 'idle'
  uploadError.value = ''
  if (contractFileInput.value) contractFileInput.value.value = ''
}

const materialErrorMessage = (error: any): string => {
  const data = error?.response?.data
  const detail = typeof data?.detail === 'string' ? data.detail : data?.detail?.message
  return data?.message || detail || error?.message || '任务文件上传失败'
}

const statusLabel = computed(() => {
  const map: Record<string, string> = {
    completed: '已完成', failed: '失败', running: '执行中',
    waiting_review: '待审核', cancelled: '已取消', retrying: '重试中', planning: '规划中', pending: '待启动'
  }
  const status = progressTracker.progress.value?.status || acgView.value?.status
  return status ? (map[status] || status) : '准备中'
})
const statusTagType = computed(() => {
  const phase = progressTracker.progress.value?.phase
  const s = progressTracker.progress.value?.status || acgView.value?.status
  if (s === 'completed') return 'success'
  if (s === 'failed') return 'danger'
  if (s === 'waiting_review' || phase === 'review' || phase === 'recovery') return 'warning'
  return 'info'
})
const effectiveStatus = computed(() => progressTracker.progress.value?.status || acgView.value?.status || '')
const effectivePhase = computed(() => progressTracker.progress.value?.phase || '')
const planningModeSummary = computed(() => ({
  template_preferred: '模板优先',
  dynamic: '动态规划'
})[planningMode.value])
const thinkingModeSummary = computed(() => ({ disabled: '关闭', standard: '标准', deep: '深度' })[thinkingMode.value])
type AdvancedPreset = 'fast' | 'balanced' | 'deep'
const advancedPreset = computed<AdvancedPreset | 'custom'>(() => {
  if (thinkingMode.value === 'disabled' && !draft.webSearchEnabled && draft.planningDiversity === 'stable') return 'fast'
  if (thinkingMode.value === 'standard' && draft.webSearchEnabled && draft.planningDiversity === 'balanced') return 'balanced'
  if (thinkingMode.value === 'deep' && draft.webSearchEnabled && draft.planningDiversity === 'exploratory') return 'deep'
  return 'custom'
})
const advancedSettingsSummary = computed(() => `${thinkingModeSummary.value}思考 · ${draft.webSearchEnabled ? '联网' : '仅本地'} · ${({
  stable: '稳定',
  balanced: '均衡',
  exploratory: '探索'
} as const)[draft.planningDiversity]}规划`)
const mainAction = computed<{
  action: 'start' | 'planning' | 'view' | 'review' | 'rerun' | 'retry'
  label: string
  type: 'primary' | 'warning' | 'danger' | 'info'
  loading: boolean
  disabled: boolean
}>(() => {
  const status = effectiveStatus.value
  const phase = effectivePhase.value
  if (isSubmitting.value || (activeRunId.value && ['understanding', 'planning', 'graph_building'].includes(phase))) {
    return { action: 'planning', label: '正在生成编排', type: 'info', loading: true, disabled: true }
  }
  if (loading.upload) return { action: 'planning', label: '正在解析文件', type: 'info', loading: true, disabled: true }
  if (!activeRunId.value) return { action: 'start', label: '启动 ACG', type: 'primary', loading: false, disabled: false }
  if (status === 'waiting_review' || phase === 'review') return { action: 'review', label: '进入人工审核', type: 'warning', loading: false, disabled: false }
  if (status === 'completed' || phase === 'completed') return { action: 'rerun', label: '基于当前配置重新运行', type: 'primary', loading: false, disabled: false }
  if (status === 'failed' || phase === 'failed') return { action: 'retry', label: '修改配置并重试', type: 'danger', loading: false, disabled: false }
  if (status === 'cancelled' || phase === 'cancelled') return { action: 'retry', label: '重新运行', type: 'primary', loading: false, disabled: false }
  if (status === 'pending' || status === 'planning') return { action: 'planning', label: '正在生成编排', type: 'info', loading: true, disabled: true }
  return { action: 'view', label: '查看运行', type: 'primary', loading: false, disabled: false }
})
// 从调度 trace 还原"每轮就绪集批次"，可视化并行调度
const scheduleBatches = computed(() => {
  const events = acgView.value?.scheduleTrace || []
  const batches = new Map<string, { id: string; round: number; nodes: string[] }>()
  for (const e of events) {
    const batch = (e.payload?.batch as string[]) || (e.stepId ? [e.stepId] : [])
    const round = Number(e.payload?.round || batches.size + 1)
    const id = String(e.payload?.batchId || `${round}:${e.eventId}`)
    if (batch.length && !batches.has(id)) {
      batches.set(id, { id, round, nodes: batch })
    }
  }
  return Array.from(batches.values()).sort((a, b) => a.round - b.round)
})

const ACTIVE_TOPOLOGY_PHASES = new Set(['executing', 'recovery', 'review'])
const TOPOLOGY_REFRESH_MS = 8000
let topologyController: AbortController | null = null
let topologyTimer: ReturnType<typeof setTimeout> | null = null
let topologyGeneration = 0
let lastTopologyRefreshAt = 0
let lastTopologyUpdatedAt: string | null = null
let submitController: AbortController | null = null
let inputCollapseTimer: ReturnType<typeof setTimeout> | null = null
let inputPanelCompactTimer: ReturnType<typeof setTimeout> | null = null
let terminalNotificationRunId: string | null = null

const clearInputCollapseTimer = () => {
  if (inputCollapseTimer !== null) window.clearTimeout(inputCollapseTimer)
  inputCollapseTimer = null
}

const clearInputPanelCompactTimer = () => {
  if (inputPanelCompactTimer !== null) window.clearTimeout(inputPanelCompactTimer)
  inputPanelCompactTimer = null
}

const inputPanelElement = (element: Element) => element as HTMLElement

const beforeInputPanelEnter = (element: Element) => {
  const panel = inputPanelElement(element)
  inputPanelCompact.value = false
  panel.style.height = '0'
  panel.style.opacity = '0'
  panel.style.transform = 'translateY(-8px)'
}

const enterInputPanel = (element: Element) => {
  const panel = inputPanelElement(element)
  window.requestAnimationFrame(() => {
    panel.style.height = `${panel.scrollHeight}px`
    panel.style.opacity = '1'
    panel.style.transform = 'translateY(0)'
  })
}

const afterInputPanelEnter = (element: Element) => {
  clearInputPanelCompactTimer()
  const panel = inputPanelElement(element)
  panel.style.height = 'auto'
  panel.style.opacity = ''
  panel.style.transform = ''
}

const beforeInputPanelLeave = (element: Element) => {
  const panel = inputPanelElement(element)
  panel.style.height = `${panel.scrollHeight}px`
  panel.style.opacity = '1'
  panel.style.transform = 'translateY(0)'
}

const leaveInputPanel = (element: Element) => {
  const panel = inputPanelElement(element)
  void panel.offsetHeight
  window.requestAnimationFrame(() => {
    panel.style.height = '0'
    panel.style.opacity = '0'
    panel.style.transform = 'translateY(-8px)'
  })
}

const afterInputPanelLeave = (element: Element) => {
  clearInputPanelCompactTimer()
  const panel = inputPanelElement(element)
  panel.style.height = ''
  panel.style.opacity = ''
  panel.style.transform = ''
  if (!inputPanelExpanded.value) inputPanelCompact.value = true
}

const scheduleInputCollapse = (delayMs = 1400) => {
  clearInputCollapseTimer()
  inputCollapseTimer = window.setTimeout(() => {
    inputCollapseTimer = null
    inputPanelExpanded.value = false
  }, delayMs)
}

const clearTopologyTimer = () => {
  if (topologyTimer !== null) {
    window.clearTimeout(topologyTimer)
    topologyTimer = null
  }
}

const clearRunData = () => {
  clearTopologyTimer()
  topologyGeneration += 1
  topologyController?.abort()
  topologyController = null
  acgView.value = null
  activeRun.value = null
  resourceUsage.value = null
  resourceDrawerOpen.value = false
  loadedRunId.value = ''
  isAcgLoading.value = false
  lastTopologyRefreshAt = 0
  lastTopologyUpdatedAt = null
}

const enterNewAcgDraft = () => {
  submitController?.abort()
  progressTracker.reset()
  clearRunData()
  clearInputCollapseTimer()
  clearInputPanelCompactTimer()
  activeRunId.value = ''
  startError.value = null
  inputPanelExpanded.value = true
  inputPanelCompact.value = false
  advancedSettingsExpanded.value = false
  resetDraftContent()
}

async function refreshAcgForRun(runId: string, force = false): Promise<void> {
  if (!runId || runId !== activeRunId.value) return
  if (!force && progressTracker.progress.value?.updatedAt === lastTopologyUpdatedAt) return

  const requestGeneration = ++topologyGeneration
  topologyController?.abort()
  topologyController = new AbortController()
  const signal = topologyController.signal
  isAcgLoading.value = true
  try {
    const runPromise = workflowApi.getRun(runId, { signal })
    const [runResult, viewResult, historyConfigResult, resourceResult] = await Promise.allSettled([
      runPromise,
      workflowApi.getAcgView(runId, { signal, run: runPromise }),
      workflowApi.getRunHistoryConfig(runId, { signal }),
      workflowApi.getRunResourceUsage(runId, { signal })
    ])
    if (requestGeneration !== topologyGeneration || runId !== activeRunId.value) return
    if (runResult.status === 'rejected') {
      if (axios.isAxiosError(runResult.reason) && runResult.reason.response?.status === 404) {
        await removeMissingAcgRun(runId)
      } else if (!axios.isCancel(runResult.reason) && force) {
        ElMessage.warning('运行信息暂时未能加载，请稍后刷新')
      }
      return
    }
    activeRun.value = runResult.value
    if (viewResult.status === 'rejected') {
      if (!axios.isCancel(viewResult.reason) && force) {
        ElMessage.warning('最终 ACG 数据暂时未能加载，请稍后刷新')
      }
      return
    }

    const view = viewResult.value
    const run = runResult.value
    acgView.value = view
    activeRun.value = run
    resourceUsage.value = resourceResult.status === 'fulfilled' ? resourceResult.value : null
    if (loadedRunId.value !== runId && historyConfigResult.status === 'fulfilled') {
      const historyConfig = historyConfigResult.value
      restoreWorkbenchDraft(draft, historyConfig, pluginUiExtensions.resolve(historyConfig.enabledPluginIds || []))
    } else {
      taskName.value = resolveAcgTaskTitle(run)
    }
    loadedRunId.value = runId
    lastTopologyRefreshAt = Date.now()
    lastTopologyUpdatedAt = progressTracker.progress.value?.updatedAt ?? null
  } catch (error: unknown) {
    if (!axios.isCancel(error) && requestGeneration === topologyGeneration && force) {
      ElMessage.warning('最终 ACG 数据暂时未能加载，请稍后刷新')
    }
  } finally {
    if (requestGeneration === topologyGeneration) {
      topologyController = null
      isAcgLoading.value = false
    }
  }
}

const removeMissingAcgRun = async (runId: string) => {
  workflowRunsStore.removeReference(runId)
  notifyAcgRunInvalidated(runId)
  if (activeRunId.value !== runId) return
  progressTracker.reset()
  clearRunData()
  activeRunId.value = ''
  const query = { ...route.query }
  delete query.runId
  await router.replace({ query })
  ElMessage.warning('该运行记录已不存在。')
}

const scheduleTopologyRefresh = (value: DeepReadonly<WorkflowProgress>) => {
  if (!ACTIVE_TOPOLOGY_PHASES.has(value.phase) || value.runId !== activeRunId.value) return
  if (value.updatedAt === lastTopologyUpdatedAt) return
  clearTopologyTimer()
  const remaining = Math.max(0, TOPOLOGY_REFRESH_MS - (Date.now() - lastTopologyRefreshAt))
  topologyTimer = window.setTimeout(() => {
    topologyTimer = null
    void refreshAcgForRun(value.runId)
  }, remaining)
}

async function handleTerminal(value: WorkflowProgress): Promise<void> {
  const shouldNotify = terminalNotificationRunId === value.runId
  if (shouldNotify) terminalNotificationRunId = null
  clearTopologyTimer()
  for (let attempt = 0; attempt < 3; attempt += 1) {
    await refreshAcgForRun(value.runId, true)
    const projectedStepCount = acgView.value?.stepOutputs?.length || 0
    const hasFinalResult = Boolean(
      acgView.value?.finalArtifacts?.length || acgView.value?.finalReport
    )
    const identityProjectionComplete = acgView.value?.identityProjection?.status === 'available'
    const projectionComplete = projectedStepCount >= value.completedSteps
      && (value.phase !== 'completed' || hasFinalResult)
      && identityProjectionComplete
    if (projectionComplete) break
    await new Promise(resolve => window.setTimeout(resolve, 300))
  }
  if (!shouldNotify) return
  if (value.phase === 'completed') ElMessage.success('ACG 引擎执行完成')
  if (value.phase === 'failed') ElMessage.error('ACG 工作流执行失败')
  if (value.phase === 'cancelled') ElMessage.info('ACG 工作流已取消')
}

watch(
  () => progressTracker.progress.value,
  (value, previous) => {
    if (!value) return
    const stateChanged = value.status !== previous?.status || value.phase !== previous?.phase
    if (value.status === 'failed' || value.phase === 'failed') {
      clearInputCollapseTimer()
      inputPanelExpanded.value = true
    } else if (stateChanged && (value.status === 'waiting_review' || ['review', 'completed', 'cancelled'].includes(value.phase))) {
      scheduleInputCollapse(0)
    }
    if (isWorkflowReviewPending(value, activeRun.value) && !isWorkflowReviewPending(previous, activeRun.value)) {
      clearTopologyTimer()
      void refreshAcgForRun(value.runId, true)
      return
    }
    scheduleTopologyRefresh(value)
  }
)

watch(() => progressTracker.syncError.value, error => {
  if (error === '该运行记录不存在或当前账户无权访问' && activeRunId.value) {
    void removeMissingAcgRun(activeRunId.value)
  }
})

watch(inputPanelExpanded, value => {
  clearInputPanelCompactTimer()
  if (value) {
    inputPanelCompact.value = false
    return
  }
  advancedSettingsExpanded.value = false
  inputPanelCompactTimer = window.setTimeout(() => {
    inputPanelCompactTimer = null
    if (!inputPanelExpanded.value) inputPanelCompact.value = true
  }, 380)
})

watch(
  () => route.query.runId,
  (value) => {
    if (typeof value !== 'string' || !value.trim()) return
    const runId = value.trim()
    if (runId === activeRunId.value && progressTracker.runId.value === runId) return
    terminalNotificationRunId = null
    progressTracker.reset()
    clearRunData()
    startError.value = null
    activeRunId.value = runId
    inputPanelExpanded.value = false
    inputPanelCompact.value = true
    advancedSettingsExpanded.value = false
    workflowRunsStore.register({ runId, source: 'restored' })
    void progressTracker.start(runId, { fresh: false })
  },
  { immediate: true }
)


const openOperations = () => {
  void router.push({
    path: '/agentos-console',
    query: activeRunId.value ? { runId: activeRunId.value, source: 'acg' } : { source: 'acg' }
  })
}

const openRelatedRun = (runId: string) => {
  void router.push({ path: '/agentos/acg', query: { runId } })
}

const scrollToSection = (selector: string) => {
  const target = document.querySelector<HTMLElement>(selector)
  if (!target) return
  const top = target.getBoundingClientRect().top + window.scrollY - 16
  window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' })
}

const rerunWithNewPlanningSeed = () => {
  const values = new Uint32Array(1)
  crypto.getRandomValues(values)
  draft.planningSeed = values[0] & 0x7fffffff
  void startRun()
}

const handleMainAction = () => {
  if (mainAction.value.action === 'start' || mainAction.value.action === 'rerun' || mainAction.value.action === 'retry') {
    void startRun()
    return
  }
  if (mainAction.value.action === 'review') {
    scrollToSection('.workflow-review')
    return
  }
  if (mainAction.value.action === 'view') scrollToSection('.workflow-progress')
}

const handleAcgReviewed = async (run: WorkflowRun) => {
  if (run.runId !== activeRunId.value) return
  activeRun.value = run
  await progressTracker.refresh()
  await refreshAcgForRun(run.runId, true)
}

const handleAcgReviewConflict = async () => {
  await progressTracker.refresh()
  if (activeRunId.value) await refreshAcgForRun(activeRunId.value, true)
}

const downloadText = (content: string, filename: string, type: string) => {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

const exportAudit = (format: 'json' | 'csv') => {
  if (!acgView.value) return
  const filename = `acg-audit-${acgView.value.runId}.${format}`
  if (format === 'json') {
    downloadText(
      JSON.stringify(buildAcgAuditExport(acgView.value), null, 2),
      filename,
      'application/json;charset=utf-8'
    )
  } else {
    downloadText(`\ufeff${buildAcgAuditCsv(acgView.value)}`, filename, 'text/csv;charset=utf-8')
  }
  ElMessage.success(`ACG 审计 ${format.toUpperCase()} 已导出`)
}

const startRun = async () => {
  if (isSubmitting.value) return
  if (!taskName.value.trim()) {
    ElMessage.warning('请输入任务名称')
    return
  }
  if (!userIntent.value.trim()) {
    ElMessage.warning('请输入任务目标')
    return
  }
  for (const extension of draftExtensions.value) {
    const validation = extension.validateDraft?.(draft)
    if (validation && !validation.valid) {
      ElMessage.warning(validation.message || `${extension.displayName}配置不完整`)
      return
    }
  }
  isSubmitting.value = true
  startError.value = null
  submitController?.abort()
  submitController = new AbortController()
  progressTracker.reset()
  clearRunData()
  activeRunId.value = ''
  terminalNotificationRunId = null
  try {
    const clientRequestId = createClientRequestId()
    const request = buildWorkbenchStartRequest(draft, draftExtensions.value, clientRequestId)
    const requestInput: Record<string, unknown> = {
      ...request.input,
      taskName: taskName.value.trim(),
      debugTrace: debugTraceEnabled.value,
      lowEntropyOptions: [...lowEntropyOptions.value]
    }
    request.input = requestInput
    const material = String(request.input.materialText || '')
    if (material) {
      const manifest = await workflowApi.createMaterial(material, 'text/plain')
      request.materialRefs = [manifest.manifestId]
      delete request.input.materialText
    }
    const res = await workflowApi.startWorkflowAsync(request, { signal: submitController.signal })
    activeRunId.value = res.runId
    scheduleInputCollapse()
    advancedSettingsExpanded.value = false
    workflowRunsStore.register({
      runId: res.runId,
      missionId: res.missionId,
      workflowId: res.workflowId || request.workflowId || 'native_acg_runtime_v1',
      source: 'acg',
      status: res.status,
      phase: res.lifecyclePhase || undefined
    })
    window.dispatchEvent(new Event('acg-runs-refresh'))
    terminalNotificationRunId = res.runId
    void progressTracker.start(res.runId, { fresh: true })
    await router.replace({ query: { ...route.query, runId: res.runId } })
  } catch (error: unknown) {
    if (axios.isCancel(error)) return
    startError.value = startErrorMessage(error)
  } finally {
    isSubmitting.value = false
    submitController = null
  }
}

const createClientRequestId = (): string => {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0'))
  return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex.slice(6, 8).join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10).join('')}`
}

const startErrorDetail = (data: unknown): string | null => {
  if (!data || typeof data !== 'object') return null
  const response = data as Record<string, unknown>
  const parts = [response.message, response.error, response.detail]
    .filter((value): value is string => typeof value === 'string' && Boolean(value.trim()))
    .map((value) => value.trim())
  const unique = [...new Set(parts)]
  return unique.length ? unique.join('：').slice(0, 240) : null
}

const startErrorMessage = (error: unknown): string => {
  if (axios.isAxiosError(error)) {
    if (error.response?.status === 409) {
      return '相同请求标识已用于不同参数，请重新发起任务'
    }
    if (!error.response) return '任务未能启动：网络连接暂时不可用'
    const detail = startErrorDetail(error.response.data)
    if (detail) return `任务未能启动：${detail}`
  }
  return '任务未能启动'
}

onMounted(() => {
  window.addEventListener('acg-new-task', enterNewAcgDraft)
  window.addEventListener('resize', handleAdvancedSettingsViewportChange)
  window.addEventListener('pointerdown', handleAdvancedSettingsDismiss)
  window.addEventListener('keydown', handleAdvancedSettingsKeydown)
})

onBeforeUnmount(() => {
  submitController?.abort()
  clearTopologyTimer()
  topologyGeneration += 1
  topologyController?.abort()
  clearInputCollapseTimer()
  clearInputPanelCompactTimer()
  window.removeEventListener('acg-new-task', enterNewAcgDraft)
  window.removeEventListener('resize', handleAdvancedSettingsViewportChange)
  window.removeEventListener('pointerdown', handleAdvancedSettingsDismiss)
  window.removeEventListener('keydown', handleAdvancedSettingsKeydown)
})
</script>

<style scoped>
.acg-view.ui-shell { display: flex; flex-direction: column; gap: 0; padding: var(--space-sm) var(--space-md); }
.acg-view.is-draft { min-height: calc(100dvh + 15px); }
.acg-view > .ui-hero { border-bottom: 0; border-radius: 8px 8px 0 0; }
.acg-view > .control-bar { border-top: 0; border-radius: 0 0 8px 8px; }
.acg-view.is-draft > .control-bar { flex: 1 1 auto; }
.acg-view.is-draft > .control-bar.collapsed { flex: 0 0 auto; min-height: 58px; }
.acg-view.has-progress:not(.has-run) > .control-bar { border-bottom: 0; border-radius: 0; box-shadow: none; }
.acg-view.has-progress:not(.has-run) > .run-overview { border-top: 0; border-radius: 0 0 8px 8px; }
.run-overview { margin-top: 12px; overflow: hidden; }
.run-overview > :deep(.workflow-progress),
.run-overview > :deep(.agentos-run-summary) {
  margin: 0; border: 0; border-radius: 0; background: transparent;
}
.run-overview > :deep(.workflow-progress) { padding: 14px 16px; }
.run-overview > :deep(.agentos-run-summary) { padding: 14px 16px; }
:global(.resource-drawer) {
  --el-drawer-padding-primary: 0;
  border-radius: var(--radius-panel) 0 0 var(--radius-panel);
  overflow: hidden;
  box-shadow: var(--shadow-lg);
}
:global(.resource-drawer .el-drawer__header) {
  margin: 0;
  padding: 18px 22px 16px;
  border-bottom: 1px solid var(--border-light);
}
:global(.resource-drawer .el-drawer__body) {
  padding: 0;
  overflow-y: auto;
  background: var(--surface-solid);
}
:global(.resource-drawer .el-drawer__close-btn) { border-radius: var(--radius-control); }
:global(.resource-drawer .el-tag) { border-radius: var(--radius-full); }
.resource-drawer__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.resource-drawer__header > div { display: grid; gap: 4px; min-width: 0; }
.resource-drawer__header strong { color: var(--text-primary); font-size: 16px; font-weight: 800; line-height: 1.25; }
.resource-drawer__header span { color: var(--text-secondary); font-size: 11px; line-height: 1.4; }
.resource-drawer__body { min-height: 100%; padding: 0 22px 24px; }
.hero-left { display: flex; align-items: center; gap: 10px; min-width: 0; }
.ui-hero h3 { overflow: hidden; margin: 0; color: var(--text-primary); font-size: 18px; font-weight: 800; line-height: 1.2; text-overflow: ellipsis; white-space: nowrap; }
.hero-right { display: flex; gap: 8px; align-items: center; justify-content: flex-end; flex-wrap: nowrap; }
.hero-run-chip { min-width: 0; height: 30px; display: inline-flex; align-items: center; gap: 5px; padding: 0 9px; border: 1px solid var(--border-light); border-radius: 6px; background: var(--bg-input); color: var(--text-muted); font-size: 10px; }
.hero-run-chip code { overflow: hidden; max-width: 150px; color: var(--text-secondary); font-family: var(--font-mono, ui-monospace, SFMono-Regular, Consolas, monospace); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.hero-icon-action, .hero-operations { height: 32px; display: inline-flex; align-items: center; justify-content: center; border: 1px solid var(--border-light); background: var(--surface-solid); color: var(--text-secondary); cursor: pointer; transition: var(--transition); }
.hero-icon-action { width: 32px; padding: 0; border-radius: 50%; }
.hero-operations { gap: 5px; padding: 0 11px; border-radius: 7px; font: inherit; font-size: 11px; }
.hero-icon-action:hover:not(:disabled), .hero-operations:hover { border-color: var(--primary-line); background: var(--primary-fade); color: var(--primary-color); }
.hero-icon-action:disabled { cursor: not-allowed; opacity: .5; }
.hero-icon-action:focus-visible, .hero-operations:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
.control-bar { position: relative; display: flex; flex-direction: column; gap: var(--space-md); padding-right: 52px; padding-bottom: 10px; }
.control-bar.advanced-open { z-index: 40; }
.control-bar.collapsed { flex-direction: row; align-items: center; gap: 14px; padding: 10px 52px 10px 14px; }
.control-bar.collapsed .input-summary { flex: 1 1 auto; }
.control-bar.collapsed .ctrl-options { flex: 0 0 auto; padding: 0; border: 0; }
.control-bar.collapsed .ctrl-options > :deep(.el-button:last-child) { margin-left: 0; }
.workbench-identity, .plugin-selector header, .run-scope header { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.workbench-identity div, .plugin-selector header div { display:flex; flex-direction:column; gap:3px; }
.workbench-identity small, .plugin-selector small, .plugin-selector header span { color:var(--text-secondary); font-size:11px; }
.plugin-selector { display:flex; flex-direction:column; gap:10px; padding:0; }
.plugin-selector header { align-items:flex-end; }
.plugin-selector header strong { color:var(--text-primary); font-size:14px; font-weight:780; }
.plugin-selector header small { color:var(--text-muted); font-size:10px; }
.plugin-options { display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:10px; }
.plugin-card { position:relative; display:flex; flex-direction:column; align-items:stretch; gap:7px; min-height:92px; padding:13px 14px; border:1px solid var(--border-light); border-radius:var(--radius-card); background:var(--surface-solid); color:var(--text-primary); text-align:left; cursor:pointer; transition:var(--transition); }
.plugin-card:hover:not(:disabled) { border-color:var(--border-hover); background:var(--surface-hover); transform:translateY(-1px); }
.plugin-card.selected { border-color:var(--primary-line); background:color-mix(in srgb, var(--primary-fade) 68%, var(--surface-solid)); box-shadow:inset 0 0 0 1px color-mix(in srgb, var(--primary-color) 24%, transparent), var(--shadow-sm); }
.plugin-card__top { display:flex; align-items:center; justify-content:space-between; gap:10px; }
.plugin-card__top strong { min-width:0; color:var(--text-primary); font-size:12px; font-weight:760; }
.plugin-card__state { flex:0 0 auto; padding:4px 7px; border-radius:var(--radius-full); background:var(--bg-input); color:var(--text-muted); font-size:9px; line-height:1; }
.plugin-card.selected .plugin-card__state { background:var(--primary-fade); color:var(--primary-color); }
.plugin-card small { min-height:28px; color:var(--text-secondary); font-size:10px; line-height:1.45; }
.plugin-card code { align-self:flex-start; padding:4px 7px; border-radius:5px; background:var(--bg-input); color:var(--text-muted); font-family:var(--font-mono); font-size:9px; }
.plugin-card:disabled { cursor:not-allowed; opacity:.6; }
.plugin-card:focus-visible { outline:2px solid var(--primary-color); outline-offset:2px; }
.run-scope { display:flex; flex-direction:column; gap:8px; padding:18px 20px; }
.run-scope header strong { font-size:13px; }
.snapshot-list { display:flex; align-items:center; flex-wrap:wrap; gap:8px; color:var(--text-secondary); font-size:11px; }
.snapshot-list span, .snapshot-list code { padding:5px 8px; border-radius:6px; background:var(--bg-input); }
.input-panel-expandable {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  min-width: 0;
  overflow: hidden;
  transform-origin: top center;
  transition:
    height 380ms cubic-bezier(0.22, 1, 0.36, 1),
    opacity 220ms ease,
    transform 380ms cubic-bezier(0.22, 1, 0.36, 1);
  will-change: height, opacity, transform;
}
.input-panel-toggle {
  position: absolute; top: 10px; right: 12px; z-index: 1;
  width: 28px; height: 28px; display: inline-grid; place-items: center;
  padding: 0; border: 1px solid var(--border-light); border-radius: 6px;
  background: var(--surface-solid); color: var(--text-secondary); cursor: pointer;
  transition: var(--transition);
}
.input-panel-toggle:hover { border-color: var(--primary-line); color: var(--primary-color); background: var(--primary-fade); }
.input-panel-toggle:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--primary-fade); }
.input-fields { display: grid; grid-template-columns: minmax(0, 13fr) minmax(280px, 7fr); align-items: stretch; gap: 24px; min-width: 0; }
.input-pane { display: flex; flex-direction: column; gap: 10px; min-width: 0; }
.contract-pane .ctrl-row { flex: 1 1 auto; min-height: 0; }
.contract-pane .contract-textarea { flex: 1 1 auto; min-height: 0; }
.definition-pane { min-width: 0; gap: 12px; }
.definition-pane :deep(.el-input__wrapper) {
  min-height: 42px;
  border-radius: 6px;
  background: var(--bg-input);
  box-shadow: none;
}
.definition-pane :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--border-light) inset;
}
.definition-pane :deep(.el-input__wrapper.is-focus) {
  background: var(--surface-solid);
  box-shadow: 0 0 0 1px var(--primary-color) inset;
}
.pane-heading { color: var(--text-primary); font-size: 13px; font-weight: 750; }
.pane-heading small { margin-left: 4px; color: var(--text-disabled); font-size: 10px; font-weight: 600; }
.input-summary { display: flex; align-items: center; min-width: 0; }
.input-summary__copy { display: grid; grid-template-columns: 28px minmax(0, auto) minmax(0, 1fr); align-items: center; gap: 8px; min-width: 0; color: var(--text-secondary); }
.input-summary__copy .el-icon { width: 28px; height: 28px; display: inline-grid; place-items: center; border: 1px solid var(--primary-line); border-radius: 7px; background: var(--primary-fade); color: var(--primary-color); }
.input-summary__copy strong { overflow: hidden; max-width: min(240px, 28vw); color: var(--text-primary); font-size: 13px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.input-summary__copy small { overflow: hidden; padding-left: 9px; border-left: 1px solid var(--border-light); text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.run-error {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid color-mix(in srgb, var(--danger) 38%, var(--border-light));
  border-radius: 6px;
  background: var(--danger-fade);
  color: var(--danger);
  font-size: 12px;
}
.ctrl-row { display: flex; flex-direction: column; gap: 6px; }
.ctrl-label { font-size: 12px; font-weight: 600; color: var(--text-secondary); }
.ctrl-options {
  order: 2;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  padding-top: 6px;
}
.primary-options { display: flex; align-items: center; gap: 18px; min-width: 0; flex-wrap: wrap; overflow: visible; }
.primary-config { display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ctrl-label { white-space: nowrap; font-size: 11px; font-weight: 650; color: var(--text-secondary); }
.segmented-control {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-full);
  background: var(--bg-input);
  box-shadow: inset 0 1px 0 color-mix(in srgb, var(--surface-solid) 45%, transparent);
}
.segment-option {
  min-height: 26px;
  padding: 0 10px;
  border: 0;
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--text-secondary);
  font: inherit;
  font-size: 11px;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 160ms var(--ease-out), color 160ms var(--ease-out), box-shadow 160ms var(--ease-out), transform 160ms var(--ease-out);
}
.segment-option:hover { color: var(--text-primary); }
.segment-option.selected {
  background: var(--surface-solid);
  color: var(--primary-color);
  box-shadow: var(--shadow-sm), 0 0 0 1px var(--primary-line);
}
.segment-option:active { transform: scale(.98); }
.segment-option:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
.advanced-toggle {
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 4px 9px 4px 11px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-card);
  background: var(--surface-solid);
  color: var(--text-secondary);
  text-align: left;
  cursor: pointer;
  transition: var(--transition);
}
.advanced-toggle:hover, .advanced-toggle[aria-expanded="true"] { border-color: var(--primary-line); background: var(--primary-fade); color: var(--primary-color); }
.advanced-toggle:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
.advanced-toggle__copy { display: grid; gap: 1px; min-width: 0; }
.advanced-toggle__copy strong { color: inherit; font-size: 11px; font-weight: 700; line-height: 1.2; }
.advanced-toggle__copy small { overflow: hidden; max-width: 210px; color: var(--text-muted); font-size: 9px; line-height: 1.2; text-overflow: ellipsis; white-space: nowrap; }
.advanced-toggle:hover .advanced-toggle__copy small, .advanced-toggle[aria-expanded="true"] .advanced-toggle__copy small { color: color-mix(in srgb, var(--primary-color) 72%, var(--text-secondary)); }
.advanced-settings-popover { position: relative; z-index: 20; }
.ctrl-options > :deep(.main-action:last-child) {
  --main-action-tone: var(--primary-color);
  --main-action-hover: var(--primary-hover);
  position: relative;
  isolation: isolate;
  min-width: 126px;
  min-height: 44px;
  padding: 0 15px 0 17px;
  overflow: visible;
  border: 1px solid color-mix(in srgb, var(--main-action-tone) 82%, white 18%) !important;
  border-radius: var(--radius-card);
  color: var(--on-primary) !important;
  font-weight: 780;
  letter-spacing: .01em;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .22), 0 7px 14px color-mix(in srgb, var(--main-action-tone) 22%, transparent), 0 0 0 1px color-mix(in srgb, var(--main-action-tone) 16%, transparent);
  transform: translateY(0);
  transition: background-color 180ms var(--ease-out), border-color 180ms var(--ease-out), box-shadow 180ms var(--ease-out), transform 180ms var(--ease-out);
}
.ctrl-options > :deep(.main-action:last-child)::before {
  content: '';
  position: absolute;
  inset: -5px;
  z-index: -1;
  border: 1px solid color-mix(in srgb, var(--main-action-tone) 42%, transparent);
  border-radius: calc(var(--radius-card) + 4px);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--main-action-tone) 7%, transparent);
  opacity: 0;
  transform: scale(.94);
  transition: opacity 180ms var(--ease-out), transform 220ms var(--ease-out);
  pointer-events: none;
}
.ctrl-options > :deep(.main-action:last-child)::after {
  content: '';
  position: absolute;
  inset: 1px;
  z-index: -1;
  border-radius: calc(var(--radius-card) - 1px);
  background: rgba(255, 255, 255, .1);
  opacity: .55;
  pointer-events: none;
}
.ctrl-options > :deep(.main-action.el-button--primary) { background: var(--primary-color) !important; }
.ctrl-options > :deep(.main-action.el-button--warning) { --main-action-tone: var(--warning); --main-action-hover: color-mix(in srgb, var(--warning) 86%, white 14%); }
.ctrl-options > :deep(.main-action.el-button--danger) { --main-action-tone: var(--danger); --main-action-hover: color-mix(in srgb, var(--danger) 86%, white 14%); }
.ctrl-options > :deep(.main-action.el-button--info) { --main-action-tone: var(--info); --main-action-hover: color-mix(in srgb, var(--info) 86%, white 14%); }
.ctrl-options > :deep(.main-action:last-child:hover:not(:disabled)) {
  background: var(--main-action-hover) !important;
  border-color: color-mix(in srgb, var(--main-action-tone) 90%, white 10%) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, .26), 0 12px 24px color-mix(in srgb, var(--main-action-tone) 30%, transparent), 0 0 0 1px color-mix(in srgb, var(--main-action-tone) 22%, transparent);
  transform: translateY(-2px);
}
.ctrl-options > :deep(.main-action:last-child:hover:not(:disabled))::before { opacity: 1; transform: scale(1); }
.ctrl-options > :deep(.main-action:last-child:active:not(:disabled)) {
  box-shadow: inset 0 2px 3px rgba(8, 9, 18, .18), 0 3px 8px color-mix(in srgb, var(--main-action-tone) 20%, transparent);
  transform: translateY(1px) scale(.985);
}
.ctrl-options > :deep(.main-action:last-child:focus-visible) { outline: 3px solid color-mix(in srgb, var(--main-action-tone) 34%, transparent); outline-offset: 3px; }
.ctrl-options > :deep(.main-action:last-child:disabled) { box-shadow: var(--shadow-sm); cursor: wait; opacity: .72; }
.main-action__label, .main-action__arrow { position: relative; z-index: 1; }
.main-action__arrow { margin-left: 6px; transition: transform 180ms var(--ease-out); }
.ctrl-options > :deep(.main-action:last-child:hover:not(:disabled)) .main-action__arrow { transform: translateX(3px); }
.advanced-settings {
  position: fixed;
  top: 0;
  left: 0;
  right: auto;
  z-index: 100;
  width: min(688px, calc(100vw - 32px));
  max-height: min(520px, calc(100dvh - 104px));
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  padding: 8px;
  overflow-x: hidden;
  overflow-y: auto;
  border: 1px solid color-mix(in srgb, var(--border-light) 78%, var(--surface-solid));
  border-radius: 16px;
  background: var(--bg-input);
  box-shadow: 0 22px 56px color-mix(in srgb, var(--shadow-color) 80%, transparent), 0 4px 12px color-mix(in srgb, var(--shadow-color) 42%, transparent);
  transform-origin: top right;
  animation: advanced-settings-in 180ms var(--ease-out) both;
}
.advanced-settings__head {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  min-width: 0;
  min-height: 72px;
  padding: 15px 16px;
  border: 1px solid var(--border-light);
  border-radius: 11px;
  background: var(--surface-solid);
}
.advanced-settings__head > div { display: grid; gap: 3px; min-width: 0; }
.advanced-settings__head strong { color: var(--text-primary); font-size: 15px; font-weight: 780; letter-spacing: -.015em; }
.advanced-settings__head small { color: var(--text-muted); font-size: 10px; line-height: 1.4; }
.advanced-settings__head > .advanced-settings__head-actions { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
.advanced-settings__head-actions > span { max-width: 220px; overflow: hidden; padding: 7px 10px; border: 1px solid var(--primary-line); border-radius: var(--radius-full); background: var(--primary-fade); color: var(--primary-color); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.advanced-settings__close { width: 32px; height: 32px; display: inline-grid; place-items: center; padding: 0; border: 1px solid var(--border-light); border-radius: var(--radius-control); background: var(--bg-input); color: var(--text-secondary); cursor: pointer; transition: var(--transition); }
.advanced-settings__close:hover, .advanced-settings__close:focus-visible { border-color: var(--primary-line); background: var(--primary-fade); color: var(--primary-color); outline: none; }
.advanced-settings__close:focus-visible { box-shadow: 0 0 0 3px var(--primary-fade); }
.advanced-presets { grid-column: 1 / -1; display: grid; grid-template-columns: minmax(142px, .7fr) minmax(0, 2fr); align-items: center; gap: 14px; padding: 12px 14px; border: 1px solid var(--border-light); border-radius: 11px; background: var(--surface-solid); }
.advanced-presets__intro { display: grid; gap: 3px; min-width: 0; }
.advanced-presets__intro strong { color: var(--text-primary); font-size: 12px; font-weight: 780; }
.advanced-presets__intro small { color: var(--text-muted); font-size: 10px; }
.advanced-presets__options { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; min-width: 0; }
.advanced-preset { min-height: 48px; display: grid; align-content: center; gap: 3px; padding: 7px 10px; border: 1px solid var(--border-light); border-radius: 9px; background: var(--bg-input); color: var(--text-secondary); text-align: left; cursor: pointer; transition: var(--transition); }
.advanced-preset strong { color: inherit; font-size: 11px; font-weight: 750; }
.advanced-preset small { overflow: hidden; color: var(--text-muted); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.advanced-preset:hover, .advanced-preset.selected { border-color: var(--primary-color); background: var(--primary-fade); color: var(--primary-color); }
.advanced-preset:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
.advanced-item {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
  min-height: 82px;
  padding: 13px 14px;
  border: 1px solid var(--border-light);
  border-radius: 11px;
  background: var(--surface-solid);
}
.advanced-item__heading { display: grid; gap: 3px; min-width: 0; }
.advanced-item__heading > span, .advanced-item__label { color: var(--text-primary); font-size: 12px; font-weight: 740; }
.advanced-item__heading small { overflow: hidden; color: var(--text-muted); font-size: 10px; line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }
.advanced-item--segmented .segmented-control { align-self: flex-start; }
.advanced-item--switch { flex-direction: row; align-items: center; justify-content: space-between; gap: 12px; }
.advanced-item--switch .advanced-item__heading { flex: 1 1 auto; }
.advanced-item--wide { grid-column: span 2; }
.advanced-item :deep(.el-select), .advanced-item :deep(.el-input-number) { width: 100%; }
.advanced-item :deep(.el-input__wrapper) {
  min-height: 36px;
  border: 1px solid var(--border-light);
  border-radius: 9px;
  background: var(--bg-input);
  box-shadow: none;
  transition: border-color 160ms var(--ease-out), background-color 160ms var(--ease-out), box-shadow 160ms var(--ease-out);
}
.advanced-item :deep(.el-input__wrapper:hover) { border-color: var(--border-hover); }
.advanced-item :deep(.el-input__wrapper.is-focus) { border-color: var(--primary-color); background: var(--surface-solid); box-shadow: 0 0 0 3px var(--primary-fade); }
.advanced-item :deep(.el-input__inner) { color: var(--text-primary); font-size: 11px; }
.advanced-item :deep(.el-select .el-input__inner) { color: var(--text-primary); }
.advanced-item :deep(.el-button) { min-height: 34px; border-radius: 9px; }
.settings-switch { display: inline-flex; align-items: center; gap: 7px; flex: 0 0 auto; padding: 0; border: 0; background: transparent; color: var(--text-muted); font: inherit; font-size: 10px; cursor: pointer; }
.settings-switch:hover:not(:disabled), .settings-switch[aria-checked="true"] { color: var(--primary-color); }
.settings-switch:disabled { cursor: not-allowed; opacity: .55; }
.settings-switch:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 4px; border-radius: var(--radius-full); }
.settings-switch__track { position: relative; width: 36px; height: 22px; flex: 0 0 36px; display: inline-flex; align-items: center; padding: 2px; border-radius: var(--radius-full); background: var(--border-hover); transition: background-color 160ms var(--ease-out), box-shadow 160ms var(--ease-out); }
.settings-switch__track > span { width: 18px; height: 18px; display: block; border-radius: 50%; background: var(--surface-solid); box-shadow: var(--shadow-sm); transform: translateX(0); transition: transform 160ms var(--ease-out); }
.settings-switch[aria-checked="true"] .settings-switch__track { background: var(--primary-color); box-shadow: 0 0 0 2px var(--primary-fade); }
.settings-switch[aria-checked="true"] .settings-switch__track > span { transform: translateX(14px); }
.settings-switch:active .settings-switch__track > span { transform: scale(.92); }
.settings-switch[aria-checked="true"]:active .settings-switch__track > span { transform: translateX(14px) scale(.92); }
@keyframes advanced-settings-in {
  from { opacity: 0; transform: translateY(-6px) scale(.985); }
  to { opacity: 1; transform: translateY(0) scale(1); }
}
.contract-textarea :deep(.el-textarea__inner),
.intent-textarea :deep(.el-textarea__inner) {
  line-height: 1.72;
  font-size: 14px;
  padding: 12px 14px;
  resize: vertical;
}
.contract-pane .contract-textarea :deep(.el-textarea__inner) { height: 100% !important; }
.acg-view.is-draft .input-panel-expandable,
.acg-view.is-draft .input-fields,
.acg-view.is-draft .definition-pane .ctrl-row,
.acg-view.is-draft .contract-textarea,
.acg-view.is-draft .intent-textarea { flex: 1 1 auto; min-height: 0; }
.acg-view.is-draft .contract-textarea :deep(.el-textarea__inner),
.acg-view.is-draft .intent-textarea :deep(.el-textarea__inner) { height: 100% !important; }
.acg-view.is-draft .ctrl-options { margin-top: auto; }
.contract-textarea :deep(.el-textarea__inner),
.intent-textarea :deep(.el-textarea__inner) { min-height: 150px !important; }

.contract-file-input { display: none; }
.contract-upload {
  min-height: 42px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 8px;
  border: 0;
  border-radius: 0;
  background: var(--bg-input);
  transition: border-color 0.16s ease, background-color 0.16s ease;
}
.contract-upload.dragging {
  border-color: var(--primary-color);
  background: var(--primary-fade);
}
.contract-upload.loading { opacity: 0.72; }
.contract-upload__icon {
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  display: inline-grid;
  place-items: center;
  border-radius: 5px;
  background: var(--surface-solid);
  color: var(--primary-color);
  box-shadow: 0 0 0 1px var(--border-light);
}
.contract-upload__copy {
  min-width: 0;
  flex: 1 1 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.contract-upload__copy strong,
.contract-upload__copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.contract-upload__copy strong { color: var(--text-primary); font-size: 11px; font-weight: 700; }
.contract-upload__copy small { color: var(--text-secondary); font-size: 10px; }
.contract-upload__copy .contract-upload__error { color: var(--el-color-danger); }
.contract-upload__actions { flex: 0 0 auto; display: inline-flex; align-items: center; gap: 6px; }

.acg-view > :deep(.workflow-review) { margin-top: var(--space-lg); }
.acg-grid { display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 11px; margin-top: 16px; align-items: stretch; min-width: 0; transition: grid-template-columns 180ms ease; }
.acg-grid.is-side-collapsed { grid-template-columns: minmax(0, 1fr) 44px; }
.grid-main { align-self: start; display: flex; flex-direction: column; gap: var(--space-lg); min-width: 0; }
.grid-side {
  position: sticky; top: 12px; align-self: start; box-sizing: border-box;
  height: calc(100dvh - 24px); max-height: calc(100dvh - 24px); min-width: 0; min-height: 0;
  overflow: hidden;
}
.grid-side__content {
  box-sizing: border-box; height: 100%; min-height: 0; display: flex; flex-direction: column; gap: var(--space-lg);
  overflow-y: auto; overscroll-behavior-y: auto; scrollbar-gutter: stable; scrollbar-width: thin;
}
.side-provenance { flex: 1 0 auto; min-height: 0; display: flex; min-width: 0; overflow: hidden; }
.side-provenance :deep(.acg-provenance) { flex: 1 1 auto; min-height: 0; border: 0; border-radius: 0; box-shadow: none; }
.side-provenance :deep(.panel-head) { padding: 14px 16px 10px; }
.side-provenance :deep(.tabs) { margin-right: 16px; margin-left: 16px; }
.side-provenance :deep(.tab-body) { padding: 0 16px 14px; }
.is-side-collapsed .grid-side { display: none; }
.grid-side :deep(.acg-provenance) { min-height: 0; }
.grid-side__metrics { flex: 0 0 auto; min-width: 0; }
.grid-side__audit { flex: 1 1 auto; min-width: 0; min-height: 360px; display: flex; }
.grid-side__audit :deep(.acg-provenance) { width: 100%; height: 100%; }
.grid-side > :deep(.runtime-audit-timeline) { flex: 0 0 auto; max-height: 380px; overflow: auto; }
.grid-side__collapse {
  min-height: 32px; display: inline-flex; align-items: center; justify-content: flex-start; gap: 6px;
  padding: 0 9px; border: 1px solid var(--border-light); border-radius: 7px;
  background: var(--surface-solid); color: var(--text-secondary); font: inherit; font-size: 11px; cursor: pointer;
  transition: border-color 140ms ease, color 140ms ease, background-color 140ms ease;
}
.grid-side__collapse:hover, .grid-side__collapse:focus-visible { border-color: var(--primary-line); background: var(--primary-fade); color: var(--primary-color); }
.side-rail {
  align-self: stretch; box-sizing: border-box; height: 100%; min-height: 176px; display: flex; flex-direction: column; align-items: stretch; gap: 6px;
  padding: 6px; border: 1px solid var(--border-light); border-radius: 8px; background: var(--surface-solid);
}
.side-rail button { border: 0; background: transparent; color: var(--text-secondary); font: inherit; cursor: pointer; }
.side-rail__toggle {
  width: 30px; height: 30px; display: inline-grid; place-items: center; border-radius: 6px !important;
  background: var(--primary-fade) !important; color: var(--primary-color) !important;
}
.side-rail button:focus-visible, .grid-side__collapse:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }

.schedule-strip { padding: var(--space-md); }
.schedule-strip h4 { margin: 0 0 var(--space-sm); font-size: 13px; font-weight: 700; color: var(--text-primary); }
.batch-row { display: flex; gap: var(--space-md); flex-wrap: wrap; }
.batch { display: flex; align-items: center; gap: 4px; padding: 4px 8px; background: var(--bg-input); border-radius: var(--radius-md); }
.batch-idx { font-size: 11px; color: var(--text-secondary); font-weight: 600; margin-right: 4px; }
.batch-node { font-size: 11px; padding: 2px 8px; background: var(--primary-fade); color: var(--primary-color); border-radius: 10px; font-family: monospace; }

.task-brief {
  min-height: 62px;
  display: grid;
  place-items: center;
  margin-top: var(--space-md);
  padding: 12px 20px;
  border-radius: var(--radius-lg);
}
.acg-view.is-draft > .task-brief { flex: 0 0 62px; margin-bottom: var(--space-md); }
.task-brief strong { color: var(--text-secondary); font-size: 13px; font-weight: 700; letter-spacing: .02em; }

@keyframes restore-pulse {
  to { opacity: 1; }
}

@media (max-width: 1160px) {
  .acg-grid { grid-template-columns: minmax(0, 1fr); }
  .acg-grid.is-side-collapsed { grid-template-columns: minmax(0, 1fr); }
  .side-rail { display: none; }
  .grid-side, .is-side-collapsed .grid-side { position: static; display: block; height: auto; max-height: none; overflow: visible; }
  .grid-side__content { height: auto; overflow: visible; }
  .side-provenance { flex: 0 0 auto; display: block; }
  .side-provenance :deep(.acg-provenance) { display: flex; }
  .grid-side__audit { min-height: 0; display: block; }
  .grid-side__audit :deep(.acg-provenance) { height: auto; }
  .grid-side__collapse { display: none; }
  .advanced-settings { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (prefers-reduced-motion: reduce) {
  .acg-grid { transition: none; }
  .advanced-settings { animation: none; }
}

@media (max-width: 720px) {
  :global(.resource-drawer) { width: 92vw !important; }
  .resource-drawer__body { padding-right: 16px; padding-left: 16px; }
  .ui-hero { flex-wrap: wrap; align-items: flex-start; }
  .hero-left { width: 100%; }
  .hero-right { justify-content: flex-start; width: 100%; flex-wrap: wrap; }
  .hero-run-chip code { max-width: 120px; }
  .contract-upload { align-items: flex-start; flex-wrap: wrap; }
  .contract-upload__copy { width: calc(100% - 34px); }
  .contract-upload__actions { width: 100%; padding-left: 34px; }
  .input-fields { grid-template-columns: 1fr; }
  .definition-pane { padding-top: 14px; }
  .advanced-settings { left: 0; right: auto; width: min(620px, calc(100vw - 32px)); grid-template-columns: 1fr; }
  .advanced-presets { grid-template-columns: 1fr; }
  .advanced-presets__options { grid-template-columns: 1fr; }
  .advanced-item--wide { grid-column: auto; }
  .ctrl-options > :deep(.el-button:last-child) { width: 100%; margin-left: 0; }
  .input-summary__copy { align-items: flex-start; flex-wrap: wrap; }
  .input-summary__copy small { width: 100%; white-space: normal; }
  .control-bar.collapsed { align-items: stretch; flex-direction: column; }
  .control-bar.collapsed .ctrl-options { width: 100%; }
}

@media (prefers-reduced-motion: reduce) {
  .input-panel-expandable { transition-duration: 1ms; }
}
</style>
