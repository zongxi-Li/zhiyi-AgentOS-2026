import type { AcgStepState } from '@/services/api/agentos'

export const mapNodeVisualState = (step?: AcgStepState) => ({
  status: step?.status || 'pending',
  runtimeAdded: (step?.createdGraphVersion ?? 1) > 1,
  bindingSwitched: (step?.bindingHistory?.length ?? 0) > 1,
  conditionalSkipped: step?.status === 'skipped_by_condition',
  targetRetried: (step?.attempt ?? 0) > 1
})

export const mapEdgeVisualState = (activation?: string) => {
  const normalized = String(activation || 'active').toLowerCase()
  return ['inactive', 'terminated', 'superseded'].includes(normalized) ? normalized : 'active'
}
