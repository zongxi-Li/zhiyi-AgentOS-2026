import { createWorkbenchRegistry, type WorkbenchContributionRegistry } from './registry'
import { projectContribution } from './contributions/project'
import { resourceContribution } from './contributions/resource'
import { runtimeContribution } from './contributions/runtime'

export const createNativeWorkbenchRegistry = (): WorkbenchContributionRegistry => (
  createWorkbenchRegistry()
    .register(projectContribution)
    .register(resourceContribution)
    .register(runtimeContribution)
)
