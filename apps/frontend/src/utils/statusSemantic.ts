// Semantic status system — the single status→tone mapping for the Workbench.
// Tones resolve to CSS variables defined in styles/global.css (--sem-*), so
// components must color through var(--tone) / .tone-* classes instead of
// hardcoding hues. Hue assignments follow the semantic color contract:
//   success → green, running/active → blue, waiting/pending → yellow,
//   retry/degraded → orange, failed/error/conflict → red,
//   artifact/canonical/control → purple, communication/data flow → cyan.

export type SemanticTone =
  | 'success'
  | 'running'
  | 'waiting'
  | 'retry'
  | 'failed'
  | 'artifact'
  | 'flow'
  | 'muted'

const TONE_PATTERN: Array<[RegExp, SemanticTone]> = [
  [/^(succeeded|success|completed|complete|done|committed|available|online|passed|verified|healthy)$/, 'success'],
  [/^(running|active|planning|executing|executed|processing|in_progress|inprogress|started)$/, 'running'],
  [/^(pending|waiting|waiting_review|queued|paused|prepared|scheduled|unproven)$/, 'waiting'],
  [/^(retrying|retry|retried|degraded|recovering|recovered|fallback|restore)$/, 'retry'],
  [/^(failed|failure|error|conflict|violated|violation|rejected|cancelled|canceled|offline)$/, 'failed'],
  [/^(canonical|artifact|control)$/, 'artifact']
]

// Compound keys (contract_violation, run_recovered, step_failed…) fall through
// the exact-match pass and resolve by substring. Order matters: recovery and
// degradation outrank failure so run_recovered stays in the retry family.
const TONE_SUBSTRING: Array<[RegExp, SemanticTone]> = [
  [/recover|degrad|retry|fallback/, 'retry'],
  [/violation|conflict|fail|error|cancel/, 'failed'],
  [/waiting|pending|queued|paused/, 'waiting'],
  [/running|active|execut/, 'running'],
  [/complet|succeed|committed|verified|passed/, 'success']
]

export function statusSemanticTone(status?: string | null): SemanticTone {
  const key = (status || '').trim().toLowerCase()
  if (!key) return 'muted'
  for (const [pattern, tone] of TONE_PATTERN) {
    if (pattern.test(key)) return tone
  }
  for (const [pattern, tone] of TONE_SUBSTRING) {
    if (pattern.test(key)) return tone
  }
  return 'muted'
}

const TONE_COLOR: Record<SemanticTone, string> = {
  success: 'var(--sem-success)',
  running: 'var(--sem-running)',
  waiting: 'var(--sem-waiting)',
  retry: 'var(--sem-retry)',
  failed: 'var(--sem-failed)',
  artifact: 'var(--sem-artifact)',
  flow: 'var(--sem-flow)',
  muted: 'var(--wb-text-muted)'
}

export function toneClass(tone: SemanticTone): string {
  return `tone-${tone}`
}

export function statusToneClass(status?: string | null): string {
  return toneClass(statusSemanticTone(status))
}

export function statusSemanticColor(status?: string | null): string {
  const tone = statusSemanticTone(status)
  return TONE_COLOR[tone]
}
