import { getElectronBridge, type LspDiagnosticItem, type LspLocationItem } from '@/platform/electron/bridge'

export type { LspDiagnosticItem, LspLocationItem } from '@/platform/electron/bridge'

const lsp = () => {
  const bridge = getElectronBridge()?.lsp
  if (!bridge) throw new Error('语言服务仅在桌面端可用')
  return bridge
}

export const lspAvailable = (): boolean => Boolean(getElectronBridge()?.lsp)

export const lspOpen = (root: string, path: string, text: string): Promise<{ languageId: string | null }> => lsp().open(root, path, text)
export const lspChange = (root: string, path: string, text: string): Promise<void> => lsp().change(root, path, text)
export const lspClose = (root: string, path: string): Promise<void> => lsp().close(root, path)
export const lspDiagnostics = (root: string): Promise<LspDiagnosticItem[]> => lsp().diagnostics(root)
export const lspDefinition = (root: string, path: string, line: number, column: number): Promise<LspLocationItem[]> =>
  lsp().definition(root, path, line, column)
