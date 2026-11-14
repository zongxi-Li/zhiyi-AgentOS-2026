/** Connection-independent ownership of the existing Python stream, not another agent loop. */
import { EventEmitter, once } from 'node:events';
import { createStreamBatcher, type StreamEvent } from './shared/chat-stream/index.mjs';
import { StreamCapture } from './chatCapture.js';
import { one, messageWire, HttpError, type Database, type MessageRow } from './db.js';
import type { PreparedChat, ChatConfig } from './chat.js';
import type { LocalIdentity } from './identity.js';
import type { PythonGateway } from './gateway.js';

interface ExecutionRow extends MessageRow { context_id: string }
interface Active {
  prepared: PreparedChat; capture: StreamCapture; controller: AbortController; emitter: EventEmitter;
  sequence: number; frames: Array<{ seq: number; text: string }>; frameBytes: number;
  done: boolean; phase: string; task: Promise<void>; lastPersist: number;
}
const frame = (event: StreamEvent) => `id: ${event.sequence ?? 0}\nevent: ${event.event}\ndata: ${JSON.stringify(event)}\n\n`;

export class ChatExecutions {
  private readonly active = new Map<string, Active>();
  constructor(private readonly db: Database, private readonly gateway: PythonGateway, private readonly config: ChatConfig,
    private readonly beginActivity: () => () => void = () => () => undefined) {}

  async recoverInterrupted() {
    // The local service has a single lifecycle owner. A process restart cannot prove tool outcomes.
    await this.db.query(`UPDATE messages SET metadata=metadata||$1::jsonb||jsonb_build_object(
      'executionSummary', $2::jsonb || COALESCE((SELECT jsonb_agg(CASE WHEN item->>'status' IN ('running','approval_required')
        THEN item||'{"status":"interrupted"}'::jsonb||CASE WHEN item->'approval'->>'status'='pending'
          THEN jsonb_build_object('approval',(item->'approval')||'{"status":"expired"}'::jsonb) ELSE '{}'::jsonb END
        ELSE item END) FROM jsonb_array_elements(
        COALESCE(metadata->'executionSummary','[]'::jsonb)) item WHERE item->>'stage'<>'chat_stream'),'[]'::jsonb),
      'transcript', COALESCE((SELECT jsonb_agg(CASE WHEN item->>'state' IN ('streaming','running','approval_required')
        THEN item||'{"state":"interrupted"}'::jsonb ELSE item END) FROM jsonb_array_elements(
        COALESCE(metadata->'transcript','[]'::jsonb)) item),'[]'::jsonb))
      WHERE metadata->>'chatExecutionState'='running'`, [JSON.stringify({
        chatExecutionState: 'interrupted', streamPhase: '服务已重启，执行已中断',
      }), JSON.stringify([{ stage: 'chat_stream', status: 'failed',
        description: '服务已重启，执行结果尚未确认；请检查已有操作后再继续' }])]);
  }

  owned(id: string, actorId: string): Promise<ExecutionRow> {
    return one<ExecutionRow>(this.db, `SELECT m.*,c.context_id FROM messages m JOIN conversations c ON c.id=m.conversation_id
      WHERE c.user_id=$1 AND m.metadata->>'chatExecutionId'=$2`, [actorId, id]);
  }

  start(prepared: PreparedChat, identity: Readonly<LocalIdentity>) {
    const id = prepared.chatExecutionId!;
    if (prepared.resumed || this.active.has(id)) return;
    const active: Active = { prepared, capture: new StreamCapture(), controller: new AbortController(),
      emitter: new EventEmitter(), sequence: 0, frames: [], frameBytes: 0, done: false,
      phase: '等待模型响应', task: Promise.resolve(), lastPersist: Date.now() };
    active.emitter.setMaxListeners(0);
    this.active.set(id, active);
    const release = this.beginActivity();
    active.task = this.run(active, identity).finally(() => {
      release();
      active.done = true;
      active.emitter.emit('change');
      // Finished executions remain resumable from PostgreSQL after this bounded live buffer expires.
      const timer = setTimeout(() => this.active.delete(id), 60_000); timer.unref();
    });
  }

