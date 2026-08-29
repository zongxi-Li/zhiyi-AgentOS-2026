import { defineComponent } from 'vue'
import { describe, expect, it } from 'vitest'
import { createWorkbenchRegistry } from './registry'
import type { WorkbenchContext, WorkbenchInspectorContext } from './types'

const component = defineComponent({ template: '<div />' })

const context: WorkbenchContext = {
  missionId: 'mission_1',
  runId: 'run_1',
  selectedSemanticTaskKey: null,
  selectedArtifactId: null,
  selectedAcgNodeId: null,
  activeEditorId: 'overview:graph.acg',
  activeEntryKind: 'graph',
  historicalMode: false,
  diagnostics: []
}

const inspectorContext: WorkbenchInspectorContext = {
  ...context,
  entry: { entryId: 'overview:graph.acg', kind: 'graph', name: 'graph.acg', group: 'overview', displayOrder: 0 },
  graphNode: null,
  available: true,
  graph: null,
  runStatus: 'succeeded'
}

describe('WorkbenchContributionRegistry', () => {
  it('registers isolated contributions and rejects duplicate contribution ids', () => {
    const registry = createWorkbenchRegistry()
    registry.register({ id: 'project', commands: [{ id: 'project.open', title: 'Open', execute: () => undefined }] })

    expect(registry.list()).toHaveLength(1)
    expect(() => registry.register({ id: 'project' })).toThrow('Duplicate Workbench contribution: project')
  })

  it('resolves editors by entry kind and canOpen policy', () => {
    const registry = createWorkbenchRegistry()
    registry.register({
      id: 'project',
      editors: [
        { id: 'graph', entryKinds: ['graph'], component, title: entry => `Editor: ${entry.name}` },
        { id: 'artifact', entryKinds: ['artifact'], component, canOpen: entry => entry.identityQuality !== 'legacy' }
      ]
    })

    const graph = { entryId: 'graph', kind: 'graph' as const, name: 'graph.acg', group: 'overview' as const, displayOrder: 0 }
    const legacyArtifact = { entryId: 'artifact', kind: 'artifact' as const, name: 'legacy.md', group: 'steps' as const, displayOrder: 0, identityQuality: 'legacy' as const }

    expect(registry.resolveEditor(graph, context)?.title?.(graph, context)).toBe('Editor: graph.acg')
    expect(registry.resolveEditor(legacyArtifact, context)).toBeNull()
  })

  it('resolves inspector, panel and command contributions deterministically', () => {
    const registry = createWorkbenchRegistry()
    registry.register({
      id: 'project',
      inspectors: [{ id: 'graph-inspector', component, matches: value => value.entry?.kind === 'graph' }],
      panels: [{ id: 'problems', label: 'Problems', component, count: value => value.diagnostics.length }],
      commands: [{ id: 'workbench.togglePanel', title: 'Toggle panel', execute: () => undefined }]
    })

    expect(registry.resolveInspector(inspectorContext)?.id).toBe('graph-inspector')
    expect(registry.getPanels(context)[0]?.count?.(context)).toBe(0)
    expect(registry.resolveCommand('workbench.togglePanel')?.title).toBe('Toggle panel')
    expect(registry.resolveCommand('missing')).toBeNull()
  })
})
