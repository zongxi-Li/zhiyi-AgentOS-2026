import { describe, expect, it, vi } from 'vitest';
import { applyTranscript, restoreTranscript, createStreamBatcher, type TranscriptBlock } from '../src/shared/chat-stream/index.mjs';
import { StreamCapture } from '../src/chatCapture.js';

describe('shared chat projection', () => {
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
