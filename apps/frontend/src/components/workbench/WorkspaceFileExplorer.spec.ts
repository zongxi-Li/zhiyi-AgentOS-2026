import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { agentosApi } from '@/services/api/agentos'
import WorkspaceFileExplorer from './WorkspaceFileExplorer.vue'

vi.mock('@/services/api/agentos', async importOriginal => {
  const actual = await importOriginal<typeof import('@/services/api/agentos')>()
  return { ...actual, agentosApi: { ...actual.agentosApi, listWorkspaceFiles: vi.fn() } }
})

const iconStub = defineComponent({ template: '<i><slot /></i>' })
const rootListing = {
  workspaceRoot: 'C:/work/project',
  path: '.',
  entries: [
    { name: 'apps', path: 'apps', type: 'directory' as const },
    { name: 'node_modules', path: 'node_modules', type: 'directory' as const },
    { name: 'README.md', path: 'README.md', type: 'file' as const }
  ]
}

describe('WorkspaceFileExplorer', () => {
  beforeEach(() => vi.clearAllMocks())

  it('loads directories lazily, filters ignored folders, and emits a typed file-open request', async () => {
    vi.mocked(agentosApi.listWorkspaceFiles).mockImplementation(async (_missionId, path = '.') => {
      if (path === '.') return rootListing
      if (path === 'apps') return {
        workspaceRoot: rootListing.workspaceRoot,
        path,
        entries: [{ name: 'src', path: 'apps/src', type: 'directory' }]
      }
      return {
        workspaceRoot: rootListing.workspaceRoot,
        path,
        entries: [{ name: 'main.ts', path: 'apps/src/main.ts', type: 'file' }]
      }
    })

    const wrapper = mount(WorkspaceFileExplorer, {
      props: { missionId: 'mission_1' },
      global: { stubs: { 'el-icon': iconStub } }
    })
    await flushPromises()

    expect(agentosApi.listWorkspaceFiles).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('C:/work/project')
    expect(wrapper.text()).not.toContain('node_modules')
    expect(wrapper.text()).toContain('README.md')

    await wrapper.findAll('.workspace-file-explorer__row').find(row => row.text().includes('apps'))!.trigger('click')
    await flushPromises()
    expect(agentosApi.listWorkspaceFiles).toHaveBeenLastCalledWith('mission_1', 'apps')

    await wrapper.findAll('.workspace-file-explorer__row').find(row => row.text().includes('src'))!.trigger('click')
    await flushPromises()
    expect(agentosApi.listWorkspaceFiles).toHaveBeenLastCalledWith('mission_1', 'apps/src')

    const fileRow = wrapper.findAll('.workspace-file-explorer__row').find(row => row.text().includes('main.ts'))!
    await fileRow.trigger('click')
    expect(fileRow.classes()).toContain('is-selected')
    expect(wrapper.emitted('open-file')?.[0]?.[0]).toEqual({
      missionId: 'mission_1',
      workspaceRoot: 'C:/work/project',
      relativePath: 'apps/src/main.ts',
      name: 'main.ts'
    })
    wrapper.unmount()
  })

  it('refreshes only the workspace root and preserves the explicit no-preview behavior', async () => {
    vi.mocked(agentosApi.listWorkspaceFiles).mockResolvedValue(rootListing)
    const wrapper = mount(WorkspaceFileExplorer, {
      props: { missionId: 'mission_1' },
      global: { stubs: { 'el-icon': iconStub } }
    })
    await flushPromises()

    await wrapper.get('[aria-label="刷新文件列表"]').trigger('click')
    await flushPromises()
    expect(agentosApi.listWorkspaceFiles).toHaveBeenCalledTimes(2)
    expect(agentosApi.listWorkspaceFiles).toHaveBeenLastCalledWith('mission_1', '.')
    expect(wrapper.emitted('open-file')).toBeUndefined()
    wrapper.unmount()
  })
})
