import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { agentosApi } from '@/services/api/agentos'
import { workspaceDocuments, type TextDocument } from '@/workbench/core/documents'
import { workspaceDiagnostics } from '@/workbench/core/diagnostics'
import { gitShow } from '@/services/workspaceGit'
import WorkspaceFileEditor from './WorkspaceFileEditor.vue'

vi.mock('@/services/api/agentos', () => ({ agentosApi: { readWorkspaceFile: vi.fn(), saveWorkspaceFile: vi.fn() } }))
vi.mock('@/workbench/core/diagnostics', () => ({
  workspaceDiagnostics: { schedule: vi.fn(), run: vi.fn(), clear: vi.fn(), reset: vi.fn() }
}))
vi.mock('@/services/workspaceGit', () => ({ gitShow: vi.fn(async () => 'HEAD content') }))

// CodeMirror 需要真实排版，jsdom 里跑不起来；这里替换成只暴露 props 的桩，
// 由测试直接驱动文档对象，验证外壳的加载/保存/冲突/只读逻辑。
vi.mock('./WorkspaceCodeEditor.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    __esModule: true,
    default: defineComponent({
      name: 'CodeEditorStub',
      props: {
        document: { type: Object, required: true },
        fileName: { type: String, default: '' },
        filePath: { type: String, default: '' },
        readOnly: { type: Boolean, default: false }
      },
      emits: ['save', 'cursor'],
      render() { return h('div', { class: 'code-editor-stub' }) }
    })
  }
})

vi.mock('./WorkspaceDiffView.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    __esModule: true,
    default: defineComponent({
      name: 'DiffStub',
      props: {
        base: { type: String, default: '' },
        current: { type: String, default: '' },
        fileName: { type: String, default: '' }
      },
      render() { return h('div', { class: 'diff-stub' }) }
    })
  }
})

const request = { missionId: 'mission', workspaceRoot: 'C:/authorized', relativePath: 'note.md', name: 'note.md' }

const mountEditor = async (overrides: Record<string, unknown> = {}) => {
  const wrapper = mount(WorkspaceFileEditor, { props: { request: { ...request, ...overrides } } })
  await flushPromises()
  return wrapper
}

const editorStub = (wrapper: ReturnType<typeof mount>) => wrapper.getComponent({ name: 'CodeEditorStub' })

beforeEach(() => {
  vi.clearAllMocks()
  workspaceDocuments.reset()
  vi.mocked(agentosApi.readWorkspaceFile).mockResolvedValue({
    workspaceRoot: 'C:/authorized',
    path: 'note.md',
    content: '<script>literal</script>',
    version: 'v1'
  })
})

it('opens literal text and saves only against the observed version', async () => {
  vi.mocked(agentosApi.saveWorkspaceFile).mockResolvedValue({ path: 'note.md', version: 'v2' })
  const wrapper = await mountEditor()

  expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
  expect(wrapper.find('script').exists()).toBe(false)
  const stub = editorStub(wrapper)
  const doc = stub.props('document') as TextDocument
  expect(doc.getText()).toBe('<script>literal</script>')

  doc.applyEdits([{ from: 0, to: 0, insert: 'edited ' }])
  stub.vm.$emit('save')
  await flushPromises()

  expect(agentosApi.saveWorkspaceFile).toHaveBeenCalledWith('mission', expect.objectContaining({
    path: 'note.md',
    content: 'edited <script>literal</script>',
    expectedVersion: 'v1'
  }))
  expect(wrapper.emitted('dirty-change')?.at(-1)).toEqual([false])
  expect(workspaceDiagnostics.schedule).toHaveBeenCalledWith('C:/authorized')
  wrapper.unmount()
})

it('keeps the draft on conflict and never retries an uncertain save', async () => {
  vi.mocked(agentosApi.saveWorkspaceFile).mockRejectedValue({ response: { status: 409 } })
  const wrapper = await mountEditor()
  const stub = editorStub(wrapper)
  const doc = stub.props('document') as TextDocument

  doc.applyEdits([{ from: 0, to: 0, insert: 'my draft' }])
  stub.vm.$emit('save')
  await flushPromises()

  expect(wrapper.get('[role="alert"]').text()).toContain('未覆盖')
  expect(doc.getText()).toBe('my draft<script>literal</script>')
  expect(agentosApi.saveWorkspaceFile).toHaveBeenCalledTimes(1)
  wrapper.unmount()
})

