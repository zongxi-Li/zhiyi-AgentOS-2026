import { FolderOpened } from '@element-plus/icons-vue'
import GraphEditor from '@/components/workspace/GraphEditor.vue'
import ArtifactEditor from '@/components/workspace/ArtifactEditor.vue'
import MissionEditor from '@/components/workspace/MissionEditor.vue'
import WorkspaceExplorer from '@/components/workspace/WorkspaceExplorer.vue'
import ProblemsPanel from '@/components/workbench/ProblemsPanel.vue'
import ProjectArtifactInspector from './ProjectArtifactInspector.vue'
import ProjectGraphInspector from './ProjectGraphInspector.vue'
import ProjectMissionInspector from './ProjectMissionInspector.vue'
import ProjectNodeInspector from './ProjectNodeInspector.vue'
import ProjectRunInspector from './ProjectRunInspector.vue'
import type { WorkbenchContribution } from '@/workbench/types'

export const projectContribution: WorkbenchContribution = {
  id: 'project',
  activityBar: [
    { id: 'project.activity', label: 'Projects', icon: FolderOpened, routeName: 'AcgVisualization' }
  ],
  sidebarViews: [
    { id: 'project.explorer', title: 'Project Explorer', component: WorkspaceExplorer }
  ],
  editors: [
    { id: 'project.graph-editor', entryKinds: ['graph'], component: GraphEditor, title: entry => entry.name },
    { id: 'project.artifact-editor', entryKinds: ['artifact'], component: ArtifactEditor, title: entry => entry.name },
    { id: 'project.mission-editor', entryKinds: ['virtual_document'], component: MissionEditor, title: entry => entry.name }
  ],
  inspectors: [
    { id: 'project.node-inspector', component: ProjectNodeInspector, matches: context => Boolean(context.graphNode && context.entry?.kind === 'graph') },
    { id: 'project.graph-inspector', component: ProjectGraphInspector, matches: context => context.entry?.kind === 'graph' && !context.graphNode },
    { id: 'project.artifact-inspector', component: ProjectArtifactInspector, matches: context => context.entry?.kind === 'artifact' },
    { id: 'project.run-inspector', component: ProjectRunInspector, matches: context => context.entry?.kind === 'run' },
    { id: 'project.selected-node-inspector', component: ProjectNodeInspector, matches: context => Boolean(context.graphNode) },
    { id: 'project.mission-inspector', component: ProjectMissionInspector, matches: () => true }
  ],
  panels: [
    {
      id: 'problems',
      label: 'Problems',
      component: ProblemsPanel,
      count: context => context.diagnostics.length,
      getProps: context => ({ diagnostics: context.diagnostics })
    }
  ]
}
