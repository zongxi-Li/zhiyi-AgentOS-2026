/** Read public narrative values from unfinished JSON without showing its wire format. */
const privateKey = /reasoning|chain.?of.?thought|prompt|secret|password|api[_-]?key|authorization|access[_-]?token|credential/i
const narrativeKey = /^(?:answer|final_answer|finalAnswer|final_report|report_markdown|report|task_summary|summary|overview|description|content|text|title|name|objective|primaryGoal|keyConstraints|expectedArtifacts|acceptanceCriteria|decompositionRationale|producedArtifacts|analysis|conclusion|rationale|explanation|finding|findings|recommendation|recommendations|assumptions|constraints|success_criteria|open_questions|criterion|result|evidence|unresolvedGaps|unresolved_gaps|risks|notes)$/

export function planningContent(value: string): string {
  const source = value.trimStart()
  // A tail-truncated planning buffer has no reliable JSON field boundary.
  return /^(?:\{|\[|```json)/.test(source) ? streamingContent(source) : ''
}

export function streamingContent(value: string): string {
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
  function read(visible: boolean, narrative = false, depth = 0): void {
    if (depth > 24 || at >= source.length) return
    whitespace()
    if (source[at] === '"') {
      const item = string()
      if (visible && narrative && item.text.trim()) parts.push(item.text)
    } else if (source[at] === '{') {
      at++; whitespace()
      while (at < source.length && source[at] !== '}') {
        if (source[at] !== '"') return
        const key = string()
        if (!key.closed) return
        whitespace()
        if (source[at++] !== ':') return
        read(visible && !privateKey.test(key.text), narrativeKey.test(key.text), depth + 1)
        whitespace()
        if (source[at] !== ',') break
        at++; whitespace()
      }
      if (source[at] === '}') at++
    } else if (source[at] === '[') {
      at++; whitespace()
      while (at < source.length && source[at] !== ']') {
        const start = at
        read(visible, narrative, depth + 1)
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
