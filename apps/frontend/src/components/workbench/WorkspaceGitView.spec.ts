import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import WorkspaceGitView from './WorkspaceGitView.vue'
import { gitCommit, gitDiff, gitStage, gitStatus, gitUnstage } from '@/services/workspaceGit'
import { registerDiff, resetDiff } from '@/workbench/core/diffRequest'

vi.mock('@/services/workspaceGit', () => ({
  gitStatus: vi.fn(),
  gitDiff: vi.fn(),
  gitStage: vi.fn(),
  gitUnstage: vi.fn(),
  gitCommit: vi.fn()
}))
vi.mock('@/services/api/agentos', () => ({
  agentosApi: { listWorkspaceFiles: vi.fn(async () => ({ workspaceRoot: 'C:/workspace', path: '.', entries: [] })) }
}))

const status = {
  branch: 'main',
  ahead: 1,
  behind: 0,
  files: [
    { path: 'src/a.ts', index: ' ', worktree: 'M' },
    { path: 'src/b.ts', index: 'M', worktree: ' ' }
  ]
}

const mountView = async () => {
  const wrapper = mount(WorkspaceGitView, { props: { missionId: 'mission-1' } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  vi.clearAllMocks()
  resetDiff()
  vi.mocked(gitStatus).mockResolvedValue(status)
  vi.mocked(gitDiff).mockResolvedValue('diff --git a/src/a.ts b/src/a.ts\n@@ -1 +1 @@\n-old line\n+new line\n')
  vi.mocked(gitStage).mockResolvedValue(undefined)
  vi.mocked(gitUnstage).mockResolvedValue(undefined)
  vi.mocked(gitCommit).mockResolvedValue({ committed: true, output: '' })
  ;(window as any).kinlinDesktop = {
    window: {}, dialog: {}, zoom: {}, notify: () => {}, openExternal: async () => {},
    appInfo: async () => ({ version: '0', platform: 'win32', packaged: false }),
    workspace: { current: async () => ({ id: 'ws-1', root: 'C:/workspace' }), gitStatus: () => {} }
  }
})

afterEach(() => {
  delete (window as any).kinlinDesktop
})

it('展示分支与改动文件，暂存后刷新状态', async () => {
  const wrapper = await mountView()
  expect(wrapper.text()).toContain('main')
  expect(wrapper.text()).toContain('↑1')
  expect(wrapper.text()).toContain('src/a.ts')
  expect(wrapper.text()).toContain('src/b.ts')

  const stageButton = wrapper.findAll('button').find(button => button.text() === '暂存')!
  await stageButton.trigger('click')
  await flushPromises()

  expect(gitStage).toHaveBeenCalledWith('C:/workspace', ['src/a.ts'])
  expect(gitStatus).toHaveBeenCalledTimes(2)
  wrapper.unmount()
})

it('取消暂存走 gitUnstage', async () => {
  const wrapper = await mountView()
  const unstageButton = wrapper.findAll('button').find(button => button.text() === '取消暂存')!
  await unstageButton.trigger('click')
  await flushPromises()
  expect(gitUnstage).toHaveBeenCalledWith('C:/workspace', ['src/b.ts'])
  wrapper.unmount()
})

it('选中文件加载 diff 并按增删着色', async () => {
  const wrapper = await mountView()
  await wrapper.findAll('.workspace-git__file')[0].trigger('click')
  await flushPromises()

  expect(gitDiff).toHaveBeenCalledWith('C:/workspace', 'src/a.ts', false)
  expect(wrapper.find('.workspace-git__diff-body').text()).toContain('new line')
  expect(wrapper.findAll('.workspace-git__diff-line.is-add').length).toBe(1)
  expect(wrapper.findAll('.workspace-git__diff-line.is-del').length).toBe(1)
  wrapper.unmount()
})

it('提交按钮需要提交信息与已暂存改动', async () => {
  const wrapper = await mountView()
  const commitButton = () => wrapper.findAll('button').find(button => button.text() === '提交')!
  expect(commitButton().attributes('disabled')).toBeDefined()

  await wrapper.get('textarea').setValue('feat: 修改 a.ts')
  expect(commitButton().attributes('disabled')).toBeUndefined()

  await commitButton().trigger('click')
  await flushPromises()
  expect(gitCommit).toHaveBeenCalledWith('C:/workspace', 'feat: 修改 a.ts')
  expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('')
  wrapper.unmount()
})

it('对比按钮请求行内 diff 并带上 diff 标记', async () => {
  const wrapper = await mountView()
  const opened: string[] = []
  registerDiff('src/a.ts', () => opened.push('diff'))

  await wrapper.findAll('button').find(button => button.text() === '对比')!.trigger('click')
  expect(opened).toEqual(['diff'])
  expect(wrapper.emitted('open-file')?.[0]?.[0]).toMatchObject({
    relativePath: 'src/a.ts',
    diff: true,
    desktopWorkspaceId: 'ws-1'
  })
  wrapper.unmount()
})

it('没有桌面桥时提示仅桌面可用', async () => {
  delete (window as any).kinlinDesktop
  const wrapper = await mountView()
  expect(wrapper.text()).toContain('Git 仅在桌面端可用')
  expect(gitStatus).not.toHaveBeenCalled()
  wrapper.unmount()
})
