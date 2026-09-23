import RuntimeCommunicationPanel from './RuntimeCommunicationPanel.vue'
import RuntimeEventsPanel from './RuntimeEventsPanel.vue'
import RuntimeToolCallsPanel from './RuntimeToolCallsPanel.vue'
import RuntimeTracePanel from './RuntimeTracePanel.vue'
import RuntimeAuditSidebarView from './RuntimeAuditSidebarView.vue'
import RuntimeCommunicationSidebarView from './RuntimeCommunicationSidebarView.vue'
import RuntimeContextSidebarView from './RuntimeContextSidebarView.vue'
import type { WorkbenchContribution } from '@/workbench/types'
import { projectRuntimeObservation } from '@/workbench/runtime/runtimePresentation'

/** Read-only runtime observation panels backed by RuntimeObservationAdapter. */
export const runtimeContribution: WorkbenchContribution = {
  id: 'runtime-observation',
  secondarySidebarViews: [
    {
      id: 'runtime.communication-view',
      title: '通信',
      order: 300,
      component: RuntimeCommunicationSidebarView,
      when: () => true
    },
    {
      id: 'runtime.audit-view',
      title: '审计',
      order: 400,
      component: RuntimeAuditSidebarView,
      when: () => true
    },
    {
      id: 'runtime.context-view',
      title: '上下文',
      order: 500,
      component: RuntimeContextSidebarView,
      when: () => true
    }
  ],
  panels: [
    {
      id: 'communication',
      label: 'Communication',
      component: RuntimeCommunicationPanel,
      count: context => context.runtimeObservation?.communication.length ?? 0,
      getProps: context => ({ runtimeObservation: context.runtimeObservation })
    },
    {
      id: 'trace',
      label: 'Trace',
      component: RuntimeTracePanel,
      count: context => context.runtimeObservation?.traces.length ?? 0,
      getProps: context => ({ runtimeObservation: context.runtimeObservation })
    },
    {
      id: 'events',
      label: 'Events',
      component: RuntimeEventsPanel,
      count: context => projectRuntimeObservation(context.runtimeObservation).length,
      getProps: context => ({ runtimeObservation: context.runtimeObservation })
    },
    {
      id: 'tool-calls',
      label: 'Tool Calls',
      component: RuntimeToolCallsPanel,
      count: context => context.runtimeObservation?.toolCalls.length ?? 0,
      getProps: context => ({ runtimeObservation: context.runtimeObservation })
    }
  ]
}
