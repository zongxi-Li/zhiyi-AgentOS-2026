import { describe, expect, it } from 'vitest'
import { renderMarkdown } from './markdown'

describe('renderMarkdown paragraph flow', () => {
  it('keeps soft line breaks within one paragraph instead of adding a gap after every line', () => {
    const html = renderMarkdown('先检查任务约束，\n再分析策略冲突与依赖。\n最后说明需要用户确认的取舍。')
    expect(html.match(/<p>/g)).toHaveLength(1)
    expect(html).toContain('先检查任务约束，\n再分析策略冲突与依赖。\n最后说明需要用户确认的取舍。')
    expect(html).not.toContain('<br>')
  })

  it('retains intentional blank paragraphs and explicit hard breaks', () => {
    const html = renderMarkdown('第一段\n延续第一段\n\n第二段  \n第二段换行\\\n末行')
    expect(html.match(/<p>/g)).toHaveLength(2)
    expect(html).toContain('<p>第一段\n延续第一段</p>')
    expect(html).toContain('<p>第二段<br>\n第二段换行<br>\n末行</p>')
  })

  it('separates prose, lists, headings, tables and code without turning each prose line into a paragraph', () => {
    const html = renderMarkdown('已调整的区域：\n- 移除不可点击的标签\n- 保留当前进展\n\n接下来检查\n实际页面。\n## 验证\n| 项目 | 状态 |\n|---|---|\n| 布局 | 正常 |\n```text\n原样\n保留换行\n```')
    expect(html).toContain('<p>已调整的区域：</p>\n<ul>')
    expect(html).toContain('<p>接下来检查\n实际页面。</p>\n<h2>验证</h2>')
    expect(html.match(/<li>/g)).toHaveLength(2)
    expect(html).toContain('<table>')
    expect(html).toContain('原样\n保留换行')
  })
})

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
  it('renders task list items as disabled document checkboxes', () => {
    const html = renderMarkdown('- [x] 已完成\n- [ ] 待复核')
    expect(html).toContain('class="markdown-task-item"')
    expect(html).toContain('type="checkbox" disabled checked')
    expect(html).toContain('待复核')
  })

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

describe('renderMarkdown 连续重复标题折叠', () => {
  it('逐字相同的连续标题（中间仅空行）只渲染一次', () => {
    const html = renderMarkdown('# 报告标题\n\n# 报告标题\n\n正文段落')
    expect(html.match(/<h1>报告标题<\/h1>/g)).toHaveLength(1)
    expect(html).toContain('<p>正文段落</p>')
  })

  it('相同标题被正文隔开后正常保留', () => {
    const html = renderMarkdown('# 小结\n\n正文内容\n\n# 小结\n\n尾注')
    expect(html.match(/<h1>小结<\/h1>/g)).toHaveLength(2)
  })

  it('同文字不同级别或隔代码块的标题不折叠', () => {
    const html = renderMarkdown('# 标题\n\n## 标题\n\n```js\nconst a = 1\n```\n\n# 标题\n\n尾注')
    expect(html.match(/<h1>标题<\/h1>/g)).toHaveLength(2)
    expect(html.match(/<h2>标题<\/h2>/g)).toHaveLength(1)
  })
})
