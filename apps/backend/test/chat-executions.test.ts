import { describe, expect, it, vi } from 'vitest';
import { ChatExecutions } from '../src/chatExecutions.js';
import type { Database } from '../src/db.js';
import type { PythonGateway } from '../src/gateway.js';

const wire = (event: string, data: object) => new TextEncoder().encode(`data: ${JSON.stringify({event, data})}\n\n`);
const decode = (text: string) => JSON.parse(text.split('data: ')[1]);
function fixture() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  let upstream!: AbortSignal;
  const stream = new ReadableStream<Uint8Array>({ start(c) { controller = c; } });
  const gateway = { request: vi.fn(async (_path: string, options: any) => {
    upstream = options.signal;
    upstream.addEventListener('abort', () => controller.error(upstream.reason), {once: true});
    return new Response(stream, { headers: {'content-type': 'text/event-stream'} });
  }) };
  const writes: any[] = [];
  const query = vi.fn(async (_sql: string, params: any[]) => { writes.push(params); return {rowCount: 1, rows: []}; });
  const executions = new ChatExecutions({query} as unknown as Database, gateway as unknown as PythonGateway, {});
  const prepared = {conversationId: 'conversation', contextId: 'context', actorId: 'actor',
    assistantId: 'assistant', chatExecutionId: 'execution', body: {model: 'offline'}};
  const row = {id: 'assistant', conversation_id: 'conversation', context_id: 'context', role: 'ASSISTANT',
    content: '', metadata: {}, message_type: 'TEXT', file_url: null, created_at: new Date().toISOString()} as any;
  executions.start(prepared, {actorId: 'actor', tenantId: null});
  return { executions, gateway, query, writes, row, upstream: () => upstream,
    send: (event: string, data: object) => controller.enqueue(wire(event, data)), end: () => controller.close() };
}

describe('connection independent chat executions', () => {
  it('does not skip deltas arriving while the snapshot is delivered, or cancel on unsubscribe', async () => {
    const f = fixture();
    try {
      const signal = new AbortController();
      const subscriber = f.executions.follow('execution', f.row, 0, signal.signal);
      expect(decode((await subscriber.next()).value!).event).toBe('snapshot');
      f.send('content_delta', {delta: 'between snapshot and next read'});
      f.send('tool_start', {callId: 'one', toolName: 'read_file'});
      expect(decode((await subscriber.next()).value!).data.delta).toBe('between snapshot and next read');
      signal.abort(); await subscriber.return(undefined);
      expect(f.upstream().aborted).toBe(false);
      f.send('content_delta', {delta: ' continued'}); f.send('done', {status: 'completed'}); f.end();
      await vi.waitFor(() => expect(f.writes.at(-1)?.[3]).toContain('"chatExecutionState":"completed"'));
      const reconnect = f.executions.follow('execution', f.row, 999, new AbortController().signal);
      const snapshot = decode((await reconnect.next()).value!);
      expect(snapshot.data.message.content).toBe('between snapshot and next read continued');
      expect(snapshot.data.message.metadata.transcript.map((b: any) => b.kind)).toEqual(['text','tool','text']);
      expect(decode((await reconnect.next()).value!).event).toBe('done');
      expect(f.gateway.request).toHaveBeenCalledTimes(1);
    } finally { await f.executions.close(); }
  });

  it('saves the terminal result before delivering done', async () => {
    const f = fixture();
    let release!: () => void;
    const gate = new Promise<void>(resolve => {release = resolve;});
    f.query.mockImplementation(async (_sql, params) => { f.writes.push(params); await gate; return {rowCount: 1, rows: []}; });
    try {
      const subscriber = f.executions.follow('execution', f.row, 0, new AbortController().signal);
      await subscriber.next();
      f.send('content_delta', {delta: 'saved'}); f.send('done', {status: 'completed'}); f.end();
      expect(decode((await subscriber.next()).value!).event).toBe('content_delta');
      let terminalDelivered = false;
      const terminal = subscriber.next().then(result => {terminalDelivered = true; return result;});
      await new Promise(resolve => setTimeout(resolve, 5)); expect(terminalDelivered).toBe(false);
      release(); expect(decode((await terminal).value!).event).toBe('done');
      expect(JSON.parse(f.writes.at(-1)[3]).chatExecutionCursor).toBe(2);
      await subscriber.return(undefined);
    } finally {release(); await f.executions.close();}
  });

  it('explicit cancellation aborts the owned upstream and preserves partial progress', async () => {
    const f = fixture();
    try {
      f.send('content_delta', {delta: 'partial'});
      await vi.waitFor(() => expect(f.upstream()).toBeDefined());
      expect(await f.executions.cancel('execution')).toBe(true);
      expect(f.upstream().aborted).toBe(true);
      expect(JSON.parse(f.writes.at(-1)[3]).chatExecutionState).toBe('cancelled');
      expect(f.writes.at(-1)[2]).toBe('partial');
      expect(await f.executions.cancel('execution')).toBe(false);
    } finally {await f.executions.close();}
  });

  it('repairs a slow subscriber gap with a complete snapshot and a terminal event', async () => {
    const f = fixture();
    try {
      const subscriber = f.executions.follow('execution', f.row, 0, new AbortController().signal);
      await subscriber.next();
      for (let index = 0; index < 1100; index++) f.send('model_activity', {});
      f.send('content_delta', {delta: 'all progress'}); f.send('done', {status: 'completed'}); f.end();
      await vi.waitFor(() => expect(f.writes.at(-1)?.[3]).toContain('"chatExecutionState":"completed"'));
      const snapshot = decode((await subscriber.next()).value!);
      expect(snapshot.event).toBe('snapshot');
      expect(snapshot.data.message.content).toBe('all progress');
      expect(decode((await subscriber.next()).value!).event).toBe('done');
      expect((await subscriber.next()).done).toBe(true);
    } finally {await f.executions.close();}
  });
});
