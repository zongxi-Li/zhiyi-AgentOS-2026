/** OScode-owned contracts, independent of Cordis, DSH Session and any Provider. */
export type Message = Record<string, any>
export const VERSION = 'oscode-context.v2'
export const SUMMARY_FIELDS = ['goals', 'facts', 'constraints', 'completed', 'decisions', 'unresolved', 'references', 'tool_results'] as const
export type Summary = Record<typeof SUMMARY_FIELDS[number], string[]>
export type Summarize = (text: string, maxTokens: number, instruction: string) => Promise<{ text: string; totalTokens?: number }>

export interface Budget {
  contextWindow: number
  outputReserve: number
  safetyMargin: number
  /** Optional latency-oriented soft budget; never changes model capacity. */
  workingSetTriggerTokens?: number
  workingSetTargetTokens?: number
}
export interface Config {
  triggerRatio: number
  targetRatio: number
  retainTurns: number
  retainRatio: number
  recentToolGroups: number
  recentTailTokens: number
  summaryMaxTokens: number
  maxSummaryCalls: number
  thresholdChars: number
  headChars: number
  tailChars: number
}
export const DEFAULTS: Readonly<Config> = Object.freeze({
  triggerRatio: .85, targetRatio: .65, retainTurns: 2, retainRatio: .20,
  recentToolGroups: 0, recentTailTokens: 0,
  // The fallback meter counts UTF-8 bytes; 2048 was too small for eight
  // multilingual fields. The engine still caps this by actual savings/window.
  summaryMaxTokens: 8192, maxSummaryCalls: 16,
  thresholdChars: 8192, headChars: 4096, tailChars: 1024,
})
export interface ProjectionRequest {
  /** Explicit /compact request; still respects protected turns and hard limits. */
  force?: boolean
  /** Local preparation can run independently of auxiliary model calls. */
  localOnly?: boolean
  summaryCallsRemaining?: number
  /** Host-validated same-route provider baseline plus newly appended input. */
  sourceUsage?: { inputTokens: number; sourceHash: string; tokenMethod: string }
  contextId: string
  provider: string
  model: string
  messages: Message[]
  instructions: string
  tools: Record<string, unknown>[]
  budget: Budget
}
export interface Projection {
  messages: Message[]
  status: 'unchanged' | 'pruned' | 'summarized' | 'no_safe_range' | 'failed_passthrough'
  metrics: Record<string, number | string | boolean>
  snapshot?: Record<string, unknown>
}
export class CompactionError extends Error {
  readonly code: string
  constructor(message: string, options?: ErrorOptions & { code?: string }) {
    super(message, options)
    this.name = 'CompactionError'
    this.code = options?.code || 'COMPACTION_VALIDATION_FAILED'
  }
}

/** DSH model-window/output-reserve budgeting, with a separate safety margin. */
export function inputLimit(budget: Budget): number {
  const { contextWindow, outputReserve, safetyMargin } = budget
  if (![contextWindow, outputReserve, safetyMargin].every(Number.isSafeInteger)
    || contextWindow < 1 || outputReserve < 1 || safetyMargin < 0
    || outputReserve + safetyMargin >= contextWindow) throw new CompactionError('Invalid context budget')
  return contextWindow - outputReserve - safetyMargin
}
export function workingLimits(budget: Budget, config: Config): { trigger: number; target: number } {
  const hard = inputLimit(budget)
  for (const value of [budget.workingSetTriggerTokens, budget.workingSetTargetTokens]) {
    if (value !== undefined && (!Number.isSafeInteger(value) || value < 1)) throw new CompactionError('Invalid working budget')
  }
  if (budget.workingSetTargetTokens !== undefined && budget.workingSetTriggerTokens !== undefined
    && budget.workingSetTargetTokens >= budget.workingSetTriggerTokens) throw new CompactionError('Invalid working hysteresis')
  const trigger = Math.min(Math.floor(hard * config.triggerRatio), budget.workingSetTriggerTokens ?? hard)
  const target = Math.min(Math.floor(hard * config.targetRatio), budget.workingSetTargetTokens ?? hard, trigger - 1)
  return { trigger, target }
}
export function resolveConfig(overrides: Partial<Config> = {}): Config {
  for (const key of Object.keys(overrides)) if (!(key in DEFAULTS)) throw new CompactionError(`Unknown compaction config ${key}`)
  const config = { ...DEFAULTS, ...overrides }
  if (!(config.targetRatio > 0 && config.targetRatio < config.triggerRatio && config.triggerRatio < 1)
    || !(config.retainRatio >= 0 && config.retainRatio < config.targetRatio)) throw new CompactionError('Invalid hysteresis/retention ratios')
  for (const key of ['retainTurns', 'summaryMaxTokens', 'maxSummaryCalls', 'thresholdChars'] as const) {
    if (!Number.isSafeInteger(config[key]) || config[key] < 1) throw new CompactionError(`Invalid ${key}`)
  }
  for (const key of ['headChars', 'tailChars', 'recentToolGroups', 'recentTailTokens'] as const) if (!Number.isSafeInteger(config[key]) || config[key] < 0) throw new CompactionError(`Invalid ${key}`)
  if (config.headChars + config.tailChars + 50 > config.thresholdChars) throw new CompactionError('Pruning replacement exceeds threshold')
  return config
}
