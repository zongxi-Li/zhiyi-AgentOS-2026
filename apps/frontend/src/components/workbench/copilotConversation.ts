import type { CopilotAction, CopilotExchange } from '@/services/api/agentos/api/copilot'
import type { ModelOutputItem, ModelOutputMetrics } from '@/workbench/runtime/observation'

export interface CopilotConversationMessage {
  id: string
  role: string
  content: string
  time: string
  planner: boolean
  action?: CopilotAction
  receipt?: CopilotExchange['receipt']
  proposalId: string
  sourceRunId?: string
}

export function planningProfileText(metrics: ModelOutputMetrics) {
  const facts = [
    metrics.constraintCount != null ? `${metrics.constraintCount} 项约束` : '',
    metrics.requiredCapabilityCount != null ? `${metrics.requiredCapabilityCount} 项能力` : '',
    metrics.expectedArtifactCount != null ? `${metrics.expectedArtifactCount} 项交付物` : '',
  ].filter(Boolean)
  return facts.length ? `已梳理任务需求，识别出 ${facts.join('、')}。` : '已完成任务需求的初步梳理。'
}

// Describe recorded facts, without treating a finished model call as an accepted plan.
export function planningProgressText(item: ModelOutputItem) {
  switch (item.kind) {
    case 'profile_resolved': return planningProfileText(item.metrics)
    case 'stage_completed': {
      const stages: Record<string, string> = {
        intent_profile: '已完成任务目标与约束的初步梳理。',
        outline: '已生成任务步骤草案，后续还需补充细节并校验。',
        detail: '已生成步骤目标与验收标准，后续还需校验。',
        relations: '已生成步骤之间的依赖关系，后续还需校验。',
        decompose: '已生成任务步骤与规划依据，后续还需校验是否满足任务约束。',
        repair: '本轮规划修正已生成，仍需通过校验后才能进入执行。',
        'detail.repair': '本轮步骤细节修正已生成，仍需校验。',
        'relations.repair': '本轮依赖关系修正已生成，仍需校验。',
        repair_coverage: '本轮交付覆盖修正已生成，仍需校验。',
      }
      return stages[item.stage || ''] || `${item.title}。`
    }
    case 'plan_parsed': return item.metrics.taskCount != null
      ? `已解析 ${item.metrics.taskCount} 个任务步骤${item.metrics.dependencyCount != null ? `和 ${item.metrics.dependencyCount} 条依赖关系` : ''}。`
      : '已解析任务步骤与依赖关系。'
    case 'graph_compiled': return '已完成任务图编译，执行前仍需确认规划与授权。'
    case 'completed': return '初步规划已生成，正在载入可供确认的版本。'
    case 'retry': return '本轮规划请求正在重试，后续结果会继续显示在这里。'
    case 'failed': return '本次规划未完成，暂时无法进入执行。'
    default: return `${item.title}。`
  }
}
