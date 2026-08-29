import type {
  CommandContribution,
  EditorContribution,
  ActivityBarContribution,
  InspectorContribution,
  PanelContribution,
  SidebarViewContribution,
  WorkbenchContext,
  WorkbenchContribution,
  WorkbenchInspectorContext
} from './types'
import type { WorkspaceEntry } from '@/services/api/agentos'

const contributionItems = <T extends { id: string }>(contributions: Iterable<WorkbenchContribution>, slot: keyof WorkbenchContribution): T[] => {
  const items: T[] = []
  for (const contribution of contributions) {
    const values = contribution[slot] as unknown as readonly T[] | undefined
    if (values) items.push(...values)
  }
  return items
}

export class WorkbenchContributionRegistry {
  private readonly contributions = new Map<string, WorkbenchContribution>()

  register(contribution: WorkbenchContribution): this {
    if (!contribution.id.trim()) throw new Error('Workbench contribution id is required')
    if (this.contributions.has(contribution.id)) {
      throw new Error(`Duplicate Workbench contribution: ${contribution.id}`)
    }
    this.contributions.set(contribution.id, contribution)
    return this
  }

  get(id: string): WorkbenchContribution | undefined {
    return this.contributions.get(id)
  }

  list(): WorkbenchContribution[] {
    return [...this.contributions.values()]
  }

  getActivityBar(): ActivityBarContribution[] {
    return contributionItems<ActivityBarContribution>(this.contributions.values(), 'activityBar')
  }

  getSidebarViews(context: WorkbenchContext): SidebarViewContribution[] {
    return contributionItems<SidebarViewContribution>(this.contributions.values(), 'sidebarViews')
      .filter(view => view.isVisible?.(context) ?? true)
  }

  getEditors(): EditorContribution[] {
    return contributionItems<EditorContribution>(this.contributions.values(), 'editors')
  }

  resolveEditor(entry: WorkspaceEntry | null, context: WorkbenchContext): EditorContribution | null {
    if (!entry) return null
    return this.getEditors().find(editor => (
      editor.entryKinds.includes(entry.kind) && (editor.canOpen?.(entry, context) ?? true)
    )) || null
  }

  getInspectors(): InspectorContribution[] {
    return contributionItems<InspectorContribution>(this.contributions.values(), 'inspectors')
  }

  resolveInspector(context: WorkbenchInspectorContext): InspectorContribution | null {
    return this.getInspectors().find(inspector => inspector.matches(context)) || null
  }

  getPanels(context: WorkbenchContext): PanelContribution[] {
    return contributionItems<PanelContribution>(this.contributions.values(), 'panels')
      .filter(panel => panel.isVisible?.(context) ?? true)
  }

  resolvePanel(id: string, context: WorkbenchContext): PanelContribution | null {
    return this.getPanels(context).find(panel => panel.id === id) || null
  }

  getCommands(): CommandContribution[] {
    return contributionItems<CommandContribution>(this.contributions.values(), 'commands')
  }

  resolveCommand(id: string): CommandContribution | null {
    return this.getCommands().find(command => command.id === id) || null
  }
}

export const createWorkbenchRegistry = () => new WorkbenchContributionRegistry()
