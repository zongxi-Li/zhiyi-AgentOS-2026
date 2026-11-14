import { describe, expect, it, vi } from 'vitest';
import { applyTranscript, restoreTranscript, createStreamBatcher, type TranscriptBlock } from '../src/shared/chat-stream/index.mjs';
import { StreamCapture } from '../src/chatCapture.js';

describe('shared chat projection', () => {
  it('preserves the authoritative watermark through failure and a newer compact boundary', () => {
    const capture = new StreamCapture();
    capture.apply({event:'model_context',data:{contextUsage:{usedTokens:205000,maxTokens:1000000,measurement:'provider',source:'model'}}});
    capture.apply({event:'error',data:{message:'failed'}});
    expect(capture.metadata().contextUsage).toMatchObject({usedTokens:205000,source:'model'});
    capture.apply({event:'model_phase',data:{phase:'context_committed',contextUsage:{usedTokens:40000,maxTokens:1000000,
      measurement:'upper-bound',source:'compaction',projectionVersion:2}}});
    expect(capture.metadata().contextUsage).toMatchObject({usedTokens:40000,projectionVersion:2});
  });
  it('persists the last individual model usage before done and preserves it across request byte events', () => {
    const capture = new StreamCapture();
    capture.apply({event:'model_context',data:{contextMeasurement:'provider-usage',contextInputTokens:200000,
      last_input_tokens:200000,last_output_tokens:1000,contextWindowTokens:1000000}});
    capture.apply({event:'model_context',data:{contextMeasurement:'request-bytes',requestBodyBytes:850000}});
    expect(capture.metadata()).toMatchObject({contextMeasurement:'provider-usage',contextInputTokens:200000,
      last_input_tokens:200000,last_output_tokens:1000,requestBodyBytes:850000});
    capture.apply({event:'model_context',data:{contextMeasurement:'provider-usage',contextInputTokens:40000,
      last_input_tokens:40000,last_output_tokens:100}});
    expect(capture.metadata()).toMatchObject({contextInputTokens:40000,last_input_tokens:40000,last_output_tokens:100});
    expect(capture.metadata().totalTokens).toBeUndefined();
  });
  it('publishes the same bounded reasoning delta that is retained in history', () => {
    const capture = new StreamCapture();
    const forwarded = capture.apply({event:'reasoning_delta', data:{delta:'x'.repeat(200005)}});
    expect(forwarded.data.delta).toHaveLength(200000);
    expect(forwarded.data.truncated).toBe(true);
    expect(capture.metadata().reasoningContent).toBe(forwarded.data.delta);
    expect(capture.transcript[0].text).toBe(forwarded.data.delta);
  });
  it('expires uncompleted approval controls after a confirmed terminal failure', () => {
    const capture = new StreamCapture();
    capture.apply({event:'approval_required', data:{callId:'once', toolName:'write_file', approval:{status:'pending'}}});
    capture.apply({event:'error', data:{message:'cancelled'}});
    const metadata = capture.metadata();
    expect((metadata.executionSummary as any[]).find(item=>item.stage==='tool:write_file:once'))
      .toMatchObject({status:'interrupted',approval:{status:'expired'}});
  });
  it('preserves text/tool/text boundaries and updates a tool in place', () => {
    const blocks: TranscriptBlock[] = [];
    for (const event of [
      { event: 'content_delta', data: { delta: 'inspect' } },
      { event: 'tool_start', data: { callId: 'one', toolName: 'read_file' } },
      { event: 'tool_result', data: { callId: 'one', toolName: 'read_file' } },
      { event: 'content_delta', data: { delta: 'verified' } },
      { event: 'done', data: { status: 'completed' } },
    ]) applyTranscript(blocks, event);
    expect(blocks.map(b => [b.kind, b.text || b.callId, b.state])).toEqual([
      ['text', 'inspect', 'completed'], ['tool', 'one', 'completed'], ['text', 'verified', 'completed'],
    ]);
    expect(restoreTranscript(JSON.parse(JSON.stringify(blocks)))).toEqual(blocks);
  });

  it('flushes text before approvals and terminal events without waiting for a visible browser frame', () => {
    vi.useFakeTimers();
    try {
      const events: any[] = [];
      const batcher = createStreamBatcher((e: any) => events.push(e));
      batcher.accept({ event: 'content_delta', data: { delta: 'a' } });
      batcher.accept({ event: 'content_delta', data: { delta: 'b' } });
      expect(events).toHaveLength(0);
      batcher.accept({ event: 'approval_required', data: { callId: 'one' } });
      expect(events.map(e => [e.event, e.data.delta])).toEqual([['content_delta', 'ab'], ['approval_required', undefined]]);
      batcher.accept({ event: 'content_delta', data: { delta: 'c' } });
      vi.advanceTimersByTime(16);
      expect(events.at(-1).data.delta).toBe('c');
      batcher.dispose();
    } finally { vi.useRealTimers(); }
  });

  it('keeps background acceptance distinct from completion and retains failed attempt boundaries', () => {
    const blocks: TranscriptBlock[] = [];
    applyTranscript(blocks, {event: 'content_delta', data: {partId: 'old', delta: 'partial'}});
    applyTranscript(blocks, {event: 'model_phase', data: {phase: 'retrying'}});
    applyTranscript(blocks, {event: 'content_delta', data: {partId: 'new', delta: 'recovered'}});
    applyTranscript(blocks, {event: 'tool_start', data: {callId: 'job'}});
    applyTranscript(blocks, {event: 'tool_result', data: {callId: 'job', activity: {status: 'running'}}});
    expect(blocks.map(block => block.state)).toEqual(['interrupted', 'completed', 'completed', 'background']);
    applyTranscript(blocks, {event: 'execution_completed', data: {callId: 'job'}});
    applyTranscript(blocks, {event: 'tool_result', data: {callId: 'job', activity: {status: 'running'}}});
    expect(blocks.at(-1)?.state).toBe('completed');
  });
});
