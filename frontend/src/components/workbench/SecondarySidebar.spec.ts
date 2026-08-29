import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import type { RuntimeObservation } from '@/workbench/runtime/observation'
import { createWorkbenchRegistry } from '@/workbench/registry'
import { createWorkbenchContext } from '@/workbench/context'
import SecondarySidebar from './SecondarySidebar.vue'
import ProjectRunSidebarView from '@/workbench/contributions/project/ProjectRunSidebarView.vue'
import ResourceSidebarView from '@/workbench/contributions/resource/ResourceSidebarView.vue'
import RuntimeAuditSidebarView from '@/workbench/contributions/runtime/RuntimeAuditSidebarView.vue'
import RuntimeCommunicationSidebarView from '@/workbench/contributions/runtime/RuntimeCommunicationSidebarView.vue'
import RuntimeContextSidebarView from '@/workbench/contributions/runtime/RuntimeContextSidebarView.vue'
import type { WorkbenchContext } from '@/workbench/types'
import type { WorkspaceEntry, WorkspaceGraphNode } from '@/services/api/agentos'

const graphEntry: WorkspaceEntry = {
  entryId: 'overview:graph.acg',
  kind: 'graph',
  name: 'graph.acg',
  group: 'overview',
  displayOrder: 0,
  graphId: 'graph_1',
  graphVersion: 1
}

const taskEntry: WorkspaceEntry = {
  entryId: 'task:capacity',
  kind: 'task',
  name: 'Capacity',
  group: 'steps',
  displayOrder: 0,
  semanticTaskKey: 'capacity',
  taskId: 'task_capacity',
  objective: 'Form a capacity plan',
  dependencyKeys: ['scope'],
  status: 'completed',
  attemptCount: 1,
  latestAttemptId: 'attempt_capacity',
  artifactCount: 2,
  acgNodeId: 'node_capacity',
  identityQuality: 'canonical'
}

const artifactEntry: WorkspaceEntry = {
  entryId: 'task:capacity:primary',
  kind: 'artifact',
  name: 'primary.md',
  group: 'steps',
  displayOrder: 0,
  semanticTaskKey: 'capacity',
  artifactKey: 'primary',
  artifactId: 'artifact_1',
  contentRef: 'manifest_1',
  attemptId: 'attempt_capacity',
  runId: 'run_1',
  identityQuality: 'canonical'
}

const node: WorkspaceGraphNode = {
  acgNodeId: 'node_capacity',
  nodeType: 'step',
  name: 'Capacity',
  semanticTaskKey: 'capacity',
  taskId: 'task_capacity',
  displayOrder: 0,
  status: 'completed',
  attemptId: 'attempt_capacity',
  artifactCount: 2,
  identityQuality: 'canonical'
}

const baseContext = (): WorkbenchContext => createWorkbenchContext({
  missionId: 'mission_1',
  runId: 'run_1',
  activeEditorId: graphEntry.entryId,
  activeEntryKind: 'graph',
  runtimeObservation: runtimeObservation('run_1')
})

const runtimeObservation = (runId: string): RuntimeObservation => ({
  runId,
  runStatus: 'succeeded',
  traces: [],
  events: [],
  communication: [],
  toolCalls: [],
  problems: [],
  audit: {
    provenanceStatus: null,
    provenanceRecordCount: 0,
    evidenceCount: 0,
    contractViolationCount: 0,
    recoveryCount: 0
  },
  resourceObservation: null,
  unavailableSources: []
})

const inspectorContext = (overrides: Partial<{
  context: WorkbenchContext
  entry: WorkspaceEntry | null
  graphNode: WorkspaceGraphNode | null
}> = {}) => ({
  ...(overrides.context || baseContext()),
  entry: overrides.entry === undefined ? graphEntry : overrides.entry,
  graphNode: overrides.graphNode === undefined ? null : overrides.graphNode,
  available: true,
  graph: { graphId: 'graph_1', nodes: [], edges: [], metadata: { graphVersion: 1 } },
  runStatus: 'succeeded'
})

const viewProps = (context: ReturnType<typeof inspectorContext>) => ({
  entry: context.entry,
  graphNode: context.graphNode,
  graphNodes: [node],
  available: context.available,
  runId: context.runId,
  missionId: context.missionId,
  graph: context.graph,
  runStatus: context.runStatus,
  historical: context.historicalMode,
  resourceObservation: context.runtimeObservation?.resourceObservation || null,
  runtimeObservation: context.runtimeObservation
})

