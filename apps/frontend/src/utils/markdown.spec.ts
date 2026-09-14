import { describe, expect, it } from 'vitest'
import { renderMarkdown } from './markdown'

describe('renderMarkdown 数学公式', () => {
  it('渲染块级 $$..$$ 公式为 KaTeX HTML', () => {
    const html = renderMarkdown('$$PE_{(pos, 2i)} = \\sin\\left(\\frac{pos}{10000^{2i/d_{model}}}\\right)$$')
    expect(html).toContain('katex-display')
    expect(html).toContain('katex')
    expect(html).not.toContain('$$')
  })

  it('渲染独占多行的 $$ 块（开闭各占一行）', () => {
    const html = renderMarkdown('前文\n\n$$\nPE_{(pos, 2i)} = \\cos(pos)\n$$\n\n后文')
    expect(html).toContain('katex-display')
    expect(html).toContain('<p>前文</p>')
    expect(html).toContain('<p>后文</p>')
    expect(html).not.toContain('$$')
  })

  it('渲染 \\[..\\] 块级公式', () => {
    const html = renderMarkdown('\\[\\sin(pos+k) = \\sin(pos)\\cos(k) + \\cos(pos)\\sin(k)\\]')
    expect(html).toContain('katex-display')
    expect(html).not.toContain('\\[')
  })

  it('渲染行内 \\(..\\) 公式', () => {
    const html = renderMarkdown('位置 \\(pos\\) 从零开始')
    expect(html).toContain('katex')
    expect(html).not.toContain('\\(pos\\)')
    expect(html).toContain('位置 ')
    expect(html).toContain(' 从零开始')
  })

  it('渲染行内 $..$ 公式', () => {
    const html = renderMarkdown('维度索引 $2i$ 与 $2i+1$ 共用同一频率')
    expect(html).toContain('katex')
    expect(html).not.toContain('$2i$')
  })

  it('流式未闭合的 $$ 保持原样，不渲染也不抛错', () => {
    const html = renderMarkdown('$$PE_{(pos, 2i)} = \\sin')
    expect(html).not.toContain('katex')
    expect(html).toContain('$$PE_{(pos, 2i)}')
  })

  it('围栏代码块内的 $$ 不当作公式', () => {
    const html = renderMarkdown('```\n$$x^2$$\n```')
    expect(html).not.toContain('katex')
    expect(html).toContain('<pre><code>')
    expect(html).toContain('$$x^2$$')
  })

  it('行内代码内的 $..$ 不当作公式', () => {
    const html = renderMarkdown('写作 `$x^2$` 即可')
    expect(html).not.toContain('katex')
    expect(html).toContain('<code>$x^2$</code>')
  })

  it('货币类 $100 不误判为公式', () => {
    const html = renderMarkdown('价格 $100，成本 $50')
    expect(html).not.toContain('katex')
    expect(html).toContain('$100，成本 $50')
  })

  it('表格单元格内的公式正常渲染', () => {
    const html = renderMarkdown('| 公式 | 值 |\n|---|---|\n| $x^2$ | 4 |')
    expect(html).toContain('markdown-table-wrap')
    expect(html).toContain('katex')
  })

  it('行内公式不残留 @ 占位符', () => {
    const html = renderMarkdown('公式 $x^2$ 与代码 `$y$` 混排')
    expect(html).not.toContain('@@MATH_')
    expect(html).not.toContain('@@INLINE_CODE_')
  })
})

describe('renderMarkdown 既有行为回归', () => {
  it('粗体/斜体/链接不受公式管线影响', () => {
    const html = renderMarkdown('**加粗** *斜体* [链接](https://example.com)')
    expect(html).toContain('<strong>加粗</strong>')
    expect(html).toContain('<em>斜体</em>')
    expect(html).toContain('href="https://example.com"')
  })

  it('行内代码内容被转义且不再嵌套加粗', () => {
    const html = renderMarkdown('`<b>**x**</b>`')
    expect(html).toContain('<code>&lt;b&gt;**x**&lt;/b&gt;</code>')
    expect(html).not.toContain('<strong>')
  })
})
