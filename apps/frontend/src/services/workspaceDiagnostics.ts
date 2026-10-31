import { getElectronBridge, type WorkspaceDiagnosticsResult } from '@/platform/electron/bridge'

export type { WorkspaceDiagnosticItem, WorkspaceDiagnosticsResult } from '@/platform/electron/bridge'

/**
 * 用项目自己的工具链跑一次静态检查（tsc / ruff），返回可跳转的问题列表。
 * 只有桌面宿主提供该能力：检查器是本地进程。
 */
export async function runWorkspaceDiagnostics(root: string): Promise<WorkspaceDiagnosticsResult> {
  const run = getElectronBridge()?.workspace?.diagnostics
  if (!run) throw new Error('静态检查仅在桌面端可用')
  return run(root)
}
