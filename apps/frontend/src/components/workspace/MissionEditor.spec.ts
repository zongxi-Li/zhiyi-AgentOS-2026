import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MissionEditor from './MissionEditor.vue'
import type { MissionWorkspaceProjection, WorkspaceEntry } from '@/services/api/agentos'

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

describe('MissionEditor', () => {
  it('keeps the editor chrome compact and renders the full mission heading in the document', () => {
    const wrapper = mount(MissionEditor, {
      props: {
        projection: projection(),
        entry: entry('# 设备人员规划\n\n## Semantic tasks\n\n内容')
      }
    })

    expect(wrapper.find('.editor-document__header h1').text()).toBe('mission.md')
    expect(wrapper.find('.editor-document__body h1').text()).toBe('设备人员规划')
    expect(wrapper.find('.editor-document__body h2').text()).toBe('Semantic tasks')
  })

  it('keeps the document body as an independently scrollable surface', () => {
    const wrapper = mount(MissionEditor, {
      props: { projection: projection(), entry: entry('## Long document\n\n内容') }
    })

    expect(wrapper.find('.mission-editor').classes()).toContain('mission-editor')
    expect(wrapper.find('.editor-document__body').exists()).toBe(true)
  })

  it('renders current semantic and historical Run revision labels without using legacy goal', () => {
    const value = projection()
    value.missionDisplay = { objective: '当前正式目标', sourceType: 'SEMANTIC' }
    value.missionSemanticView = { missionId: 'mission_1', semanticStatus: 'INITIALIZED', missionRevision: 2,
      objective: '当前正式目标', constraints: [], sourceReferences: [], sourceStatus: 'NOT_APPLICABLE' }
    value.selectedRunBasisStatus = 'BOUND'
    value.selectedRunBasis = { missionId: 'mission_1', basisSchemaVersion: 1, fingerprintVersion: 1,
      sourceType: 'SEMANTIC', sourceRevision: 1, objective: '历史 Run 目标', constraints: [],
      sourceReferences: [], sourceStatus: 'NOT_APPLICABLE', fingerprint: 'abc' }
    const wrapper = mount(MissionEditor, { props: { projection: value, entry: entry('') } })
    expect(wrapper.find('.editor-document__body h1').text()).toBe('当前正式目标')
    expect(wrapper.text()).toContain('正式目标 · revision 2')
    expect(wrapper.text()).toContain('SEMANTIC · revision 1')
  })
})
