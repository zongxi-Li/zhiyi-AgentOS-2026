import { agentosRequest } from './client'
import { createMissionApi } from './api/mission'
import { createWorkflowApi } from './api/workflow'
import { createWorkspaceApi } from './api/workspace'
import { createArtifactsApi } from './api/artifacts'
import { createRuntimeApi } from './api/runtime'
import { createAcgApi } from './api/acg'
import { createCopilotApi } from './api/copilot'
import { createC2Api } from './api/c2'

const missionApi = createMissionApi()
const runtimeApi = createRuntimeApi()
type AgentosApi = ReturnType<typeof createMissionApi>
  & ReturnType<typeof createWorkflowApi>
  & ReturnType<typeof createWorkspaceApi>
  & ReturnType<typeof createArtifactsApi>
  & ReturnType<typeof createRuntimeApi>
  & ReturnType<typeof createAcgApi>
  & ReturnType<typeof createCopilotApi>
  & ReturnType<typeof createC2Api>
let api: AgentosApi
const getApi = () => api

api = {
  ...missionApi,
  ...createWorkflowApi(getApi),
  ...createWorkspaceApi(),
  ...createArtifactsApi(getApi),
  ...runtimeApi,
  ...createAcgApi(getApi),
  ...createCopilotApi(),
  ...createC2Api()
}

export const agentosApi = api
export { agentosRequest }
