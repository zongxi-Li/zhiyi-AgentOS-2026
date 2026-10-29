import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { agentosApi } from '@/services/api/agentos'
import WorkspaceFileEditor from './WorkspaceFileEditor.vue'
vi.mock('@/services/api/agentos', () => ({agentosApi:{readWorkspaceFile:vi.fn(),saveWorkspaceFile:vi.fn()}}))
const request={missionId:'mission',workspaceRoot:'C:/authorized',relativePath:'note.md',name:'note.md'}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(agentosApi.readWorkspaceFile).mockResolvedValue({workspaceRoot:'C:/authorized',path:'note.md',content:'<script>literal</script>',version:'v1'})
})
it('opens literal text centrally and saves only against the observed version', async () => {
  vi.mocked(agentosApi.saveWorkspaceFile).mockResolvedValue({path:'note.md',version:'v2'})
  const wrapper=mount(WorkspaceFileEditor,{props:{request}})
  await flushPromises()
  expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  expect(wrapper.find('script').exists()).toBe(false)
  expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('<script>literal</script>')
  await wrapper.get('textarea').setValue('edited')
  await wrapper.get('textarea').trigger('keydown',{key:'s',ctrlKey:true})
  await flushPromises()
  expect(agentosApi.saveWorkspaceFile).toHaveBeenCalledWith('mission',expect.objectContaining({path:'note.md',content:'edited',expectedVersion:'v1'}))
  expect(wrapper.emitted('dirty-change')?.at(-1)).toEqual([false])
  wrapper.unmount()
})
it('keeps the draft on conflict and never retries an uncertain save', async () => {
  vi.mocked(agentosApi.saveWorkspaceFile).mockRejectedValue({response:{status:409}})
  const wrapper=mount(WorkspaceFileEditor,{props:{request}})
  await flushPromises();await wrapper.get('textarea').setValue('my draft')
  await wrapper.get('textarea').trigger('keydown',{key:'s',ctrlKey:true});await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toContain('未覆盖')
  expect((wrapper.get('textarea').element as HTMLTextAreaElement).value).toBe('my draft')
  expect(agentosApi.saveWorkspaceFile).toHaveBeenCalledTimes(1)
  wrapper.unmount()
})
it('disables saving when a legacy runtime returns no version token', async () => {
  vi.mocked(agentosApi.readWorkspaceFile).mockResolvedValue({workspaceRoot:'C:/authorized',path:'note.md',content:'legacy'})
  const wrapper=mount(WorkspaceFileEditor,{props:{request}});await flushPromises()
  expect(wrapper.get('textarea').attributes('readonly')).toBeDefined()
  expect(agentosApi.saveWorkspaceFile).not.toHaveBeenCalled()
  wrapper.unmount()
})