it('marks the editor read-only when a legacy runtime returns no version token', async () => {
  vi.mocked(agentosApi.readWorkspaceFile).mockResolvedValue({ workspaceRoot: 'C:/authorized', path: 'note.md', content: 'legacy' })
  const wrapper = await mountEditor()

  expect(editorStub(wrapper).props('readOnly')).toBe(true)
  const saveButton = wrapper.findAll('button').at(-1)!
  expect(saveButton.attributes('disabled')).toBeDefined()
  expect(agentosApi.saveWorkspaceFile).not.toHaveBeenCalled()
  wrapper.unmount()
})

it('reports file meta to the window status bar instead of an internal footer', async () => {
  const wrapper = await mountEditor()
  expect(wrapper.find('.file-editor__status').exists()).toBe(false)
  expect(wrapper.emitted('status-change')?.at(-1)).toEqual([
    { editable: true, language: 'MD', lines: 1, cursor: '行 1，列 1' }
  ])

  const stub = editorStub(wrapper)
  const doc = stub.props('document') as TextDocument
  doc.applyEdits([{ from: 0, to: 0, insert: 'one\ntwo\n' }])
  await flushPromises()
  expect(wrapper.emitted('status-change')?.at(-1)).toEqual([
    { editable: true, language: 'MD', lines: 3, cursor: '行 1，列 1' }
  ])

  stub.vm.$emit('cursor', { line: 3, column: 7 })
  await flushPromises()
  expect(wrapper.emitted('status-change')?.at(-1)).toEqual([
    { editable: true, language: 'MD', lines: 3, cursor: '行 3，列 7' }
  ])
  wrapper.unmount()
})

it('flags readonly in the reported status when no version token is available', async () => {
  vi.mocked(agentosApi.readWorkspaceFile).mockResolvedValue({ workspaceRoot: 'C:/authorized', path: 'note.md', content: 'legacy' })
  const wrapper = await mountEditor()
  expect(wrapper.emitted('status-change')?.at(-1)).toEqual([
    { editable: false, language: 'MD', lines: 1, cursor: '行 1，列 1' }
  ])
  wrapper.unmount()
})

it('re-reads the file and rebuilds the editor on reload', async () => {
  const wrapper = await mountEditor()
  expect(editorStub(wrapper).props('readOnly')).toBe(false)

  await wrapper.findAll('button').find(button => button.text() === '重新读取')!.trigger('click')
  await flushPromises()
  expect(agentosApi.readWorkspaceFile).toHaveBeenCalledTimes(2)
  wrapper.unmount()
})

it('opens in inline diff mode when the request asks for it', async () => {
  const wrapper = await mountEditor({ diff: true })
  await vi.waitFor(() => expect(wrapper.findComponent({ name: 'DiffStub' }).exists()).toBe(true))

  const stub = wrapper.getComponent({ name: 'DiffStub' })
  expect(stub.props('base')).toBe('HEAD content')
  expect(stub.props('current')).toBe('<script>literal</script>')
  expect(gitShow).toHaveBeenCalledWith('C:/authorized', 'note.md')
  wrapper.unmount()
})

it('toggles inline diff from the toolbar', async () => {
  const wrapper = await mountEditor()
  expect(wrapper.findComponent({ name: 'DiffStub' }).exists()).toBe(false)

  await wrapper.findAll('button').find(button => button.text() === '对比')!.trigger('click')
  await vi.waitFor(() => expect(wrapper.findComponent({ name: 'DiffStub' }).exists()).toBe(true))

  await wrapper.findAll('button').find(button => button.text() === '编辑')!.trigger('click')
  await flushPromises()
  expect(wrapper.findComponent({ name: 'DiffStub' }).exists()).toBe(false)
  wrapper.unmount()
})

it('falls back to the editor and reports the reason when the base version cannot be read', async () => {
  vi.mocked(gitShow).mockRejectedValueOnce(new Error('不是 Git 仓库'))
  const wrapper = await mountEditor({ diff: true })
  await flushPromises()

  expect(wrapper.text()).toContain('不是 Git 仓库')
  expect(wrapper.findComponent({ name: 'DiffStub' }).exists()).toBe(false)
  wrapper.unmount()
})
