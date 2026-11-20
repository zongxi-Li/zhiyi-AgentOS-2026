import { describe, expect, it } from 'vitest'
import { renderCopilotMarkdown } from './copilotMarkdown'

const parse = (source: string) => {
  const el = document.createElement('div')
  el.innerHTML = renderCopilotMarkdown(source)
  return el
}

describe('Copilot keyword accents', () => {
  it('uses three restrained categories and matches compound keywords once', () => {
    const el = parse('核对权限边界与审计，明确验收标准，标记高风险和冲突。')
    expect([...el.querySelectorAll('.copilot-keyword')].map(span => [span.textContent, span.className])).toEqual([
      ['权限边界', 'copilot-keyword copilot-keyword--security'], ['审计', 'copilot-keyword copilot-keyword--security'],
      ['验收标准', 'copilot-keyword copilot-keyword--verification'], ['高风险', 'copilot-keyword copilot-keyword--attention'],
      ['冲突', 'copilot-keyword copilot-keyword--attention'],
    ])
    expect(el.textContent).toBe('核对权限边界与审计，明确验收标准，标记高风险和冲突。')
  })

  it('preserves code, links, math and Markdown emphasis', () => {
    const el = parse('**权限** [测试](https://example.com/测试) `风险`\n\n```text\n安全测试\n```\n\n$风险$')
    expect(el.querySelector('strong .copilot-keyword--security')).not.toBeNull()
    expect(el.querySelector('a .copilot-keyword, code .copilot-keyword, .katex .copilot-keyword')).toBeNull()
    expect(el.querySelector('a')?.getAttribute('href')).toBe('https://example.com/测试')
  })

  it('keeps escaped source text inert and does not change paragraph or list structure', () => {
    const el = parse('安全 <img src=x onerror=alert(1)>\n仍是同一段\n\n- 测试\n- 风险')
    expect(el.querySelector('img')).toBeNull()
    expect(el.textContent).toContain('<img src=x onerror=alert(1)>')
    expect(el.querySelectorAll('p')).toHaveLength(1)
    expect(el.querySelectorAll('ul')).toHaveLength(1)
    expect(el.querySelectorAll('li')).toHaveLength(2)
  })
})
