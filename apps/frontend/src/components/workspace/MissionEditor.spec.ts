import { nextTick } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { EditorView } from '@codemirror/view'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MissionEditor from './MissionEditor.vue'
import { agentosApi, type MissionWorkspaceProjection, type WorkspaceEntry } from '@/services/api/agentos'

vi.mock('@/services/api/agentos', async importOriginal => {
  const actual = await importOriginal<typeof import('@/services/api/agentos')>()
  return { ...actual, agentosApi: { ...actual.agentosApi, editMissionSemantics: vi.fn() } }
})
afterEach(() => vi.resetAllMocks())

// jsdom 没有排版引擎：给 CodeMirror 提供几何 API（与 WorkspaceCodeEditor.lifecycle.spec 同配方）。
const rangeRectDescriptors = ['getClientRects', 'getBoundingClientRect'].map(key =>
  [key, Object.getOwnPropertyDescriptor(Range.prototype, key)] as const)

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
  const rect = { left: 0, top: 0, right: 500, bottom: 200, width: 500, height: 200, x: 0, y: 0, toJSON() {} }
  Object.defineProperty(Range.prototype, 'getClientRects', { configurable: true, value: () => [] })
  Object.defineProperty(Range.prototype, 'getBoundingClientRect', { configurable: true, value: () => rect })
})

afterEach(() => {
  for (const [key, descriptor] of rangeRectDescriptors) {
    if (descriptor) Object.defineProperty(Range.prototype, key, descriptor)
    else delete (Range.prototype as Record<string, unknown>)[key]
  }
  vi.unstubAllGlobals()
})

const projection = (): MissionWorkspaceProjection => ({
  mission: {
    missionId: 'mission_1', userId: 'user_1', goal: '设备人员规划', description: '目标',
    metadata: {}, createdAt: '2026-08-28T00:00:00Z', updatedAt: '2026-08-28T00:00:00Z', status: 'created'
  },
  activeRun: null,
  runs: [],
  activeGraph: null,
  graphNodes: [],
  diagnostics: [],
  entries: []
})

const entry = (content: string): WorkspaceEntry => ({
  entryId: 'overview:mission.md', kind: 'virtual_document', name: 'mission.md',
  group: 'overview', displayOrder: 1, content
})

/** 视图页签：0=编辑 1=预览。 */
const modeButtons = (wrapper: ReturnType<typeof mount>) =>
  wrapper.findAll('.mission-editor__mode button')

