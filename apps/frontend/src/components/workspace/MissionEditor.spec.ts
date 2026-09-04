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
})
