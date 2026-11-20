import { describe, expect, it, vi } from 'vitest'
import type { MissionWorkspaceProjection } from '@/services/api/agentos'
import { CompanionRuntimeBridge } from './runtimeBridge'
import { useCompanionRuntime } from './useCompanionRuntime'

const projection = (runId: string, status = 'running') => ({ mission: { missionId: 'm' }, activeRun: { runId, status }, runs: [{ runId, status }] } as MissionWorkspaceProjection)

describe('Companion persistent runtime display', () => {
  it('starts from verified status, ignores other runs and clears on switch/disposal', () => {
    const bridge = new CompanionRuntimeBridge(), owner = Symbol('workspace')
    const changed = vi.fn(), notice = vi.fn()
    const runtime = useCompanionRuntime({ bridge, onChange: changed, onNotice: notice })
    runtime.start()
    bridge.activate(owner)
    bridge.selectVerified(owner, projection('a'), 'm')
    expect(runtime.state.value).toBe('working')
    bridge.publishAccepted({ eventId: 'other', eventType: 'run.failed', runId: 'b', sequence: 1 })
    expect(runtime.state.value).toBe('working')
    bridge.publishAccepted({ eventId: 'bad', eventType: 'run.failed', runId: 'a', sequence: 1 })
    expect(runtime.state.value).toBe('error')
    expect(notice).toHaveBeenCalledOnce()
    bridge.selectVerified(owner, projection('b', 'pending'), 'm')
    expect(runtime.state.value).toBe('thinking')
    bridge.clear(owner)
    expect(runtime.state.value).toBeNull()
    runtime.dispose()
    changed.mockClear()
    bridge.selectVerified(owner, projection('a'), 'm')
    expect(changed).not.toHaveBeenCalled()
  })

  it('holds errors above routine progress but lets definitive completion and approval resolution settle', () => {
    const bridge = new CompanionRuntimeBridge(), owner = Symbol('workspace')
    const runtime = useCompanionRuntime({ bridge, onChange: vi.fn(), onNotice: vi.fn() })
    runtime.start(); bridge.activate(owner); bridge.selectVerified(owner, projection('a'), 'm')
    let sequence = 0
    const send = (eventType: string) => bridge.publishAccepted({ eventId: `${++sequence}`, eventType, runId: 'a', sequence })
    send('tool.approval_required'); expect(runtime.state.value).toBe('alert')
    send('tool.approval_resolved'); expect(runtime.state.value).toBe('working')
    send('node.failed'); send('node.started'); expect(runtime.state.value).toBe('error')
    send('run.completed'); expect(runtime.state.value).toBe('happy')
    runtime.dispose()
  })
})
