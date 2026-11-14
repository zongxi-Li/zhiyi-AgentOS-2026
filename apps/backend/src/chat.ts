import { randomUUID, createHash } from 'node:crypto';
import { once } from 'node:events';
import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import { type Database, type MessageRow, type ConversationRow, type Connection, transaction, one,
  ownedConversation, saveMessage, messageWire, objectValue, textValue, uuidValue, workspaceMode, HttpError, invalid } from './db.js';
import { actor } from './platform.js';
import { clearChatSession } from './chatSession.js';
import { GatewayError, type PythonGateway } from './gateway.js';
import { StreamCapture } from './chatCapture.js';
export { StreamCapture } from './chatCapture.js';
import { ChatExecutions } from './chatExecutions.js';

export interface PreparedChat {
  conversationId: string; contextId: string; actorId: string; body: Record<string, unknown>;
  assistantId?: string; chatExecutionId?: string; resumed?: boolean;
  gatewayPrepareMs?: number;
}
export interface ChatConfig { streamIdleTimeoutMs?: number; streamMaxDurationMs?: number }

export async function prepareChat(db: Database, actorId: string, input: unknown, persistent = false): Promise<PreparedChat> {
  const data = objectValue(input);
  const text = textValue(data.text ?? data.message, 1000000, true)!;
  const contextId = textValue(data.context_id ?? data.contextId, 100);
  const mode = workspaceMode(data.workspace_mode ?? data.workspaceMode);
  const roleId = uuidValue(data.role_id ?? data.roleId, true);
  const fileUrl = textValue(data.file_url ?? data.fileUrl, 255);
  const body: Record<string, unknown> = { text };
  const clientRequestId = persistent ? uuidValue(data.clientRequestId) : null;
  const fingerprint = createHash('sha256').update(JSON.stringify(data)).digest('hex');
  for (const [snake, camel] of [['model', 'model'], ['base_url', 'baseUrl'], ['api_key', 'apiKey'],
    ['thinking_mode', 'thinkingMode'], ['reasoning_effort', 'reasoningEffort'], ['tool_mode', 'toolMode'], ['approval_mode', 'approvalMode']]) {
    const value = data[snake] ?? data[camel];
    if (value !== undefined && value !== null) body[snake] = textValue(value, 20000);
  }
  if (roleId) body.role_id = roleId;
  if (data.context !== undefined && data.context !== null) {
    body.context_projection = true;
    if (!Array.isArray(data.context) || data.context.length > 10000) invalid('对话上下文格式无效');
    body.context = data.context.map(value => {
      const item = objectValue(value);
      if (!['user', 'assistant', 'system'].includes(String(item.role))) invalid('上下文角色无效');
      return { role: item.role, content: textValue(item.content, 1000000) ?? '',
        ...(typeof item.file_url === 'string' ? { file_url: textValue(item.file_url, 255) } : {}) };
    });
  }
  return transaction(db, async client => {
    if (persistent) {
      // 同一命令重连只返回已有执行，不重复插入用户消息，也不重跑工具。
      await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', [`${actorId}:chat:${clientRequestId}`]);
      const existing = (await client.query<MessageRow & { context_id: string }>(`SELECT m.*,c.context_id FROM messages m
        JOIN conversations c ON c.id=m.conversation_id WHERE c.user_id=$1 AND m.metadata->>'clientRequestId'=$2`, [actorId, clientRequestId])).rows[0];
      if (existing) {
        if (existing.metadata?.clientRequestFingerprint !== fingerprint) throw new HttpError(409, 'CHAT_COMMAND_CONFLICT');
        return { conversationId: existing.conversation_id, contextId: existing.context_id, actorId, body: {},
          assistantId: existing.id, chatExecutionId: String(existing.metadata?.chatExecutionId), resumed: true };
      }
    }
    if (roleId) await one(client, "SELECT id FROM roles WHERE id=$1 AND (user_id=$2 OR role_type='BUILTIN')", [roleId, actorId]);
    // Existing context IDs are authority-bearing references, never hints to
    // silently fall back to a newly-created conversation owned by this caller.
    let conversation: ConversationRow;
    if (contextId) {
      conversation = await ownedConversation(client, contextId, actorId, true);
      if (conversation.workspace_mode !== mode) throw new HttpError(409, 'WORKSPACE_MODE_MISMATCH');
    } else {
      conversation = await one<ConversationRow>(client, `INSERT INTO conversations(user_id,role_id,context_id,title,workspace_mode)
        VALUES($1,$2,$3,$4,$5) RETURNING *`, [actorId, roleId, 'ctx_' + randomUUID(), text.length > 50 ? text.slice(0, 50) + '...' : text, mode]);
    }
    if (body.context === undefined) {
      const history = await client.query<MessageRow>(`SELECT role,content,file_url,
        jsonb_build_object('executionSummary',metadata->'executionSummary') AS metadata
        FROM messages WHERE conversation_id=$1 ORDER BY created_at,id`, [conversation.id]);
      body.context = bootstrapHistory(history.rows);
    }
    if (persistent && (await client.query(`SELECT id FROM messages WHERE conversation_id=$1
      AND metadata->>'chatExecutionState'='running' LIMIT 1`, [conversation.id])).rowCount) {
      throw new HttpError(409, 'CHAT_SESSION_BUSY', '这个对话仍在回复，请先停止生成再继续');
    }
    const userMessage = await saveMessage(client, conversation.id, actorId, 'USER', text, null, fileUrl);
    body.context_id = conversation.context_id;
    if (!persistent) return { conversationId: conversation.id, contextId: conversation.context_id, actorId, body };
    const chatExecutionId = randomUUID();
    const assistant = await saveMessage(client, conversation.id, actorId, 'ASSISTANT', '', {
      chatExecutionId, chatExecutionState: 'running', chatExecutionCursor: 0, clientRequestId,
      clientRequestFingerprint: fingerprint, transcript: [],
      executionSummary: [{ stage: 'chat_stream', status: 'running', description: '等待模型响应' }],
    });
    // PostgreSQL now() is constant within this transaction; UUID order is not turn order.
    await client.query(`UPDATE messages SET created_at=GREATEST(clock_timestamp(),
      (SELECT created_at FROM messages WHERE id=$2)+interval '1 microsecond') WHERE id=$1`, [assistant.id, userMessage.id]);
    return { conversationId: conversation.id, contextId: conversation.context_id, actorId, body,
      assistantId: assistant.id, chatExecutionId };
  });
}
function unfinished(message: MessageRow) {
  const summary = message.metadata?.executionSummary;
  return message.role === 'ASSISTANT' && Array.isArray(summary) && summary.some(item =>
    item && typeof item === 'object' && item.stage === 'chat_stream' && item.status !== 'completed');
}

