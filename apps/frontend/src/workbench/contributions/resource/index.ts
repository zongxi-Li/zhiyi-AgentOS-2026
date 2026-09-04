import NodeResourceInspector from './NodeResourceInspector.vue'
import RunResourceInspector from './RunResourceInspector.vue'
import ResourceSidebarView from './ResourceSidebarView.vue'
import type { WorkbenchContribution } from '@/workbench/types'

export const resourceContribution: WorkbenchContribution = {
  id: 'resource',
  inspectorSections: [
    {
      id: 'resource.node',
      title: 'Resource',
      order: 200,
      component: NodeResourceInspector,
      when: context => Boolean(context.graphNode)
    },
    {
      id: 'resource.run',
      title: 'Resource',
      order: 200,
      component: RunResourceInspector,
      when: context => context.entry?.kind === 'run'
    }
  ],
  secondarySidebarViews: [
    {
      id: 'resource.view',
      title: '资源',
      order: 200,
      component: ResourceSidebarView,
      when: () => true
    }
  ]
}
