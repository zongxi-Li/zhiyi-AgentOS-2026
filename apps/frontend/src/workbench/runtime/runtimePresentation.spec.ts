import { describe, expect, it } from 'vitest'
import type { RuntimeTraceObservation } from './observation'
import { projectRuntimePresentations, type RuntimePresentationInput } from './runtimePresentation'

const event = (
  sequence: number,
  eventType: string,
  payload: Record<string, unknown> = {},
  overrides: Partial<RuntimePresentationInput> = {}
): RuntimePresentationInput => ({
  eventId: `event-${sequence}-${eventType}`,
  eventType,
  runId: 'run-1',
  nodeId: 'node-1',
  attemptId: 'attempt-1',
  sequence,
  timestamp: `2026-09-23T10:00:${String(sequence).padStart(2, '0')}Z`,
  payload,
  ...overrides
})

describe('runtime presentation projection', () => {
  it('classifies the supported semantic kinds', () => {
    const items = projectRuntimePresentations([
      event(1, 'model.started', { model: 'deepseek-chat' }),
      event(2, 'tool_called', { tool: 'read_file', status: 'succeeded', path: 'README.md' }),
      event(3, 'command.completed', { command: 'pnpm test', status: 'completed' }),
      event(4, 'data_produced', { artifactRef: 'artifact:report', status: 'produced' }),
      event(5, 'node.failed', { errorCode: 'MODEL_TIMEOUT', message: 'request timed out' }),
      event(6, 'run.completed', { status: 'completed' })
    ])

    expect(items.map(item => item.kind)).toEqual(['model', 'tool', 'command', 'artifact', 'error', 'completion'])
  })

  it('aggregates model lifecycle and delta events into one activity', () => {
    const items = projectRuntimePresentations([
      event(1, 'model.started', { model: 'deepseek-chat' }),
      event(2, 'model.first_token', { ttftMs: 142 }),
      event(3, 'model.output.delta', { delta: 'first ' }),
      event(4, 'model.output.delta', { delta: 'answer' }),
      event(5, 'model.completed', { durationMs: 930, status: 'completed', data: { answer: 'final' } })
    ])

    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({
      kind: 'model',
      status: 'success',
      title: '模型 · deepseek-chat',
      durationMs: 930,
      metrics: { events: 5, chunks: 2, ttftMs: 142 }
    })
    expect(items[0].eventIds).toHaveLength(5)
    expect(items[0].detail).toContain('final')
  })

  it('keeps unknown events visible through generic fallback', () => {
    const [item] = projectRuntimePresentations([
      event(1, 'runtime.future_signal', { opaque: { value: 1 } })
    ])

    expect(item.kind).toBe('generic')
    expect(item.title).toBe('runtime.future_signal')
    expect(item.details.some(detail => detail.label === 'opaque')).toBe(true)
  })

  it('removes reasoning and credentials from model, generic, and nested data details', () => {
    const cyclic: Record<string, unknown> = {
      safe: 'visible',
      reasoning_content: 'private model reasoning',
      internalThought: 'hidden chain of thought',
      apiKey: 'sk-example-secret-1234567890',
      credentials: { access_token: 'nested-access-token' },
      message: 'Authorization: Bearer very-secret-value'
    }
    cyclic.loop = cyclic

    const items = projectRuntimePresentations([
      event(1, 'model.completed', {
        status: 'completed',
        data: {
          result: 'visible result',
          reasoning_content: 'must not render',
          internal_reasoning: 'must not render',
          password: 'private-password'
        }
      }),
      event(2, 'runtime.future_signal', cyclic),
      event(3, 'runtime.json_blob', {
        payload_blob: '{"safe":"visible JSON","reasoning_content":"hidden JSON reasoning","access_token":"hidden JSON token"}'
      })
    ])
    const rendered = JSON.stringify(items)

    expect(rendered).toContain('visible result')
    expect(rendered).toContain('visible')
    expect(rendered).not.toContain('private model reasoning')
    expect(rendered).not.toContain('hidden chain of thought')
    expect(rendered).not.toContain('sk-example-secret-1234567890')
    expect(rendered).not.toContain('nested-access-token')
    expect(rendered).not.toContain('private-password')
    expect(rendered).not.toContain('very-secret-value')
    expect(rendered).not.toContain('must not render')
    expect(rendered).not.toContain('hidden JSON reasoning')
    expect(rendered).not.toContain('hidden JSON token')
    expect(rendered).not.toContain('reasoning_content')
    expect(rendered).not.toContain('access_token')
    expect(rendered).toContain('[circular]')
  })

  it('bounds generic values and does not group calls by step alone', () => {
    const large = Array.from({ length: 80 }, (_, index) => index)
    const items = projectRuntimePresentations([
      event(1, 'runtime.large', {
        large,
        deep: { a: { b: { c: { d: { e: 'must stop at depth limit' } } } } },
        longText: 'x'.repeat(50000)
      }, { attemptId: null }),
      event(2, 'model.started', { model: 'deepseek-chat' }, { attemptId: null }),
      event(3, 'model.output.delta', { delta: 'first invocation' }, { attemptId: null }),
      event(4, 'model.started', { model: 'deepseek-chat' }, { attemptId: null }),
      event(5, 'model.output.delta', { delta: 'second invocation' }, { attemptId: null })
    ])
    const generic = items.find(item => item.kind === 'generic')!
    const models = items.filter(item => item.kind === 'model')

    expect(generic.details.reduce((sum, detail) => sum + detail.value.length, 0)).toBeLessThanOrEqual(2600)
    expect(generic.details.find(detail => detail.label === 'longText')?.value.length).toBeLessThanOrEqual(900)
    expect(generic.details.find(detail => detail.label === 'deep')?.value).toContain('[depth limit]')
    expect(generic.details.find(detail => detail.label === 'large')?.value).not.toContain('12')
    expect(models).toHaveLength(3)
    expect(models.map(item => item.eventIds.length)).toEqual([2, 1, 1])
  })

  it('keeps tool and command calls separate when only the step is shared', () => {
    const items = projectRuntimePresentations([
      event(1, 'tool.started', { tool: 'search' }, { attemptId: null }),
      event(2, 'tool.completed', { tool: 'search', status: 'completed' }, { attemptId: null }),
      event(3, 'command.started', { command: 'first' }, { attemptId: null }),
      event(4, 'command.completed', { command: 'first', status: 'completed' }, { attemptId: null })
    ])

    expect(items.filter(item => item.kind === 'tool')).toHaveLength(2)
    expect(items.filter(item => item.kind === 'command')).toHaveLength(2)
    expect(items.every(item => item.eventIds.length === 1)).toBe(true)
  })

  it('does not merge tool or command lifecycles using a shared step/attempt identity alone', () => {
    const items = projectRuntimePresentations([
      event(1, 'tool.started', { tool: 'search', status: 'running' }),
      event(2, 'tool.started', { tool: 'search', status: 'running' }),
      event(3, 'tool.completed', { tool: 'search', status: 'completed' }),
      event(4, 'command.started', { command: 'build', status: 'running' }),
      event(5, 'command.started', { command: 'build', status: 'running' }),
      event(6, 'command.completed', { command: 'build', status: 'completed' })
    ])

    const tools = items.filter(item => item.kind === 'tool')
    const commands = items.filter(item => item.kind === 'command')
    expect(tools).toHaveLength(3)
    expect(tools.map(item => item.eventIds.length)).toEqual([1, 1, 1])
    expect(commands).toHaveLength(3)
    expect(commands.map(item => item.eventIds.length)).toEqual([1, 1, 1])
  })

  it('aggregates Tool/Command lifecycle events only with call- or execution-scoped identities', () => {
    const items = projectRuntimePresentations([
      event(1, 'tool.started', { tool: 'search', toolCallId: 'tool-a', status: 'running' }),
      event(2, 'tool.completed', { tool: 'search', toolCallId: 'tool-a', status: 'completed' }),
      event(3, 'tool.started', { tool: 'search', toolCallId: 'tool-b', status: 'running' }),
      event(4, 'tool.completed', { tool: 'search', toolCallId: 'tool-b', status: 'completed' }),
      event(5, 'command.started', { command: 'build', executionId: 'exec-a', status: 'running' }),
      event(6, 'command.completed', { command: 'build', executionId: 'exec-a', status: 'completed' })
    ])

    expect(items).toHaveLength(3)
    expect(items.map(item => item.eventIds.length)).toEqual([2, 2, 2])
  })

  it('preserves failed status and useful error detail', () => {
    const [item] = projectRuntimePresentations([
      event(1, 'tool.failed', { tool: 'search', errorCode: 'SEARCH_TIMEOUT', status: 'failed' })
    ])

    expect(item).toMatchObject({ kind: 'tool', status: 'failed', title: 'search' })
    expect(item.details.some(detail => detail.value.includes('SEARCH_TIMEOUT'))).toBe(true)
  })

  it('uses trace-level duration for tool activity', () => {
    const trace: RuntimeTraceObservation = {
      eventId: 'trace-tool-1',
      eventType: 'tool_called',
      timestamp: '2026-09-23T10:00:01Z',
      stepId: 'node-1',
      target: 'read_file',
      observation: 'README.md',
      source: 'runtime',
      durationMs: 821,
      status: 'succeeded',
      payload: { tool: 'read_file', status: 'succeeded' }
    }

    expect(projectRuntimePresentations([trace])[0]).toMatchObject({
      kind: 'tool',
      durationMs: 821,
      status: 'success'
    })
  })

  it('closes a failed model activity before a later retry', () => {
    const items = projectRuntimePresentations([
      event(1, 'model.started', { model: 'deepseek-chat', callKey: 'attempt-a' }),
      event(2, 'model.failed', { callKey: 'attempt-a', errorCode: 'MODEL_TIMEOUT', status: 'failed' }),
      event(3, 'model.started', { model: 'deepseek-chat', callKey: 'attempt-b' })
    ])

    expect(items).toHaveLength(2)
    expect(items.map(item => item.status)).toEqual(['failed', 'running'])
  })

  it('orders sequenced events deterministically and preserves source order for ties', () => {
    const items = projectRuntimePresentations([
      event(3, 'run.completed'),
      event(1, 'node.started'),
      event(2, 'runtime.alpha'),
      event(2, 'runtime.beta')
    ])

    expect(items.map(item => item.title)).toEqual([
      'node.started',
      'runtime.alpha',
      'runtime.beta',
      '运行完成'
    ])
  })
})
