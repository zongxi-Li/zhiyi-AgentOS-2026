import katex from 'katex'
import 'katex/dist/katex.min.css'

// 依次匹配：块级 $$..$$、块级 \[..\]、行内 \(..\)、行内 $..$。
// 块级允许跨行；行内 $..$ 不允许跨行，且在 replace 回调里做防误伤检查（见下）。
const MATH_PATTERN = /\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|\$([^$\n]+?)\$/g

const escapeHtml = (raw: string) => raw
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#39;')

const renderTex = (tex: string, displayMode: boolean) => {
  try {
    // throwOnError: false 让坏公式渲染成红色报错文本而不是抛异常
    return katex.renderToString(tex, { displayMode, throwOnError: false, strict: false })
  } catch {
    return `<span class="math-render-error">${escapeHtml(displayMode ? `$$${tex}$$` : `$${tex}$`)}</span>`
  }
}

export interface MathPass {
  /** 数学片段已替换为 @@MATH_N@@ 占位符的文本 */
  text: string
  /** 把占位符换回 KaTeX HTML（必须在代码块恢复之前调用，避免误替换代码里的字面占位符） */
  restore: (html: string) => string
}

/**
 * 把文本中的 LaTeX 公式渲染成 KaTeX HTML 并替换为占位符，
 * 使其不经过后续 Markdown 行内规则的转义与格式化。
 * 流式场景下未闭合的定界符不匹配任何规则，保持原样输出，闭合后自然成型。
 */
export const extractMath = (input: string): MathPass => {
  const rendered: string[] = []

  const stash = (tex: string, displayMode: boolean) => {
    const token = `@@MATH_${rendered.length}@@`
    rendered.push(renderTex(tex.trim(), displayMode))
    return token
  }

  const text = input.replace(MATH_PATTERN, (match, dollarBlock, bracketBlock, parenInline, dollarInline, offset: number) => {
    if (dollarBlock !== undefined) return stash(dollarBlock, true)
    if (bracketBlock !== undefined) return stash(bracketBlock, true)
    if (parenInline !== undefined) return stash(parenInline, false)

    // 行内 $..$ 防误伤：前一个字符是 $ 或 \（转义/相邻定界符）、
    // 内容以空白开头或结尾、闭合 $ 后紧跟数字（如“$100，成本 $50”）时不当作公式
    const previous = offset > 0 ? input.charAt(offset - 1) : ''
    const next = input.charAt(offset + match.length)
    if (previous === '$' || previous === '\\') return match
    if (/^\s/.test(dollarInline) || /\s$/.test(dollarInline) || /^\d/.test(next)) return match
    return stash(dollarInline, false)
  })

  return {
    text,
    restore: (html: string) => rendered.reduce(
      (acc, block, index) => acc.replace(`@@MATH_${index}@@`, () => block),
      html
    ),
  }
}
