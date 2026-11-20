import { renderMarkdown } from '@/utils/markdown'

const keywordGroups = {
  security: ['权限边界', '访问控制', '安全评审', '安全设计', '安全', '权限', '审计'],
  verification: ['验收标准', '验收条件', '测试验收', '测试结果', '验收', '测试', '验证'],
  attention: ['高风险', '风险', '冲突', '异常', '失败', '阻塞'],
} as const
const tones = new Map<string, string>(Object.entries(keywordGroups).flatMap(([tone, terms]) => terms.map(term => [term, tone] as const)))
const keywords = [...tones.keys()].sort((a, b) => b.length - a.length)
const pattern = new RegExp(keywords.join('|'), 'g')

/** Decorate only prose text; Markdown continues to own escaping and structure. */
export function renderCopilotMarkdown(source: string): string {
  const html = renderMarkdown(source)
  if (!keywords.some(keyword => source.includes(keyword))) return html
  const template = document.createElement('template')
  template.innerHTML = html
  const walker = document.createTreeWalker(template.content, NodeFilter.SHOW_TEXT)
  const nodes: Text[] = []
  while (walker.nextNode()) {
    const node = walker.currentNode as Text
    if (!node.parentElement?.closest('pre, code, a, .katex, math, svg')) nodes.push(node)
  }
  for (const node of nodes) {
    const text = node.data
    const matches = [...text.matchAll(pattern)]
    if (!matches.length) continue
    const fragment = document.createDocumentFragment()
    let end = 0
    for (const match of matches) {
      fragment.append(text.slice(end, match.index))
      const span = document.createElement('span')
      span.className = `copilot-keyword copilot-keyword--${tones.get(match[0])}`
      span.textContent = match[0]
      fragment.append(span)
      end = match.index! + match[0].length
    }
    fragment.append(text.slice(end))
    node.replaceWith(fragment)
  }
  return template.innerHTML
}
