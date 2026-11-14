/** Adapted DSH region.ts/tool-pairing.ts. OScode checks actual IDs, not just a
 * count balance. Session surface events are replaced by immutable SDK input.
 */
import { CompactionError } from './contracts.ts'
import type { Message } from './contracts.ts'
import type { TokenMeter } from './token-meter.ts'

export function toolCalls(item: Message): string[] {
  if (item.type === 'function_call') return [String(item.call_id || '')]
  return (item.tool_calls || []).map((call: any) => String(call.id || ''))
}
export function resultId(item: Message): string | undefined {
  if (item.type === 'function_call_output') return String(item.call_id || '')
  if (item.role === 'tool') return String(item.tool_call_id || '')
}
export function balancedCuts(messages: Message[]): boolean[] {
  const pending = new Set<string>(), seen = new Set<string>(), cuts = [true]
  for (const item of messages) {
    for (const id of toolCalls(item)) {
      if (!id || seen.has(id)) throw new CompactionError('Duplicate or missing tool call ID')
      pending.add(id); seen.add(id)
    }
    const id = resultId(item)
    if (id !== undefined) {
      if (!pending.delete(id)) throw new CompactionError('Orphan or duplicate tool result')
    }
    cuts.push(pending.size === 0)
  }
  // GLM and similar replay protocols require the reasoning immediately before
  // a tool call. Never retain that call while summarizing away its reasoning.
  for (let i = 0; i < messages.length; i++) if (toolCalls(messages[i]).length) {
    let start = i
    while (start > 0 && messages[start - 1].type === 'reasoning') cuts[start--] = false
  }
  return cuts
}
export function unsafeResult(value: any): boolean {
  if (typeof value === 'string') {
    try { return unsafeResult(JSON.parse(value)) } catch { return /error|exception|failed|TOOL_OUTCOME_UNKNOWN/i.test(value) }
  }
  if (Array.isArray(value)) return value.some(unsafeResult)
  if (!value || typeof value !== 'object') return false
  if (value.error || value.isError || value.is_error || value.ok === false || value.timedOut === true
    || ['failed', 'error', 'denied', 'cancelled', 'running', 'pending', 'approval_required', 'unknown'].includes(value.status)) return true
  for (const key of ['exitCode', 'exit_code']) if (key in value && value[key] !== 0) return true
  if (typeof value.type === 'string' && !['text', 'input_text', 'output_text'].includes(value.type)) return true
  return Object.values(value).some(v => typeof v === 'object' && unsafeResult(v))
}
export function protectedItem(item: Message): boolean {
  if (['system', 'developer'].includes(item.role)) return true
  if (Array.isArray(item.content) && item.content.some((b: any) => !['text', 'input_text', 'output_text', 'reasoning_text'].includes(b.type))) return true
  if (resultId(item) !== undefined && (item.is_error || unsafeResult(item.output ?? item.content))) return true
  return !['message', 'function_call', 'function_call_output', 'reasoning'].includes(item.type || 'message')
}

/** Token-tail retention rounded to complete cycles, including a single long user turn. */
export function selectCycleRange(messages: Message[], meter: TokenMeter, retainTokens: number, recentGroups: number): [number, number] | undefined {
  return selectCycleRanges(messages, meter, retainTokens, recentGroups).sort((a,b) =>
    JSON.stringify(messages.slice(b[0],b[1])).length - JSON.stringify(messages.slice(a[0],a[1])).length)[0]
}
export function selectCycleRanges(messages: Message[], meter: TokenMeter, retainTokens: number, recentGroups: number): [number, number][] {
  const cuts = balancedCuts(messages)
  let keep = messages.length, tokens = 0, groups = 0
  while (keep > 0 && (tokens < retainTokens || groups < recentGroups || !cuts[keep])) {
    const item = messages[--keep]
    tokens += meter.message(item)
    if (resultId(item) !== undefined && cuts[keep + 1]) groups++
  }
  while (keep > 0 && !cuts[keep]) keep--
  const currentUser = messages.findLastIndex(m => m.role === 'user' && !String(m.content).startsWith('Historical conversation checkpoint'))
  // Current intent is retained verbatim even if the completed tool prefix is summarized.
  const protectedMessages = messages.map((m, i) => i === currentUser ? { ...m, role: 'developer' } : m)
  return unprotectedRanges(protectedMessages, keep, cuts)
}
export function selectRange(messages: Message[], meter: TokenMeter, retainTurns: number, retainTokens: number): [number, number] | undefined {
  const cuts = balancedCuts(messages)
  const users = messages.flatMap((m, i) => m.role === 'user' ? [i] : [])
  if (users.length <= retainTurns) return
  let keep = users[users.length - retainTurns]
  let accumulated = meter.messages(messages.slice(keep))
  while (keep > 0 && accumulated < retainTokens) accumulated += meter.message(messages[--keep])
  // Round toward the older head to preserve a complete turn and tool cycle.
  while (keep > 0 && (!cuts[keep] || messages[keep].role !== 'user')) keep--
  return unprotectedRange(messages, keep, cuts)
}

/** Explicit compaction may replace completed turns, including the latest one.
 * A trailing user request/tool cycle still belongs to the active turn.
 */
export function selectCompletedRange(messages: Message[]): [number, number] | undefined {
  return selectCompletedRanges(messages).sort((a,b) =>
    JSON.stringify(messages.slice(b[0],b[1])).length - JSON.stringify(messages.slice(a[0],a[1])).length)[0]
}
export function selectCompletedRanges(messages: Message[]): [number, number][] {
  const cuts = balancedCuts(messages), last = messages.at(-1)
  const completed = last?.role === 'assistant' && (last.type || 'message') === 'message'
    && toolCalls(last).length === 0 && cuts[messages.length]
  const lastUser = messages.findLastIndex(item => item.role === 'user')
  const keep = completed ? messages.length : Math.max(0, lastUser)
  return unprotectedRanges(messages, keep, cuts)
}

function unprotectedRange(messages: Message[], keep: number, cuts: boolean[]): [number, number] | undefined {
  return unprotectedRanges(messages,keep,cuts).sort((a,b) =>
    JSON.stringify(messages.slice(b[0],b[1])).length - JSON.stringify(messages.slice(a[0],a[1])).length)[0]
}
function unprotectedRanges(messages: Message[], keep: number, cuts: boolean[]): [number, number][] {
  const ranges: [number, number][] = []
  let start = 0, preserveAttachmentTurn = false
  // Choose the largest eligible run. A protected failure near the head must not
  // prevent all of the completed work after it from ever being summarized.
  const accept = (end: number) => {
    if (end > start) ranges.push([start,end])
  }
  for (let i = 0; i < keep;) {
    let end = i + 1
    while (end < keep && !cuts[end]) end++
    if (!cuts[end]) break
    const cycle = messages.slice(i,end)
    const users = cycle.filter(m=>m.role === 'user')
    if (users.length) preserveAttachmentTurn = users.some(m=>Array.isArray(m.content)
      && m.content.some((b:any)=>!['text','input_text','output_text'].includes(b.type)))
    if (preserveAttachmentTurn || cycle.some(protectedItem)) { accept(i); start = end }
    i = end
  }
  while (keep > start && !cuts[keep]) keep--
  accept(keep)
  return ranges
}