const createSecondaryRegistry = () => createWorkbenchRegistry().register({
  id: 'native-secondary-sidebar',
  secondarySidebarViews: [
    { id: 'project.run-view', title: '运行', order: 100, component: ProjectRunSidebarView, when: () => true },
    { id: 'resource.view', title: '资源', order: 200, component: ResourceSidebarView, when: () => true },
    { id: 'runtime.communication-view', title: '通信', order: 300, component: RuntimeCommunicationSidebarView, when: () => true },
    { id: 'runtime.audit-view', title: '审计', order: 400, component: RuntimeAuditSidebarView, when: () => true },
    { id: 'runtime.context-view', title: '上下文', order: 500, component: RuntimeContextSidebarView, when: () => true }
  ]
})

const mountSidebar = (overrides: Partial<{
  context: WorkbenchContext
  entry: WorkspaceEntry | null
  graphNode: WorkspaceGraphNode | null
  historical: boolean
  runId: string | null
}> = {}) => {
  const context = inspectorContext({
    context: overrides.context,
    entry: overrides.entry,
    graphNode: overrides.graphNode
  })
  return mount(SecondarySidebar, {
    props: {
      registry: createSecondaryRegistry(),
      context,
      title: context.entry?.name || 'Mission',
      historical: overrides.historical || false,
      componentProps: viewProps(context)
    }
  })
}

describe('SecondarySidebar', () => {
  afterEach(() => {
    localStorage.clear()
  })

  it('resolves the five native views and defaults to Run', () => {
    const registry = createSecondaryRegistry()
    const context = {
      ...baseContext(),
      entry: graphEntry,
      graphNode: null,
      available: true,
      graph: null,
      runStatus: 'succeeded'
    }
    expect(registry.resolveSecondarySidebarViews(context).map(view => view.title)).toEqual(['运行', '资源', '通信', '审计', '上下文'])
    const wrapper = mountSidebar()
    expect(wrapper.find('.secondary-sidebar__tabs button.is-active').text()).toBe('运行')
    expect(wrapper.text()).toContain('图信息')
  })

  it('switches views and persists only the selected view id', async () => {
    const wrapper = mountSidebar()
    for (const [label, content] of [['资源', '运行资源'], ['通信', '通信摘要'], ['审计', '审计状态'], ['上下文', '上下文数据']]) {
      await wrapper.findAll('.secondary-sidebar__tabs button').find(button => button.text() === label)?.trigger('click')
      expect(wrapper.find('.secondary-sidebar__tabs button.is-active').text()).toBe(label)
      expect(wrapper.text()).toContain(content)
    }
    expect(localStorage.getItem('zhiyi.mission.workspace.secondary-sidebar.view.v1')).toBe('runtime.context-view')
    expect(localStorage.getItem('zhiyi.mission.workspace.secondary-sidebar.view.v1')).not.toContain('run_1')
  })

  it('renders task and artifact context without retaining the previous selection', async () => {
    const wrapper = mountSidebar()
    const taskContext = inspectorContext({
      context: createWorkbenchContext({
        ...baseContext(),
        activeEditorId: taskEntry.entryId,
        activeEntryKind: 'task',
        selectedSemanticTaskKey: 'capacity',
        selectedAcgNodeId: node.acgNodeId
      }),
      entry: taskEntry,
      graphNode: node
    })
    await wrapper.setProps({
      context: taskContext,
      componentProps: viewProps(taskContext)
    })
    expect(wrapper.text()).toContain('task_capacity')
    expect(wrapper.text()).toContain('attempt_capacity')

    const artifactContext = inspectorContext({
      context: createWorkbenchContext({
        ...baseContext(),
        activeEditorId: artifactEntry.entryId,
        activeEntryKind: 'artifact',
        selectedSemanticTaskKey: 'capacity',
        selectedArtifactId: 'artifact_1'
      }),
      entry: artifactEntry,
      graphNode: null
    })
    await wrapper.setProps({
      context: artifactContext,
      componentProps: viewProps(artifactContext)
    })
    expect(wrapper.text()).toContain('artifact_1')
    expect(wrapper.text()).not.toContain('task_capacity')
  })

  it('refreshes the active view when switching runs and marks historical context', async () => {
    const context = inspectorContext({
      context: createWorkbenchContext({
        ...baseContext(),
        runId: 'run_2',
        historicalMode: true,
        runtimeObservation: runtimeObservation('run_2')
      })
    })
    const wrapper = mountSidebar()
    await wrapper.setProps({
      context,
      historical: true,
      componentProps: viewProps(context)
    })
    expect(wrapper.text()).toContain('run_2')
    expect(wrapper.text()).not.toContain('run_1')
    expect(wrapper.text()).toContain('Historical')
    expect(wrapper.find('.secondary-sidebar__body').exists()).toBe(true)
  })
})
