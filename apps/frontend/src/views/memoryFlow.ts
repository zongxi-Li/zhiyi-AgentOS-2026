import type {
  MemoryAccessEvent,
  MemoryWriteEvent,
  PhaseCapsuleEvent,
  RunMemoryEvent
} from '@/services/api/agentos'

export interface MemoryStepGroup {
  stepId: string
  access: MemoryAccessEvent | null
  write: MemoryWriteEvent | null
  createdAt: string
}

export interface MemoryFlowEdge {
  sourceStepId: string
  targetStepId: string
}

export interface MemoryFlowStats {
  reads: number
  writes: number
  capsules: number
  hitRefs: number
  hitEdges: number
}

export interface MemoryFlowProjection {
  steps: MemoryStepGroup[]
  capsules: PhaseCapsuleEvent[]
  edges: MemoryFlowEdge[]
  stats: MemoryFlowStats
}

const UNKNOWN_STEP = '__unknown__'

function accessStepId(item: MemoryAccessEvent): string {
  return item.stepId?.trim() || UNKNOWN_STEP
}

function writeStepId(item: MemoryWriteEvent): string {
  return item.stepId?.trim() || UNKNOWN_STEP
}

/** `memory:{runId}:{stepId}` → stepId；冒号后面的全部归 stepId，避免误切。 */
export function stepIdFromMemoryRef(ref: string): string | null {
  const parts = ref.split(':')
  if (parts.length < 3 || parts[0] !== 'memory' || !parts[2]) {
    return null
  }
  return parts.slice(2).join(':')
}

export function shortStepLabel(stepId: string): string {
  return stepId
    .replace(/^native_general_agent_(?=.)/, 'agent ')
    .replace(/^native_general_agent$/, 'agent')
    .replace(/^ctrl_/, 'ctrl ')
}

export function projectMemoryFlow(items: RunMemoryEvent[]): MemoryFlowProjection {
  const groups = new Map<string, MemoryStepGroup>()
  const capsules: PhaseCapsuleEvent[] = []
  const edges: MemoryFlowEdge[] = []
  let reads = 0
  let writes = 0
  let hitRefs = 0
  const seenEdges = new Set<string>()

  const groupOf = (stepId: string, createdAt: string): MemoryStepGroup => {
    const existing = groups.get(stepId)
    if (existing) {
      if (createdAt && (!existing.createdAt || createdAt < existing.createdAt)) {
        existing.createdAt = createdAt
      }
      return existing
    }
    const created: MemoryStepGroup = { stepId, access: null, write: null, createdAt }
    groups.set(stepId, created)
    return created
  }

  for (const item of items) {
    const createdAt =
      (item.kind === 'memory_access' ? item.createdAt : null) ??
      (item.kind === 'memory_event' ? asString(item.createdAt) : null) ??
      ''
    if (item.kind === 'memory_access') {
      reads += 1
      const group = groupOf(accessStepId(item), createdAt)
      // 同一步骤多次召回保留信息量最大的一次（命中数优先，再比时间）。
      if (!group.access || (item.hitRefs?.length ?? 0) >= group.access.hitRefs.length) {
        group.access = item
      }
      hitRefs += item.hitRefs?.length ?? 0
      for (const ref of item.hitRefs ?? []) {
        const sourceStepId = stepIdFromMemoryRef(ref)
        if (!sourceStepId || sourceStepId === group.stepId) {
          continue
        }
        const key = `${sourceStepId}→${group.stepId}`
        if (!seenEdges.has(key)) {
          seenEdges.add(key)
          edges.push({ sourceStepId, targetStepId: group.stepId })
        }
      }
    } else if (item.kind === 'memory_event') {
      writes += 1
      const group = groupOf(writeStepId(item), createdAt)
      group.write = item
    } else if (item.kind === 'phase_capsule') {
      capsules.push(item)
    }
  }

  const steps = [...groups.values()].sort((a, b) => {
    if (a.createdAt !== b.createdAt) {
      return a.createdAt < b.createdAt ? -1 : 1
    }
    return a.stepId.localeCompare(b.stepId)
  })

  return {
    steps,
    capsules,
    edges,
    stats: { reads, writes, capsules: capsules.length, hitRefs, hitEdges: edges.length }
  }
}

function asString(value: unknown): string | null {
  return typeof value === 'string' ? value : null
}