describe('MissionEditor', () => {
  const editable = () => {
    const value = projection()
    value.missionSemanticView = { missionId: 'mission_1', semanticStatus: 'INITIALIZED', missionRevision: 2,
      objective: '当前正式目标', constraints: [{ constraintId: 'keep-id', text: '保留约束', sourceRefs: ['ref:one'] }],
      sourceReferences: ['ref:mission'], sourceStatus: 'UNVERIFIED' }
    return value
  }

  it('edits current semantics, retains constraint identity and retries the exact operation', async () => {
    vi.mocked(agentosApi.editMissionSemantics).mockRejectedValueOnce(new Error('lost response')).mockResolvedValueOnce({
      status: 'COMMITTED', missionId: 'mission_1', operationId: 'op', missionRevision: 3
    })
    const wrapper = mount(MissionEditor, { props: { projection: editable(), entry: entry('') } })
    await wrapper.find('header button').trigger('click')
    await wrapper.find('textarea[aria-label="正式目标"]').setValue('修改后的目标')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    const first = vi.mocked(agentosApi.editMissionSemantics).mock.calls[0][1]
    expect(first).toMatchObject({ expectedMissionRevision: 2, objective: '修改后的目标', sourceRefs: ['ref:mission'],
      constraints: [{ constraintId: 'keep-id', text: '保留约束', sourceRefs: ['ref:one'] }] })
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(vi.mocked(agentosApi.editMissionSemantics).mock.calls[1][1]).toEqual(first)
    expect(wrapper.emitted('semanticsSaved')).toHaveLength(1)
    expect(wrapper.find('form').exists()).toBe(false)
  })

  it('keeps a conflicting draft and requires a refresh before a new CAS request', async () => {
    vi.mocked(agentosApi.editMissionSemantics).mockRejectedValue({ response: { status: 409 } })
    const wrapper = mount(MissionEditor, { props: { projection: editable(), entry: entry('') } })
    await wrapper.find('header button').trigger('click')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('版本冲突')
    expect(wrapper.find('button[type="submit"]').attributes('disabled')).toBeDefined()
    await wrapper.find('form').trigger('submit')
    expect(agentosApi.editMissionSemantics).toHaveBeenCalledTimes(1)
  })

  it('offers explicit initialization for legacy missions and hides editing when the flag is off', async () => {
    const value = projection()
    const wrapper = mount(MissionEditor, { props: { projection: value, entry: entry('') } })
    expect(wrapper.find('header button').exists()).toBe(false)
    value.missionSemanticView = { missionId: 'mission_1', semanticStatus: 'UNINITIALIZED', missionRevision: 0,
      objective: null, constraints: [], sourceReferences: [], sourceStatus: 'NOT_APPLICABLE' }
    await wrapper.setProps({ projection: { ...value } })
    await wrapper.find('header button').trigger('click')
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('')
  })

  it('opens mission.md in an editable editor by default and keeps the draft local', async () => {
    const wrapper = mount(MissionEditor, {
      props: { projection: projection(), entry: entry('# 设备人员规划\n\n## Semantic tasks\n\n内容') }
    })
    // 默认编辑态：CodeMirror 渲染源文（带行号 gutter）
    expect(wrapper.find('.mission-markdown-editor').exists()).toBe(true)
    expect(wrapper.find('.mission-markdown-editor .cm-gutters').exists()).toBe(true)
    expect(wrapper.find('.mission-markdown-editor').text()).toContain('设备人员规划')
    expect(wrapper.find('.editor-document__body').exists()).toBe(false)

    // 编辑落本地草稿：出现未保存提示与还原按钮，投影不回写 entry.content
    const editor = EditorView.findFromDOM(wrapper.get('.mission-markdown-editor').element as HTMLElement)!
    editor.dispatch({ changes: { from: 0, to: 2, insert: '##' } })
    await nextTick()
    expect(wrapper.find('.mission-editor__draft-hint').text()).toContain('本地草稿')
    expect(wrapper.find('.mission-editor__reset').exists()).toBe(true)
    expect(wrapper.props('entry').content).toBe('# 设备人员规划\n\n## Semantic tasks\n\n内容')

    await wrapper.find('.mission-editor__reset').trigger('click')
    await nextTick()
    expect(wrapper.find('.mission-editor__reset').exists()).toBe(false)
    wrapper.unmount()
  })

  it('keeps the editor chrome compact and renders the full mission heading in the preview', async () => {
    const wrapper = mount(MissionEditor, {
      props: {
        projection: projection(),
        entry: entry('# 设备人员规划\n\n## Semantic tasks\n\n内容')
      }
    })

    expect(wrapper.find('.editor-document__header h1').text()).toBe('mission.md')
    await modeButtons(wrapper).at(1)!.trigger('click')
    await nextTick()
    expect(wrapper.find('.editor-document__body h1').text()).toBe('设备人员规划')
    expect(wrapper.find('.editor-document__body h2').text()).toBe('Semantic tasks')
  })

  it('keeps the document body as an independently scrollable surface', async () => {
    const wrapper = mount(MissionEditor, {
      props: { projection: projection(), entry: entry('## Long document\n\n内容') }
    })

    expect(wrapper.find('.mission-editor').classes()).toContain('mission-editor')
    await modeButtons(wrapper).at(1)!.trigger('click')
    await nextTick()
    expect(wrapper.find('.editor-document__body').exists()).toBe(true)
  })

  it('renders current semantic and historical Run revision labels without using legacy goal', async () => {
    const value = projection()
    value.missionDisplay = { objective: '当前正式目标', sourceType: 'SEMANTIC' }
    value.missionSemanticView = { missionId: 'mission_1', semanticStatus: 'INITIALIZED', missionRevision: 2,
      objective: '当前正式目标', constraints: [], sourceReferences: [], sourceStatus: 'NOT_APPLICABLE' }
    value.selectedRunBasisStatus = 'BOUND'
    value.selectedRunBasis = { missionId: 'mission_1', basisSchemaVersion: 1, fingerprintVersion: 1,
      sourceType: 'SEMANTIC', sourceRevision: 1, objective: '历史 Run 目标', constraints: [],
      sourceReferences: [], sourceStatus: 'NOT_APPLICABLE', fingerprint: 'abc' }
    const wrapper = mount(MissionEditor, { props: { projection: value, entry: entry('') } })
    await modeButtons(wrapper).at(1)!.trigger('click')
    await nextTick()
    expect(wrapper.find('.editor-document__body h1').text()).toBe('当前正式目标')
    expect(wrapper.text()).toContain('正式目标 · revision 2')
    expect(wrapper.text()).toContain('SEMANTIC · revision 1')
  })
})
