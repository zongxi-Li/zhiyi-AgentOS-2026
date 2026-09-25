import { computed, type ComputedRef, type Ref } from 'vue'
import type { AcgDeliverable, AcgFinalArtifact, AcgView, WorkflowRun } from '@/services/api/agentos'
import type { WorkflowProgress } from '@/services/api/workflow'
import type { Message } from '@/stores/chat'
import { resolveAcgTaskTitle } from '@/utils/acgTaskTitle'

type ContextTabKey = 'lineage' | 'nodes' | 'steps'

interface UseChatWorkflowPresentationOptions {
  activeWorkflowRun: Ref<WorkflowRun | null>
  activeAcgView: Ref<AcgView | null>
  activeWorkflowRunId: Ref<string>
  progress: { readonly value: Readonly<Pick<WorkflowProgress, 'status'>> | null }
  messages: ComputedRef<Message[]>
}

export function useChatWorkflowPresentation({
  activeWorkflowRun,
  activeAcgView,
  activeWorkflowRunId,
  progress,
  messages
}: UseChatWorkflowPresentationOptions) {
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
    progress.value?.status
    || activeWorkflowRun.value?.status
    || activeAcgView.value?.status
    || [...messages.value].reverse().find(message => message.workflowRunId === activeWorkflowRunId.value)?.workflowStatus
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
  ] satisfies Array<{ key: ContextTabKey; label: string; count: number }>)
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

  return {
    displayAcgBlueprint,
    displayCompletedStepIds,
    activeAcgAuditEvents,
    contextNodes,
    contextEdges,
    contextStepNodes,
    contextObjective,
    workflowHistoryInput,
    workflowHistoryTitle,
    workflowHistoryStepOutputs,
    workflowHistoryFinalArtifacts,
    workflowHistoryFinalReport,
    activeWorkflowStatus,
    activeWorkflowStatusLabel,
    contextTabs,
    contextNodeLabel,
    contextEdgeLabel,
    contextNodeTypeLabel
  }
}
