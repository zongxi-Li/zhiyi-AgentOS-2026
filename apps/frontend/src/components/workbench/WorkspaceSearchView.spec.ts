import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import WorkspaceSearchView from './WorkspaceSearchView.vue'
import { registerReveal, resetReveal } from '@/workbench/core/reveal'

vi.mock('@/services/api/agentos', () => ({
  agentosApi: { listWorkspaceFiles: vi.fn(async () => ({ workspaceRoot: 'C:/workspace', path: '.', entries: [] })) }
}))

const search = vi.fn(async () => ({
  matches: [
    { path: 'src/a.ts', line: 7, text: 'const answer = 42' },
    { path: 'src/deep/b.py', line: 3, text: 'answer = 42' }
  ],
  truncated: false,
  engine: 'ripgrep' as const
}))

beforeEach(() => {
  resetReveal()
  search.mockClear()
  ;(window as any).kinlinDesktop = {
    window: {},
    dialog: {},
    zoom: {},
    notify: () => {},
    openExternal: async () => {},
    appInfo: async () => ({ version: '0', platform: 'win32', packaged: false }),
    workspace: {
      current: async () => ({ id: 'ws-1', root: 'C:/workspace' }),
      search
    }
  }
})

afterEach(() => {
  delete (window as any).kinlinDesktop
})

const mountView = async () => {
  const wrapper = mount(WorkspaceSearchView, {
    props: { missionId: 'mission-1' },
    global: { stubs: { 'el-icon': true } }
  })
  await flushPromises()
  return wrapper
}

it('输入关键词后按防抖搜索并按行展示结果', async () => {
  const wrapper = await mountView()
  expect(wrapper.text()).toContain('输入至少 2 个字符开始搜索')

  await wrapper.get('input').setValue('answer')
  await vi.waitFor(() => expect(search).toHaveBeenCalledTimes(1))
  expect(search).toHaveBeenCalledWith('C:/workspace', { query: 'answer', maxResults: 200 })

  await vi.waitFor(() => expect(wrapper.findAll('.workspace-search__result')).toHaveLength(2))
  expect(wrapper.text()).toContain('src/a.ts')
  expect(wrapper.text()).toContain('ripgrep')
  wrapper.unmount()
})

it('点击结果打开文件并定位到对应行', async () => {
  const wrapper = await mountView()
  const revealed: number[] = []
  registerReveal('src/deep/b.py', line => revealed.push(line))

  await wrapper.get('input').setValue('answer')
  await vi.waitFor(() => expect(wrapper.findAll('.workspace-search__result')).toHaveLength(2))
  await wrapper.findAll('.workspace-search__result')[1].trigger('click')

  expect(revealed).toEqual([3])
  expect(wrapper.emitted('open-file')?.[0]).toEqual([{
    missionId: 'mission-1',
    workspaceRoot: 'C:/workspace',
    relativePath: 'src/deep/b.py',
    name: 'b.py',
    desktopWorkspaceId: 'ws-1'
  }])
  wrapper.unmount()
})

it('搜索为空时给出提示，失败时展示错误', async () => {
  search.mockResolvedValueOnce({ matches: [], truncated: false, engine: 'node' })
  const wrapper = await mountView()
  await wrapper.get('input').setValue('nothing')
  await vi.waitFor(() => expect(wrapper.text()).toContain('没有匹配结果'))
  wrapper.unmount()

  search.mockRejectedValueOnce(new Error('搜索服务不可用'))
  const failing = await mountView()
  await failing.get('input').setValue('boom')
  await vi.waitFor(() => expect(failing.text()).toContain('搜索服务不可用'))
  failing.unmount()
})

it('没有桌面桥时明确提示仅桌面端可用', async () => {
  delete (window as any).kinlinDesktop
  const wrapper = await mountView()
  expect(wrapper.text()).toContain('全文搜索仅在桌面端可用')
  wrapper.unmount()
})