  private emit(active: Active, event: StreamEvent) {
    const encoded = frame({ ...event, sequence: ++active.sequence,
      data: { ...event.data, chatExecutionId: active.prepared.chatExecutionId } });
    active.frames.push({ seq: active.sequence, text: encoded });
    active.frameBytes += encoded.length;
    while (active.frames.length > 1024 || active.frameBytes > 2 * 1024 * 1024) {
      active.frameBytes -= active.frames.shift()!.text.length;
    }
    active.emitter.emit('change');
  }

  private metadata(active: Active, finished = active.done) {
    const metadata = active.capture.metadata(active.prepared.body.model);
    const state = finished ? active.capture.completed ? 'completed' : active.capture.cancelled ? 'cancelled' : 'failed' : 'running';
    if (!finished) metadata.executionSummary = [
      { stage: 'chat_stream', status: 'running', description: active.phase },
      ...(metadata.executionSummary as any[]).filter(item => item.stage !== 'chat_stream'),
    ];
    return { ...metadata, responseTimings: {...metadata.responseTimings as object, gatewayPrepareMs: active.prepared.gatewayPrepareMs},
      chatExecutionId: active.prepared.chatExecutionId, chatExecutionState: state,
      chatExecutionCursor: active.sequence + (finished && !active.done ? 1 : 0), streamPhase: active.phase };
  }

  private async persist(active: Active, finished = false) {
    const result = await this.db.query(`UPDATE messages SET content=$3,metadata=metadata||$4::jsonb
      WHERE id=$1 AND conversation_id IN (SELECT id FROM conversations WHERE user_id=$2)`,
    [active.prepared.assistantId, active.prepared.actorId, active.capture.content, JSON.stringify(this.metadata(active, finished))]);
    if (!result.rowCount) throw new HttpError(404, 'CHAT_EXECUTION_REMOVED');
    active.lastPersist = Date.now();
  }

