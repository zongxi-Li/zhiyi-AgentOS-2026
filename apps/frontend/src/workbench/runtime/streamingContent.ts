/** Read public narrative values from unfinished JSON without showing its wire format. */
const privateKey = /reasoning|chain.?of.?thought|prompt|secret|password|api[_-]?key|authorization|access[_-]?token|credential/i
const narrativeKey = /^(?:answer|final_answer|finalAnswer|final_report|report_markdown|report|task_summary|summary|overview|description|content|text|title|name|objective|primaryGoal|keyConstraints|expectedArtifacts|acceptanceCriteria|decompositionRationale|producedArtifacts|analysis|conclusion|rationale|explanation|finding|findings|recommendation|recommendations|assumptions|constraints|success_criteria|open_questions|criterion|result|evidence|unresolvedGaps|unresolved_gaps|risks|notes)$/

export function planningContent(value: string): string {
  const source = value.trimStart()
  // A tail-truncated planning buffer has no reliable JSON field boundary.
  return /^(?:\{|\[|```json)/.test(source) ? streamingContent(source) : ''
}

const sectionLabels: Record<string, string> = {
  objective: '任务目标', primaryGoal: '任务目标', overview: '概述', summary: '摘要', task_summary: '步骤摘要',
  acceptanceCriteria: '验收条件', success_criteria: '验收条件', keyConstraints: '约束', constraints: '约束',
  findings: '分析发现', evidence: '依据', recommendations: '建议', risks: '风险', assumptions: '假设',
  open_questions: '待确认问题', unresolvedGaps: '待补充内容', unresolved_gaps: '待补充内容',
  expectedArtifacts: '预期交付物', producedArtifacts: '交付物', sources: '参考材料', sourceRefs: '参考材料',
  rationale: '处理依据', decompositionRationale: '规划依据', conclusion: '结论', notes: '补充说明',
}

export function streamingContent(value: string, structured = false): string {
  const source = value.slice(0, 65536).trimStart().replace(/^```(?:json)?\s*/, '')
  if (!source.startsWith('{') && !source.startsWith('[')) return privateKey.test(source) ? '' : source
  let at = 0
  const parts: string[] = []
  const whitespace = () => { while (at < source.length && /\s/.test(source[at])) at++ }
  function string(): { text: string; closed: boolean } {
    at++
    let text = ''
    while (at < source.length) {
      const char = source[at++]
      if (char === '"') return { text, closed: true }
      if (char !== '\\') { text += char; continue }
      const escape = source[at++]
      if (escape === 'u') {
        const hex = source.slice(at, at + 4)
        if (!/^[0-9a-f]{4}$/i.test(hex)) break
        text += String.fromCharCode(parseInt(hex, 16)); at += 4
      } else {
        const escapes: Record<string, string> = { '"': '"', '\\': '\\', '/': '/', n: '\n', r: '\r', t: '\t', b: '\b', f: '\f' }
        if (!(escape in escapes)) break
        text += escapes[escape]
      }
    }
    return { text: text.replace(/[\uD800-\uDBFF]$/, ''), closed: false }
  }
  function read(visible: boolean, narrative = false, depth = 0, listItem = false): void {
    if (depth > 24 || at >= source.length) return
    whitespace()
    if (source[at] === '"') {
      const item = string()
      if (visible && narrative && item.text.trim()) {
        const text = structured && item.text === 'User-provided task materials' ? '用户提供的任务材料' : item.text
        parts.push(structured && listItem ? `- ${text}` : text)
      }
    } else if (source[at] === '{') {
      at++; whitespace()
      while (at < source.length && source[at] !== '}') {
        if (source[at] !== '"') return
        const key = string()
        if (!key.closed) return
        whitespace()
        if (source[at++] !== ':') return
        const publicField = visible && !privateKey.test(key.text)
        const start = parts.length
        const label = structured && publicField ? sectionLabels[key.text] : undefined
        if (label) parts.push(`### ${label}`)
        read(publicField, narrativeKey.test(key.text), depth + 1)
        if (label && parts.length === start + 1) parts.pop()
        whitespace()
        if (source[at] !== ',') break
        at++; whitespace()
      }
      if (source[at] === '}') at++
    } else if (source[at] === '[') {
      at++; whitespace()
      while (at < source.length && source[at] !== ']') {
        const start = at
        read(visible, narrative, depth + 1, true)
        if (at === start) return
        whitespace()
        if (source[at] !== ',') break
        at++; whitespace()
      }
      if (source[at] === ']') at++
    } else {
      while (at < source.length && !/[\s,\]}]/.test(source[at])) at++
    }
  }
  read(true)
  return parts.join('\n\n')
}