export function bootstrapHistory(messages: MessageRow[]) {
  return messages.flatMap(item => {
    const recorded = Array.isArray(item.metadata?.executionSummary) ? item.metadata.executionSummary : [];
    const tools = recorded.filter((row: any) => row?.status === 'completed' && String(row.stage).startsWith('tool:'))
      .map((row: any) => ({ stage: row.stage, status: row.status, description: row.description, activity: row.activity }));
    if (!item.content.trim() && !tools.length) return [];
    const content = (unfinished(item) ? '[历史回复已中断，以下文字不代表任务完成]\n' : '') + item.content
      + (tools.length ? '\n[迁移时可确认的工具摘要，非原始工具协议消息]\n' + JSON.stringify(tools) : '');
    return [{ role: item.role.toLowerCase(), content, ...(item.file_url ? { file_url: item.file_url } : {}) }];
  });
}


function abortForReply(reply: FastifyReply) {
  const controller = new AbortController();
  const onClose = () => { if (!reply.raw.writableEnded) controller.abort(new Error('CLIENT_DISCONNECTED')); };
  reply.raw.once('close', onClose);
  return { controller, dispose: () => reply.raw.off('close', onClose) };
}
async function forwardError(response: Response, reply: FastifyReply) {
  const type = response.headers.get('content-type');
  if (type) reply.header('content-type', type);
  return reply.code(response.status).send(Buffer.from(await response.arrayBuffer()));
}
async function persistCapture(db: Database, prepared: PreparedChat, capture: StreamCapture) {
  if (capture.completed && !capture.content) { capture.completed = false; capture.failure = 'AI 返回了空响应，请重试'; }
  await transaction(db, async client => {
    await ownedConversation(client, prepared.conversationId, prepared.actorId, true);
    await saveMessage(client, prepared.conversationId, prepared.actorId, 'ASSISTANT',
      capture.content || capture.failure || '回复连接中断，请重试', capture.metadata(prepared.body.model));
  });
}

