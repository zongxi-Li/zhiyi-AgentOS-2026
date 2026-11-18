import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import AgentPoolPanel from './AgentPoolPanel.vue'
import { agentosApi } from '@/services/api/agentos'

vi.mock('@/services/api/agentos', () => ({ agentosApi: { getAgentPool: vi.fn() } }))

const snapshot = {
  observedAt: '2026-11-15T06:00:00Z', total: 2,
  instances: [
    { registration: { registryId: 'r', instanceId: 'seed', agentId: 'analyst', generation: 1, resourceId: 'resource-seed', definitionDigest: 'd' }, resourceId: 'resource-seed', agentId: 'analyst', agentName: '分析 Agent', domain: 'general', capabilities: ['analysis'], definitionVersion: '1', host: { runtimeId: 'host', displayName: '本地执行宿主', environment: 'device', runtimeKind: 'execution_backend', enabled: true }, enabled: true, draining: false, outcomeUnknown: false, health: { healthy: true, lastHeartbeat: '2026-11-15T06:00:00Z' }, capacity: 1, activeSlots: 0, activeSteps: [] },
    { registration: { registryId: 'r', instanceId: 'replica', agentId: 'analyst', generation: 1, resourceId: 'resource-replica', definitionDigest: 'd' }, resourceId: 'resource-replica', agentId: 'analyst', agentName: '分析 Agent', domain: 'general', capabilities: ['analysis'], definitionVersion: '1', host: { runtimeId: 'host', displayName: '本地执行宿主', environment: 'device', runtimeKind: 'execution_backend', enabled: true }, enabled: true, draining: false, outcomeUnknown: false, health: { healthy: true, lastHeartbeat: '2026-11-15T06:00:00Z' }, capacity: 1, activeSlots: 1, activeSteps: [{ runId: 'run-1', missionId: 'mission-1', stepId: 'step-1', stepName: '分析材料', status: 'running', startedAt: '2026-11-15T06:00:00Z' }] }
  ]
}

describe('AgentPoolPanel', () => {
  beforeEach(() => vi.mocked(agentosApi.getAgentPool).mockResolvedValue(snapshot as any))

  it('shows instances and currently running steps, then opens the selected run', async () => {
    const wrapper = mount(AgentPoolPanel, { global: { stubs: { ElIcon: { template: '<span><slot /></span>' } } } })
    await flushPromises()
    expect(wrapper.text()).toContain('2个执行实例')
    expect(wrapper.text()).toContain('分析材料')
    expect(wrapper.text()).toContain('1 个实例占用中')
    await wrapper.get('.active-step').trigger('click')
    expect(wrapper.emitted('select-run')).toEqual([['run-1']])
    wrapper.unmount()
  })
  it('highlights the exact instance and keeps retired identities distinct from current replicas', async () => {
    const wrapper = mount(AgentPoolPanel, { props: { selectedInstanceId: 'replica' } })
    await flushPromises()
    expect(wrapper.findAll('.is-selected')).toHaveLength(1)
    expect(wrapper.get('.is-selected .agent-title').text()).toContain('replica')
    expect(wrapper.get('.is-selected').text()).toContain('device · 本地执行宿主')
    expect(wrapper.get('.is-selected .capabilities').text()).toContain('analysis')
    await wrapper.setProps({ selectedInstanceId: 'retired-instance' })
    expect(wrapper.findAll('.is-selected')).toHaveLength(0)
    expect(wrapper.get('.pool-selection-note').text()).toContain('retired-instance')
    wrapper.unmount()
  })
})
