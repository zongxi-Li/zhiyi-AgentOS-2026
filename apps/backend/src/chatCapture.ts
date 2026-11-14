import { applyTranscript, mergeResponseTimings, workingContext, contextUsage, type TranscriptBlock, type StreamEvent, type ResponseTimings } from './shared/chat-stream/index.mjs';

export class StreamCapture {
  content = ''; reasoning = ''; completed = false; cancelled = false;
  readonly transcript: TranscriptBlock[] = [];
  failure: string | null = null; requestId = 'unknown'; sequence = 0;
  private buffer = ''; private readonly decoder = new TextDecoder();
  private reasoningStarted = false; private reasoningCompleted = false; private reasoningTruncated = false;
  private readonly usage: Record<string, unknown> = {};
  private readonly responseTimings: ResponseTimings = {};
  private readonly tools = new Map<string, Record<string, unknown>>();
  private readonly sources = new Map<string, Record<string, unknown>>();

  constructor(private readonly onEvent?: (event: StreamEvent) => void) {}

  accept(chunk: Uint8Array) { this.acceptText(this.decoder.decode(chunk, { stream: true })); }
  finish() { this.acceptText(this.decoder.decode()); }
  acceptText(text: string) {
    this.buffer += text;
    let separator: RegExpExecArray | null;
    while ((separator = /\r?\n\r?\n/.exec(this.buffer))) {
      const event = this.buffer.slice(0, separator.index);
      this.buffer = this.buffer.slice(separator.index + separator[0].length);
      this.acceptEvent(event);
    }
    if (this.buffer.length > 2 * 1024 * 1024) this.buffer = '';
  }
  private acceptEvent(frame: string) {
    const lines = frame.split(/\r?\n/); const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
    if (!data) return;
    try {
      const envelope = JSON.parse(data) as Record<string, unknown>;
      const kind = String(envelope.event ?? lines.find(line => line.startsWith('event:'))?.slice(6).trim());
      const payload = envelope.data && typeof envelope.data === 'object' && !Array.isArray(envelope.data) ? envelope.data as Record<string, unknown> : {};
      const event = { ...envelope, event: kind, data: payload } as StreamEvent;
      if (this.onEvent) this.onEvent(event);
      else this.apply(event);
    } catch { /* Malformed frames never enter history. */ }
  }
  apply(envelope: StreamEvent) {
      const kind = envelope.event, payload = envelope.data;
      mergeResponseTimings(this.responseTimings, payload.responseTimings);
      const watermark = contextUsage(payload.contextUsage);
      if (watermark) this.usage.contextUsage = watermark;
      // The browser and durable history use exactly the same ordering fold.
      if (kind === 'reasoning_delta' && typeof payload.delta === 'string') {
        const remaining = Math.max(0, 200000 - this.reasoning.length);
        this.reasoningTruncated ||= payload.delta.length > remaining;
        envelope = { ...envelope, data: { ...payload, delta: payload.delta.slice(0, remaining),
          ...(payload.delta.length > remaining ? {truncated: true} : {}) } };
      }
      applyTranscript(this.transcript, envelope);
      if (typeof envelope.requestId === 'string') this.requestId = envelope.requestId;
      if (typeof envelope.sequence === 'number') this.sequence = Math.max(this.sequence, envelope.sequence);
      const copy = (...keys: string[]) => { for (const key of keys) if (payload[key] !== undefined && payload[key] !== null) this.usage[key] = payload[key]; };
      if (['model_phase', 'model_context', 'model_activity', 'usage'].includes(kind)) {
        const budget = workingContext(payload.workingContext);
        if (budget) this.usage.workingContext = budget;
        copy('projectionVersion', 'archivedItems', 'providerRequest', 'attemptId', 'turn', 'retryAttempt');
      }
      if (kind === 'reasoning_start') { this.reasoningStarted = true; copy('requestedThinkingMode', 'effectiveThinkingMode', 'effectiveReasoningEffort'); }
      if (kind === 'reasoning_delta' && typeof payload.delta === 'string') {
        this.reasoningStarted = true;
        const remaining = Math.max(0, 200000 - this.reasoning.length);
        this.reasoning += payload.delta.slice(0, remaining); this.reasoningTruncated ||= payload.delta.length > remaining;
      }
      if (kind === 'reasoning_end') { this.reasoningCompleted = true; copy('reasoningPhaseMs'); }
      if (kind === 'content_delta' && typeof payload.delta === 'string') {
        this.content += payload.delta;
        if (this.reasoningStarted) this.reasoningCompleted = true;
      }
      if (kind === 'usage') copy('inputTokens', 'input_tokens', 'reasoningTokens', 'reasoning_tokens', 'outputTokens', 'output_tokens',
        'totalTokens', 'total_tokens', 'latencyMs', 'effectiveModel', 'requestedModel', 'requestedThinkingMode', 'effectiveThinkingMode', 'effectiveReasoningEffort', 'resolutionReasons', 'contextFixedTokens', 'contextTokenMethod', 'contextWindowTokens', 'cached_tokens', 'cacheUsageAvailable', 'last_input_tokens', 'last_output_tokens', 'protocolSession');
      if (kind === 'model_context') {
        copy('requestBodyBytes', 'contextWindowTokens', 'effectiveModel');
        if (payload.contextMeasurement === 'provider-usage') {
          copy('contextInputTokens', 'contextMeasurement', 'last_input_tokens', 'last_output_tokens', 'protocolSession');
          const context = workingContext(this.usage.workingContext);
          if (context && typeof payload.last_input_tokens === 'number') {
            this.usage.workingContext = {...context, actualInputTokens: payload.last_input_tokens};
          }
        } else if (this.usage.contextMeasurement !== 'provider-usage') copy('contextInputTokens', 'contextMeasurement');
      }
      if (['tool_start', 'tool_result', 'tool_error', 'approval_required', 'approval_resolved',
        'execution_started', 'stdout_delta', 'stderr_delta', 'execution_completed', 'execution_failed', 'execution_cancelled'].includes(kind)) {
        const status = kind === 'approval_required' ? 'approval_required'
          : kind === 'tool_result' && (payload.activity as any)?.status === 'running' ? 'running'
          : ['tool_result', 'execution_completed'].includes(kind) ? 'completed'
          : ['tool_error', 'execution_failed'].includes(kind) ? 'failed'
          : kind === 'execution_cancelled' ? 'cancelled' : 'running';
        this.addTool({ ...payload, status }); this.addSources(payload.sources);
      }
      if (kind === 'done') {
        this.completed = !this.failure && payload.status === 'completed';
        if (!this.completed && !this.failure) { this.cancelled = payload.status === 'cancelled'; this.failure = this.cancelled ? '已停止生成' : '回复生成未完成，请重试'; }
        this.addSources(payload.sources);
        if (Array.isArray(payload.toolExecutions)) for (const value of payload.toolExecutions) {
          if (value && typeof value === 'object') this.addTool(value as Record<string, unknown>);
        }
        copy('toolsUsed');
      }
      if (kind === 'error') { this.completed = false; this.failure = typeof payload.message === 'string' ? payload.message : '回复生成失败，请重试'; }
      return envelope;
  }
  private addTool(data: Record<string, unknown>) {
    const key = String(data.callId ?? data.toolName ?? this.tools.size);
    const previous = this.tools.get(key) || {};
    if ((data.activity as any)?.status === 'running') data = { ...data, status: 'running' };
    if (['completed', 'failed', 'cancelled'].includes(String(previous.status)) && data.status === 'running') return;
    this.tools.set(key, { ...previous, ...Object.fromEntries(Object.entries(data).filter(([field, value]) => value !== undefined
      && ['callId', 'toolName', 'status', 'durationMs', 'inputSummary', 'outputSummary', 'sourceRefs', 'errorCode', 'terminal', 'activity', 'approval'].includes(field))) });
  }
  private addSources(data: unknown) {
    if (!Array.isArray(data)) return;
    for (const value of data) {
      if (!value || typeof value !== 'object') continue;
      const source = value as Record<string, unknown>; const key = String(source.citationId ?? source.url ?? source.title ?? '');
      if (key) this.sources.set(key, Object.fromEntries(Object.entries(source).filter(([field]) => ['citationId', 'title', 'filename', 'url', 'snippet', 'provider', 'retrievedAt'].includes(field))));
    }
  }
  cancel() { if (!this.completed && !this.failure) { this.cancelled = true; this.failure = '已停止生成'; } }
  metadata(model?: unknown): Record<string, unknown> {
    if (this.failure) applyTranscript(this.transcript, {event: 'error', data: {}});
    const data = { ...this.usage };
    const tools = [...this.tools.values()].map<Record<string, unknown>>(item => this.failure && ['running', 'approval_required'].includes(String(item.status))
      ? { ...item, status: 'interrupted', ...(item.approval && (item.approval as any).status === 'pending'
        ? {approval: {...item.approval as any, status: 'expired'}} : {}) } : item);
    for (const name of ['input', 'reasoning', 'output', 'total']) {
      if (data[`${name}_tokens`] !== undefined && data[`${name}Tokens`] === undefined) data[`${name}Tokens`] = data[`${name}_tokens`];
      delete data[`${name}_tokens`];
    }
    const status = this.completed ? 'completed' : this.cancelled ? 'cancelled' : 'failed';
    const summary: Record<string, unknown>[] = [{ stage: 'chat_stream', status,
      description: this.completed ? '回复已完成' : this.failure ?? '回复连接中断，请重试' }];
    for (const item of tools) summary.push({ stage: `tool:${item.toolName ?? 'unknown'}:${item.callId ?? item.toolName}`,
      status: item.status ?? 'completed', description: `${item.toolName ?? '工具'} 调用${item.status === 'failed' ? '失败' : item.status === 'running' ? '仍在执行' : '完成'}`,
      ...(item.durationMs !== undefined ? { durationMs: item.durationMs } : {}),
      ...(item.approval ? { approval: item.approval } : {}),
      ...(item.terminal ? { terminal: item.terminal } : {}), ...(item.activity ? { activity: item.activity } : {}) });
    if (this.reasoningStarted) summary.push({ stage: 'reasoning', status: this.reasoningCompleted ? 'completed' : 'interrupted',
      description: this.reasoningCompleted ? '模型完成思考阶段' : '模型思考阶段未完整结束' });
    if (this.content) summary.push({ stage: 'answer_generation', status: this.completed ? 'completed' : 'interrupted',
      description: this.completed ? '模型完成最终回答生成' : '最终回答生成未完整结束' });
    return { ...data, responseTimings: {...this.responseTimings}, thinkingEnabled: this.reasoningStarted, fallbackUsed: false, executionSummary: summary,
      transcript: this.transcript,
      ...(data.effectiveModel === undefined ? { model_info: typeof model === 'string' ? model : '' } : {}),
      ...(this.reasoning ? { reasoningContent: this.reasoning } : {}), ...(this.reasoningTruncated ? { reasoningTruncated: true } : {}),
      ...(tools.length ? { toolExecutions: tools, toolsUsed: [...new Set(tools.map(item => item.toolName))] } : {}),
      ...(this.sources.size ? { sources: [...this.sources.values()] } : {}) };
  }
}
