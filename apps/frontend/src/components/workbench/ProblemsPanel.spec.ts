import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ProblemsPanel from './ProblemsPanel.vue'
import { runWorkspaceDiagnostics } from '@/services/workspaceDiagnostics'
import { registerReveal, resetReveal } from '@/workbench/core/reveal'
import { workspaceDiagnostics } from '@/workbench/core/diagnostics'

vi.mock('@/services/workspaceDiagnostics', () => ({ runWorkspaceDiagnostics: vi.fn() }))
vi.mock('@/services/api/agentos', () => ({
  agentosApi: { listWorkspaceFiles: vi.fn(async () => ({ workspaceRoot: 'C:/workspace', path: '.', entries: [] })) }
}))

beforeEach(() => {
  resetReveal()
  workspaceDiagnostics.reset()
  vi.clearAllMocks()
  ;(window as any).kinlinDesktop = {
    window: {},
    dialog: {},
    zoom: {},
    notify: () => {},
    openExternal: async () => {},
    appInfo: async () => ({ version: '0', platform: 'win32', packaged: false }),
    workspace: { current: async () => ({ id: 'ws-1', root: 'C:/workspace' }) }
  }
})

afterEach(() => {
  delete (window as any).kinlinDesktop
})

const mountPanel = async (diagnostics: any[] = []) => {
  const wrapper = mount(ProblemsPanel, {
    props: { diagnostics, missionId: 'mission-1' },
    global: { stubs: { 'el-icon': true } }
  })
  await flushPromises()
  return wrapper
}

it('默认展示投影诊断，空态提示可以运行检查', async () => {
  const wrapper = await mountPanel()
  expect(wrapper.text()).toContain('没有发现问题')
  wrapper.unmount()
})

it('运行检查后展示可点击的问题，点击打开文件并定位到行', async () => {
  vi.mocked(runWorkspaceDiagnostics).mockResolvedValue({
    diagnostics: [
      { path: 'src/a.ts', line: 3, column: 5, severity: 'error', code: 'TS2322', message: "Type 'string' is not assignable", source: 'tsc' },
      { path: 'src/b.py', line: 7, column: 1, severity: 'warning', code: 'F401', message: 'unused import', source: 'ruff' }
    ],
    engine: 'tsc',
    durationMs: 42,
    truncated: false,
    message: 'tsc 退出码 2'
  })
  const wrapper = await mountPanel()
  const revealed: number[] = []
  registerReveal('src/a.ts', line => revealed.push(line))

  await wrapper.get('.problems-panel__run').trigger('click')
  await flushPromises()

  expect(runWorkspaceDiagnostics).toHaveBeenCalledWith('C:/workspace')
  expect(wrapper.findAll('.problems-panel__item')).toHaveLength(2)
  expect(wrapper.text()).toContain('TS2322')

  await wrapper.findAll('.problems-panel__location')[0].trigger('click')
  expect(revealed).toEqual([3])
  expect(wrapper.emitted('open-file')?.[0]).toEqual([{
    missionId: 'mission-1',
    workspaceRoot: 'C:/workspace',
    relativePath: 'src/a.ts',
    name: 'a.ts',
    desktopWorkspaceId: 'ws-1'
  }])
  wrapper.unmount()
})

it('检查失败时展示错误且不影响已有诊断', async () => {
  vi.mocked(runWorkspaceDiagnostics).mockRejectedValue(new Error('检查器不可用'))
  const wrapper = await mountPanel([
    { code: 'RUN_FAILED', message: 'step failed', severity: 'error' }
  ])
  await wrapper.get('.problems-panel__run').trigger('click')
  await flushPromises()

  expect(wrapper.get('[role="alert"]').text()).toContain('检查器不可用')
  expect(wrapper.text()).toContain('RUN_FAILED')
  expect(wrapper.findAll('.problems-panel__location')).toHaveLength(0)
  wrapper.unmount()
})
