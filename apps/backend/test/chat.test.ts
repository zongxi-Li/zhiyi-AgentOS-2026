import { describe, expect, it } from 'vitest';
import { StreamCapture, bootstrapHistory } from '../src/chat.js';
import { messageWire } from '../src/db.js';
import { recommendations } from '../src/platform.js';

describe('stream history capture', () => {
  it('retains byte units and validated latency stages separately from token usage', () => {
    const capture = new StreamCapture();
    capture.apply({event:'model_context',data:{requestBodyBytes:836280, contextMeasurement:'request-bytes', responseTimings:{contextPreparationMs:12,apiKey:'private'}}});
    capture.apply({event:'model_activity',data:{responseTimings:{providerHeadersMs:17000,providerFirstByteMs:17100}}});
    const wire = messageWire({metadata:capture.metadata()} as any);
    expect(wire.metadata).toMatchObject({requestBodyBytes:836280,responseTimings:{contextPreparationMs:12,providerHeadersMs:17000,providerFirstByteMs:17100}});
    expect(wire.metadata?.responseTimings).not.toHaveProperty('apiKey');
  });
  it('returns saved cache and context statistics through history without exposing private metadata', () => {
    const wire = messageWire({ metadata: { cached_tokens: 432000, cacheUsageAvailable: true,
      inputTokens: 486855, last_input_tokens: 116238, contextWindowTokens: 1048576,
      contextInputTokens: 472847, contextMeasurement: 'protocol-utf8-upper-bound', protocolSession: true,
      apiKey: 'must-not-leave-server' } } as any);
    expect(wire.metadata).toMatchObject({ cached_tokens: 432000, cacheUsageAvailable: true,
      last_input_tokens: 116238, contextWindowTokens: 1048576, protocolSession: true });
    expect(wire.metadata).not.toHaveProperty('apiKey');
  });
  it('bootstraps interrupted legacy text with confirmed effects without claiming full tool replay', () => {
    const result = bootstrapHistory([{ role: 'ASSISTANT', content: 'working', metadata: { executionSummary: [
      { stage: 'chat_stream', status: 'cancelled' },
      { stage: 'tool:write_file:c1', status: 'completed', description: 'file created' },
    ] } } as any]);
    expect(result[0].content).toContain('历史回复已中断');
    expect(result[0].content).toContain('file created');
    expect(result[0].content).toContain('非原始工具协议消息');
    expect(bootstrapHistory([{ role: 'ASSISTANT', content: '', metadata: { executionSummary: [
      { stage: 'tool:write_file:c1', status: 'completed', description: 'confirmed write without reply' },
    ] } } as any])[0].content).toContain('confirmed write without reply');
  });
  it('retains capacity and protocol context on interruption, and cache usage on success', () => {
    const capture = new StreamCapture();
    const add = (event: string, data: unknown) => capture.acceptText(`data: ${JSON.stringify({ event, data })}\n\n`);
    add('model_context', { contextInputTokens: 4096, contextMeasurement: 'protocol-utf8-upper-bound', contextWindowTokens: 1048576 });
    add('error', { message: 'interrupted' });
    expect(capture.metadata()).toMatchObject({ contextInputTokens: 4096, contextWindowTokens: 1048576 });
    const complete = new StreamCapture();
    complete.acceptText(`data: ${JSON.stringify({ event: 'usage', data: { cached_tokens: 2048, cacheUsageAvailable: true, last_input_tokens: 3000, contextWindowTokens: 1048576, protocolSession: true } })}\n\n`);
    expect(complete.metadata()).toMatchObject({ cached_tokens: 2048, last_input_tokens: 3000, protocolSession: true });
  });
  it('handles UTF-8 and SSE frame boundaries without losing reasoning or output', () => {
    const stream = [
      { event: 'reasoning_start', data: { requestedThinkingMode: 'deep' } },
      { event: 'reasoning_delta', data: { delta: '推理😀' } },
      { event: 'reasoning_end', data: { reasoningPhaseMs: 17 } },
      { event: 'content_delta', data: { delta: '答案中文' } },
      { event: 'usage', data: { input_tokens: 11, reasoning_tokens: 3, output_tokens: 5, total_tokens: 19,
        contextFixedTokens: 100, contextTokenMethod: 'utf8-upper-bound' } },
      { event: 'done', data: { status: 'completed' } },
    ].map((value, index) => `event: ${value.event}\r\ndata: ${JSON.stringify({ requestId: 'request-a', sequence: index + 1, ...value })}\r\n\r\n`).join('');
    const bytes = new TextEncoder().encode(stream); const capture = new StreamCapture();
    for (let offset = 0; offset < bytes.length; offset += 7) capture.accept(bytes.slice(offset, offset + 7));
    capture.finish();
    expect(capture.content).toBe('答案中文'); expect(capture.completed).toBe(true);
    expect(capture.metadata()).toMatchObject({ reasoningContent: '推理😀', reasoningPhaseMs: 17, totalTokens: 19, reasoningTokens: 3,
      contextFixedTokens: 100, contextTokenMethod: 'utf8-upper-bound',
      executionSummary: [{ stage: 'chat_stream', status: 'completed' }, { stage: 'reasoning', status: 'completed' }, { stage: 'answer_generation', status: 'completed' }] });
  });
  it('persists partial cancelled output and bounded reasoning', () => {
    const capture = new StreamCapture();
    capture.accept(new TextEncoder().encode(`data: ${JSON.stringify({ event: 'reasoning_delta', data: { delta: 'x'.repeat(200010) } })}\n\n`));
    capture.accept(new TextEncoder().encode('data: {"event":"content_delta","data":{"delta":"partial"}}\n\n'));
    capture.cancel();
    const metadata = capture.metadata();
    expect(capture.content).toBe('partial'); expect(capture.cancelled).toBe(true);
    expect(String(metadata.reasoningContent)).toHaveLength(200000); expect(metadata.reasoningTruncated).toBe(true);
    expect((metadata.executionSummary as any[])[0]).toMatchObject({ stage: 'chat_stream', status: 'cancelled' });
  });
  it('keeps terminal and file activity for a history reload and ignores malformed frames', () => {
    const capture = new StreamCapture();
    capture.accept(new TextEncoder().encode('data: invalid\n\n'));
    const tool = { callId: 'call-1', toolName: 'run_command', status: 'completed', terminal: { command: 'node --version', stdout: 'v24' }, activity: { kind: 'command', summary: 'check node' } };
    capture.accept(new TextEncoder().encode(`data: ${JSON.stringify({ event: 'tool_result', data: tool })}\n\n`));
    capture.accept(new TextEncoder().encode(`data: ${JSON.stringify({ event: 'done', data: { status: 'completed', toolExecutions: [tool] } })}\n\n`));
    const summary = capture.metadata().executionSummary as any[];
    expect(summary.filter(item => item.stage.startsWith('tool:'))).toHaveLength(1);
    expect(summary[1].terminal).toMatchObject({ command: 'node --version', stdout: 'v24' });
  });
});
it('uses scene and question context for the existing lightweight recommendation rules', () => {
  const items = recommendations({ currentInput: '如何处理合同验收？', scene: 'clause', scope: 'rag' });
  expect(items.map(item => item.text)).toContain('具体步骤是什么？');
  expect(items.map(item => item.text)).toContain('补充阶段验收的判定标准');
  expect(items.every(item => item.targetAction === 'fill_query')).toBe(true);
});
