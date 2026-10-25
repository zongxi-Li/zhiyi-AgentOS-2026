import { describe, expect, it, vi } from 'vitest'
import { agentosApi, agentosRequest } from '@/services/api/agentos'
import type { FormalAction } from './c2'

describe('formal control transport', () => {
  it.each([
    ['materialize', 'graph/materializations'], ['activate', 'graph/activation'], ['handoff', 'graph/handoffs'],
    ['permit', 'graph/permits'], ['dispatch', 'execution/dispatches']
  ])('posts %s only to its existing formal route', async (action, suffix) => {
    const post = vi.spyOn(agentosRequest, 'post').mockResolvedValue({ data: { operationId: 'op', status: 'ACCEPTED' } })
    const request = { operationId: 'op', expectedPermitId: 'permit', expectedGraphId: 'graph', expectedGraphVersion: 1, expectedRuntimeRevision: 7 }
    expect(await agentosApi.submitFormalControl('mission space', 'run/segment', action as FormalAction, request)).toEqual({ operationId: 'op', status: 'ACCEPTED' })
    expect(post).toHaveBeenCalledWith(`/missions/mission%20space/runs/run%2Fsegment/${suffix}`, request)
    post.mockRestore()
  })
})