  private async run(active: Active, identity: Readonly<LocalIdentity>) {
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    let terminal: StreamEvent | undefined;
    let idleTimer: ReturnType<typeof setTimeout> | undefined;
    let totalTimer: ReturnType<typeof setTimeout> | undefined;
    let save: Promise<void> = Promise.resolve();
    const touch = () => {
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => active.controller.abort(new Error('SSE_IDLE_TIMEOUT')), this.config.streamIdleTimeoutMs ?? 240000);
      idleTimer.unref();
    };
    const batcher = createStreamBatcher((event: StreamEvent) => {
      event = active.capture.apply(event);
      if (event.event === 'model_phase') active.phase = event.data.phase === 'tool_arguments' ? '正在准备工具调用'
        : event.data.turn > 1 ? '操作已完成，等待模型处理结果' : '等待模型响应';
      if (event.event === 'reasoning_delta') active.phase = '正在思考';
      if (event.event === 'content_delta') active.phase = '正在生成回复';
      if (event.event === 'tool_start' || event.event === 'execution_started') active.phase = '正在执行工具';
      if (event.event === 'approval_required') active.phase = '等待你的确认';
      if (event.event === 'stdout_delta' || event.event === 'stderr_delta') active.phase = '读取命令输出';
      if (['done', 'error'].includes(event.event)) terminal = event;
      else {
        this.emit(active, event);
        if (Date.now() - active.lastPersist >= 250) {
          active.lastPersist = Date.now();
          save = save.then(() => this.persist(active)).catch(() => active.controller.abort(new Error('CHAT_PERSIST_FAILED')));
        }
      }
    });
    const decoder = new StreamCapture(event => batcher.accept(event));
    try {
      touch();
      const maximum = this.config.streamMaxDurationMs || 1800000;
      totalTimer = setTimeout(() => active.controller.abort(new Error('SSE_MAX_DURATION')), maximum); totalTimer.unref();
      const response = await this.gateway.request('/ai/chat/text/stream', { identity, method: 'POST', body: active.prepared.body,
        headers: { Accept: 'text/event-stream' }, signal: active.controller.signal });
      if (!response.ok || !response.body || !response.headers.get('content-type')?.includes('text/event-stream')) {
        throw new Error('AI_INVALID_STREAM');
      }
      reader = response.body.getReader();
      while (true) {
        const next = await reader.read();
        if (next.done) break;
        touch(); decoder.accept(next.value);
      }
      decoder.finish(); batcher.flush();
      if (!terminal) throw new Error('AI_STREAM_INTERRUPTED');
      if (active.capture.completed && !active.capture.content) throw new Error('AI_EMPTY_RESPONSE');
    } catch (error) {
      batcher.flush();
      active.capture.completed = false;
      const cancelled = active.controller.signal.reason?.message === 'USER_CANCELLED';
      active.capture.cancelled = cancelled;
      active.capture.failure = cancelled ? '已停止生成' : '回复连接中断，已保留当前进展，请检查后继续';
      terminal = { event: 'error', data: { code: cancelled ? 'CHAT_CANCELLED' : 'AI_STREAM_INTERRUPTED',
        message: active.capture.failure, retryable: false } };
      active.capture.apply(terminal);
    } finally {
      clearTimeout(idleTimer); clearTimeout(totalTimer); batcher.dispose();
      await reader?.cancel().catch(() => undefined);
      await save;
      try {
        await this.persist(active, true);
        active.done = true;
        this.emit(active, terminal || { event: 'error', data: { code: 'AI_STREAM_INTERRUPTED' } });
      } catch {
        active.done = true;
        active.capture.completed = false;
        active.capture.failure = '进展保存失败，请检查本机数据库';
        this.emit(active, { event: 'error', data: { code: 'CHAT_PERSIST_FAILED', message: '进展保存失败，请检查本机数据库', retryable: false } });
      }
    }
  }

  async *follow(id: string, row: ExecutionRow, after: number, signal: AbortSignal): AsyncGenerator<string> {
    const active = this.active.get(id);
    const snapshot = () => {
      const message = active ? messageWire({ ...row, content: active.capture.content, metadata: this.metadata(active) }) : messageWire(row);
      return frame({ event: 'snapshot', sequence: active?.sequence ?? Number(row.metadata?.chatExecutionCursor || 0),
        data: { message, contextId: row.context_id, chatExecutionId: id } });
    };
    // Rebaseline is atomic; a reconnect never combines a stale snapshot and newer deltas.
    let cursor = active?.sequence ?? Number(row.metadata?.chatExecutionCursor || 0);
    const initiallyDone = !active || active.done;
    yield snapshot();
    void after; // Snapshots are compact persisted projections; the live ring covers subsequent delivery gaps.
    if (initiallyDone) {
      const state = active ? this.metadata(active).chatExecutionState : row.metadata?.chatExecutionState;
      yield frame({ event: state === 'completed' ? 'done' : 'error', sequence: cursor,
        data: state === 'completed' ? { status: state } : { status: state,
          message: state === 'cancelled' ? '已停止生成' : '执行已中断，请检查已有操作后继续', code: 'CHAT_EXECUTION_ENDED' } });
      return;
    }
    while (!signal.aborted) {
      const frames = active.frames.filter(item => item.seq > cursor);
      if (frames.length && frames[0].seq !== cursor + 1) {
        cursor = active.sequence;
        yield snapshot();
        if (active.done) {
          yield frame({ event: active.capture.completed ? 'done' : 'error', sequence: cursor,
            data: {status: this.metadata(active).chatExecutionState, message: active.capture.failure || undefined} });
          return;
        }
        continue;
      }
      for (const item of frames) { cursor = item.seq; yield item.text; }
      if (active.done && cursor >= active.sequence) return;
      if (frames.length) continue;
      // Register only when waiting. A subscriber can leave at any yielded frame
      // without stranding an EventEmitter listener on the running execution.
      const waiter = new AbortController();
      const abortWait = () => waiter.abort();
      signal.addEventListener('abort', abortWait, { once: true });
      const wait = once(active.emitter, 'change', { signal: waiter.signal }).catch(() => undefined);
      let timer: ReturnType<typeof setTimeout> | undefined;
      try {
        if (signal.aborted) return;
        await Promise.race([wait, new Promise<void>(resolve => { timer = setTimeout(resolve, 10000); })]);
      } finally {
        clearTimeout(timer); waiter.abort(); signal.removeEventListener('abort', abortWait);
      }
      if (active.sequence === cursor && !signal.aborted) yield ': heartbeat\n\n';
    }
  }

  async cancel(id: string) {
    const active = this.active.get(id);
    if (!active || active.done) return false;
    active.controller.abort(new Error('USER_CANCELLED'));
    await active.task;
    return true;
  }

  async close() {
    const entries = [...this.active.values()];
    for (const entry of entries) if (!entry.done) entry.controller.abort(new Error('SERVICE_STOPPING'));
    await Promise.allSettled(entries.map(entry => entry.task));
  }
}
