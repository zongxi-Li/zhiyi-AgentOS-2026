import { createWorkbenchRegistry, type WorkbenchContributionRegistry } from './registry'
import { projectContribution } from './contributions/project'

export const createNativeWorkbenchRegistry = (): WorkbenchContributionRegistry => (
  createWorkbenchRegistry().register(projectContribution)
)