export async function registerChat(app: FastifyInstance, db: Database, gateway: PythonGateway, config: ChatConfig = {}) {
  const executions = new ChatExecutions(db, gateway, config, () => app.beginActivity?.() ?? (() => undefined));
  // Liveness must remain available without a database. Recover before the first
  // persistent operation, sharing the same barrier across concurrent requests.
  let recovery: Promise<unknown> | undefined;
  const ready = async () => {
    try { await (recovery ??= executions.recoverInterrupted()); }
    catch { recovery = undefined; throw new HttpError(503, 'CHAT_RECOVERY_UNAVAILABLE'); }
  };
  app.addHook('preClose', async () => executions.close());
  app.post('/api/chat/executions', async request => {
    const startedAt = performance.now();
    await ready();
    const prepared = await prepareChat(db, actor(request), request.body, true);
    prepared.gatewayPrepareMs = Math.round(performance.now() - startedAt);
    executions.start(prepared, request.localIdentity!);
    return { chatExecutionId: prepared.chatExecutionId, contextId: prepared.contextId, messageId: prepared.assistantId };
  });
  app.get<{ Params: { id: string }; Querystring: { after?: string } }>('/api/chat/executions/:id/events', async (request, reply) => {
    await ready();
    const id = uuidValue(request.params.id)!;
    const row = await executions.owned(id, actor(request));
    const after = Number(request.query.after ?? 0);
    if (!Number.isSafeInteger(after) || after < 0) invalid('事件游标无效');
    reply.hijack();
    for (const [key, value] of Object.entries(reply.getHeaders())) if (value !== undefined) reply.raw.setHeader(key, value);
    reply.raw.writeHead(200, { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-cache, no-transform',
      'X-Accel-Buffering': 'no', 'X-Context-Id': row.context_id });
    const abort = abortForReply(reply);
    try {
      for await (const event of executions.follow(id, row, after, abort.controller.signal)) {
        if (!reply.raw.write(event)) await once(reply.raw, 'drain', { signal: abort.controller.signal });
      }
    } catch (error) { if (!abort.controller.signal.aborted) throw error; }
    finally { abort.dispose(); if (!reply.raw.writableEnded) reply.raw.end(); }
  });
  app.post<{ Params: { id: string } }>('/api/chat/executions/:id/cancel', async request => {
    await ready();
    const id = uuidValue(request.params.id)!;
    await executions.owned(id, actor(request));
    return { chatExecutionId: id, cancelled: await executions.cancel(id) };
  });
  const sync = async (request: FastifyRequest, reply: FastifyReply) => {
    const prepared = await prepareChat(db, actor(request), request.body); const abort = abortForReply(reply);
    let persisted = false;
    const saveFailure = async (message: string) => {
      const capture = new StreamCapture(); capture.failure = message;
      if (abort.controller.signal.aborted) capture.cancelled = true;
      await persistCapture(db, prepared, capture);
      persisted = true;
    };
    try {
      const response = await gateway.request('/ai/chat/text', { identity: request.localIdentity!, method: 'POST', body: prepared.body, signal: abort.controller.signal });
      if (!response.ok) {
        await saveFailure(`模型服务请求失败（HTTP ${response.status}）`);
        return await forwardError(response, reply);
      }
      const data = objectValue(await response.json());
      if (typeof data.text !== 'string' || !data.text) throw new HttpError(502, 'AI_EMPTY_RESPONSE');
      const metadata = data.metadata && typeof data.metadata === 'object' ? data.metadata as Record<string, unknown> : {};
      const combined = { ...metadata, confidence: data.confidence, tokens_used: data.tokens_used ?? data.tokensUsed,
        model_info: data.model_info ?? data.modelInfo, sources: data.sources, reasoning_path: data.reasoning_path ?? data.reasoningPath };
      await transaction(db, async client => {
        await ownedConversation(client, prepared.conversationId, prepared.actorId, true);
        await saveMessage(client, prepared.conversationId, prepared.actorId, 'ASSISTANT', data.text as string, combined);
      });
      persisted = true;
      return { ...data, contextId: prepared.contextId, tokensUsed: data.tokens_used ?? data.tokensUsed,
        modelInfo: data.model_info ?? data.modelInfo, reasoningPath: data.reasoning_path ?? data.reasoningPath };
    } catch (error) {
      if (!persisted) await saveFailure(abort.controller.signal.aborted ? '已停止生成' : '模型请求失败，请重试').catch(() => {
        console.error('CHAT_PERSIST_FAILED');
      });
      if (error instanceof GatewayError) throw new HttpError(error.status, error.code);
      throw error;
    } finally { abort.dispose(); }
  };
  app.post('/api/chat/text', sync);
  app.post('/ai/chat/text', sync);
  app.post('/api/ai/chat/text', sync);

  const stream = async (request: FastifyRequest, reply: FastifyReply) => {
    const prepared = await prepareChat(db, actor(request), request.body); const abort = abortForReply(reply);
    const capture = new StreamCapture(); let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    let idleTimer: ReturnType<typeof setTimeout> | undefined; let durationTimer: ReturnType<typeof setTimeout> | undefined;
    const timeout = (code: string, message: string) => { capture.failure = message; abort.controller.abort(new Error(code)); };
    const resetIdle = () => {
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => timeout('SSE_IDLE_TIMEOUT', '等待模型响应超时，请重试'), config.streamIdleTimeoutMs ?? 240000);
      idleTimer.unref();
    };
    try {
      resetIdle();
      if (config.streamMaxDurationMs && config.streamMaxDurationMs > 0) {
        durationTimer = setTimeout(() => timeout('SSE_MAX_DURATION', '本次回复已达到最长生成时间，请重试'), config.streamMaxDurationMs); durationTimer.unref();
      }
      const response = await gateway.request('/ai/chat/text/stream', { identity: request.localIdentity!, method: 'POST', body: prepared.body,
        headers: { Accept: 'text/event-stream' }, signal: abort.controller.signal });
      if (!response.ok) { capture.failure = `模型服务请求失败（HTTP ${response.status}）`; return await forwardError(response, reply); }
      if (!response.body || !response.headers.get('content-type')?.includes('text/event-stream')) throw new HttpError(502, 'AI_INVALID_STREAM');
      reply.hijack();
      for (const [key, value] of Object.entries(reply.getHeaders())) if (value !== undefined) reply.raw.setHeader(key, value);
      reply.raw.writeHead(response.status, { 'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache, no-transform', 'X-Accel-Buffering': 'no', Connection: 'keep-alive', 'X-Context-Id': prepared.contextId });
      reader = response.body.getReader();
      while (!abort.controller.signal.aborted) {
        const next = await reader.read();
        if (next.done) break;
        resetIdle(); capture.accept(next.value);
        if (!reply.raw.write(next.value)) await once(reply.raw, 'drain', { signal: abort.controller.signal });
      }
      capture.finish();
      if (!capture.completed && !capture.failure) capture.failure = '回复连接中断，请重试';
      if (capture.failure && !reply.raw.destroyed && !abort.controller.signal.aborted) {
        reply.raw.write(`event: error\ndata: ${JSON.stringify({ event: 'error', requestId: capture.requestId, sequence: ++capture.sequence,
          data: { code: 'AI_STREAM_INTERRUPTED', message: capture.failure, retryable: true } })}\n\n`);
      }
    } catch (error) {
      if (abort.controller.signal.aborted && !capture.failure) capture.cancel();
      else capture.failure ??= error instanceof HttpError ? error.message : '模型连接中断，请重试';
      if (!reply.raw.headersSent && !reply.raw.destroyed) {
        const status = error instanceof HttpError ? error.statusCode : error instanceof GatewayError ? error.status : 502;
        reply.code(status).send({ error: error instanceof GatewayError ? error.code : 'AI_STREAM_FAILED', message: capture.failure });
      } else if (!reply.raw.destroyed) {
        reply.raw.write(`event: error\ndata: ${JSON.stringify({ event: 'error', requestId: capture.requestId, sequence: ++capture.sequence,
          data: { code: 'AI_STREAM_INTERRUPTED', message: capture.failure, retryable: true } })}\n\n`);
      }
    } finally {
      clearTimeout(idleTimer); clearTimeout(durationTimer); abort.dispose();
      await reader?.cancel().catch(() => undefined);
      // Flush history before terminating the stream so the UI's immediate refresh
      // observes the assistant result, including cancelled/failed partial replies.
      await persistCapture(db, prepared, capture).catch(error => {
        if (error instanceof HttpError && error.statusCode === 404) return;
        console.error('CHAT_PERSIST_FAILED');
        if (reply.raw.headersSent && !reply.raw.destroyed && !reply.raw.writableEnded) {
          reply.raw.write(`event: error\ndata: ${JSON.stringify({ event: 'error', requestId: capture.requestId, sequence: ++capture.sequence,
            data: { code: 'CHAT_PERSIST_FAILED', message: '回复保存失败，请检查本机数据库', retryable: false } })}\n\n`);
        }
      });
      if (reply.raw.headersSent && !reply.raw.writableEnded) reply.raw.end();
    }
  };
  app.post('/ai/chat/text/stream', stream);
  app.post('/api/ai/chat/text/stream', stream);
  app.get<{ Params: { context: string } }>('/api/chat/history/:context', async request => {
    const conversation = await ownedConversation(db, request.params.context, actor(request));
    return (await db.query<MessageRow>('SELECT * FROM messages WHERE conversation_id=$1 ORDER BY created_at,id', [conversation.id])).rows.map(messageWire);
  });
  app.delete<{ Params: { context: string } }>('/api/chat/history/:context', async (request, reply) => {
    const existing = await ownedConversation(db, request.params.context, actor(request));
    await clearChatSession(gateway, request, existing.context_id);
    await transaction(db, async client => {
      const conversation = await ownedConversation(client, request.params.context, actor(request), true);
      await client.query('DELETE FROM messages WHERE conversation_id=$1', [conversation.id]);
      await client.query('DELETE FROM conversations WHERE id=$1 AND user_id=$2', [conversation.id, actor(request)]);
    });
    return reply.code(204).send();
  });
}
