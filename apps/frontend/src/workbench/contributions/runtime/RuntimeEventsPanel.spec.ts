import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import RuntimeEventsPanel from './RuntimeEventsPanel.vue'
import type { RuntimeObservation, RuntimeTraceObservation } from '@/workbench/runtime/observation'

const trace = (
  eventId: string,
  eventType: string,
  sequence: number,
  payload: Record<string, unknown> = {},
  overrides: Partial<RuntimeTraceObservation> = {}
): RuntimeTraceObservation => ({
  eventId,
  runId: 'run-fixture',
  stepId: 'step-model',
  eventType,
  observation: null,
  timestamp: `2026-09-23T10:00:${String(sequence).padStart(2, '0')}Z`,
  durationMs: null,
  status: typeof payload.status === 'string' ? payload.status : null,
  payload,
  source: 'trace',
  ...overrides
})

const runtimeObservation = {
  runId: 'run-fixture',
  traces: [
    trace('model-start', 'model.started', 1, { model: 'deepseek-chat' }),
    trace('model-first', 'model.first_token', 2, { ttftMs: 80 }),
    trace('model-delta-a', 'model.output.delta', 3, { delta: '{"answer":' }),
    trace('model-delta-b', 'model.output.delta', 4, { delta: '"ready"}' }),
    trace('model-done', 'model.completed', 5, { data: { answer: 'ready' }, status: 'completed', latencyMs: 430 }),
    trace('tool-read', 'tool_called', 6, { tool: 'read_file', path: 'README.md', status: 'succeeded' }, {
      stepId: 'step-tool',
      durationMs: 126
    }),
    trace('artifact-created', 'data_produced', 7, { artifactRef: 'artifact:report', fieldNames: ['summary'] }, {
      stepId: 'step-artifact',
      status: 'produced'
    }),
    trace('node-failed', 'node.failed', 8, { errorCode: 'MODEL_TIMEOUT', message: 'request timed out', status: 'failed' }, {
      stepId: 'step-failed',
      status: 'failed'
    }),
    trace('future-signal', 'runtime.future_signal', 9, { opaque: { retained: true } }, {
      stepId: 'step-future'
    })
  ],
  events: []
} as unknown as RuntimeObservation

describe('RuntimeEventsPanel semantic fixture', () => {
  it('renders a single aggregated model row plus tool, artifact, failure, and generic rows', async () => {
    const wrapper = mount(RuntimeEventsPanel, {
      props: { runtimeObservation },
      global: { stubs: { 'el-icon': { template: '<i><slot /></i>' } } }
    })

    const rows = wrapper.findAll('.runtime-event-row')
    expect(rows).toHaveLength(5)
    expect(wrapper.findAll('.runtime-event-row.is-model')).toHaveLength(1)
    expect(wrapper.findAll('.runtime-event-row.is-tool')).toHaveLength(1)
    expect(wrapper.findAll('.runtime-event-row.is-artifact')).toHaveLength(1)
    expect(wrapper.findAll('.runtime-event-row.is-error.is-failed')).toHaveLength(1)
    expect(wrapper.text()).toContain('runtime.future_signal')
    expect(wrapper.text()).toContain('2 个片段')
    expect(wrapper.text()).toContain('read_file')
    expect(wrapper.text()).toContain('126 ms')
    expect(wrapper.text()).toContain('MODEL_TIMEOUT')

    await wrapper.find('.runtime-event-row.is-model').trigger('click')
    expect(wrapper.emitted('select')).toEqual([[{ stepId: 'step-model', semanticTaskKey: null }]])
    wrapper.unmount()
  })
})
