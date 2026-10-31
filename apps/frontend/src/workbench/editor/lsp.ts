/**
 * 编辑器内的语言服务接线：诊断走 CodeMirror lint，跳转定义走 F12。
 * 只有桌面宿主提供 LSP 桥；Web 构建下这个扩展根本不会被安装。
 */
import type { EditorState, Extension } from '@codemirror/state'
import { keymap, type EditorView } from '@codemirror/view'
import { linter, lintGutter, type Diagnostic } from '@codemirror/lint'
import { lspChange, lspDiagnostics, lspDefinition, type LspDiagnosticItem, type LspLocationItem } from '@/services/lsp'

export interface LspExtensionOptions {
  /** 工作区根目录（语言服务以它为 rootUri） */
  root: string
  /** 工作区相对路径 */
  path: string
  onDefinition: (location: LspLocationItem) => void
}

/** LSP 的行列是 1 基；映射到 CodeMirror 偏移时对越界值做收敛。 */
export const toDiagnostics = (state: EditorState, items: LspDiagnosticItem[], path: string): Diagnostic[] => (
  items.filter(item => item.path === path).map(item => {
    const line = state.doc.line(Math.min(Math.max(item.line, 1), state.doc.lines))
    const from = Math.min(line.from + Math.max(item.column - 1, 0), line.to)
    return {
      from,
      to: Math.min(from + 1, line.to),
      severity: item.severity,
      message: item.message,
      source: item.source
    }
  })
)

const goToDefinition = async (view: EditorView, options: LspExtensionOptions): Promise<void> => {
  const position = view.state.selection.main.head
  const line = view.state.doc.lineAt(position)
  try {
    const locations = await lspDefinition(options.root, options.path, line.number, position - line.from + 1)
    if (locations.length) options.onDefinition(locations[0])
  } catch {
    // 语言服务未就绪或不可用时静默，不影响编辑。
  }
}

export const lspExtension = (options: LspExtensionOptions): Extension[] => {
  let lastSent: string | null = null
  return [
    lintGutter(),
    linter(async view => {
      // 只在文本真的变化时同步，避免轮询触发的 lint 反复把同一份文本推给语言服务。
      const text = view.state.doc.toString()
      if (text !== lastSent) {
        lastSent = text
        await lspChange(options.root, options.path, text).catch(() => undefined)
      }
      // 语言服务异步计算诊断：短暂轮询，避免第一次拿到空结果就再也不刷新。
      for (let attempt = 0; attempt < 3; attempt += 1) {
        const items = await lspDiagnostics(options.root).catch(() => [] as LspDiagnosticItem[])
        if (items.length) return toDiagnostics(view.state, items, options.path)
        await new Promise(resolve => setTimeout(resolve, 250))
      }
      return []
    }, { delay: 900 }),
    keymap.of([{
      key: 'F12',
      run: view => {
        void goToDefinition(view, options)
        return true
      }
    }])
  ]
}
