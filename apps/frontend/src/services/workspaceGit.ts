import { getElectronBridge } from '@/platform/electron/bridge'

export interface GitFileChange {
  path: string
  index: string
  worktree: string
}

export interface GitStatusResult {
  branch: string
  ahead: number
  behind: number
  files: GitFileChange[]
}

/**
 * Git 操作只走桌面宿主（本地仓库）。所有方法在 Web 构建下都会明确失败，
 * 由调用方展示「仅桌面端可用」。
 */
const bridge = () => {
  const git = getElectronBridge()?.workspace
  if (!git?.gitStatus) throw new Error('Git 仅在桌面端可用')
  return git
}

export const gitStatus = (root: string): Promise<GitStatusResult> => bridge().gitStatus!(root)
export const gitDiff = (root: string, path: string, staged: boolean): Promise<string> => bridge().gitDiff!(root, path, staged)
export const gitShow = (root: string, path: string, ref = 'HEAD'): Promise<string | null> => bridge().gitShow!(root, path, ref)
export const gitStage = (root: string, paths: string[]): Promise<void> => bridge().gitStage!(root, paths)
export const gitUnstage = (root: string, paths: string[]): Promise<void> => bridge().gitUnstage!(root, paths)
export const gitCommit = (root: string, message: string): Promise<{ committed: boolean; output: string }> => bridge().gitCommit!(root, message)
