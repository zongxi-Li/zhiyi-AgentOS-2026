// Shared by the gateway history projection and browser live view. No I/O or framework state.
const textKinds = { content_delta: 'text', reasoning_delta: 'reasoning' };
const toolStates = {
  tool_start: 'running', tool_result: 'completed', tool_error: 'failed',
  approval_required: 'approval_required', approval_resolved: 'running',
  execution_started: 'running', stdout_delta: 'running', stderr_delta: 'running',
  execution_completed: 'completed', execution_failed: 'failed', execution_cancelled: 'cancelled',
};

export function mergeResponseTimings(target, source) {
  if (!source || typeof source !== 'object') return target;
  for (const key of ['gatewayPrepareMs', 'contextPreparationMs', 'providerHeadersMs', 'providerFirstByteMs', 'firstReasoningMs', 'firstContentMs']) {
    if (typeof source[key] === 'number' && Number.isFinite(source[key]) && source[key] >= 0) target[key] = source[key];
  }
  return target;
}

export function applyTranscript(blocks, event) {
  const data = event.data || {};
  const close = (state = 'completed') => {
    for (const block of blocks) if (block.state === 'streaming') block.state = state;
  };
  const kind = textKinds[event.event];
  if (kind && typeof data.delta === 'string' && data.delta) {
    let block = blocks.at(-1);
    if (!block || block.kind !== kind || block.state !== 'streaming'
      || (data.partId && block.id !== data.partId)) {
      close();
      block = { id: data.partId || `${event.requestId || 'legacy'}:part:${blocks.length}`,
        kind, text: '', state: 'streaming', attemptId: data.attemptId };
      blocks.push(block);
    }
    block.text += data.delta;
    if (data.truncated) block.truncated = true;
  } else if (Object.hasOwn(toolStates, event.event)) {
    close();
    const callId = String(data.callId || data.approval?.toolCallId || data.toolName || 'unknown');
    const nextState = event.event === 'tool_result' && data.activity?.status === 'running' ? 'background' : toolStates[event.event];
    let block = blocks.find(item => item.kind === 'tool' && item.callId === callId);
    if (!block) {
      block = { id: `tool:${callId}`, kind: 'tool', callId,
        toolName: String(data.toolName || data.approval?.toolName || 'tool'), state: nextState };
      blocks.push(block);
    }
    // A late start/approval notification must not reopen a confirmed result.
    if (!['completed', 'failed', 'cancelled'].includes(block.state)) block.state = nextState;
  } else if (event.event === 'model_phase' && data.phase === 'retrying') {
    close('interrupted');
    blocks.push({ id: `${data.attemptId || event.requestId}:retry:${blocks.length}`, kind: 'status',
      text: `模型连接中断，重试当前请求（${data.retryAttempt || 1}/1）`, state: 'completed', attemptId: data.attemptId });
  }
  else if (event.event === 'model_phase' && data.phase === 'waiting') close();
  else if (event.event === 'reasoning_end') {
    for (const block of blocks) if (block.kind === 'reasoning' && block.state === 'streaming') block.state = 'completed';
  } else if (event.event === 'done' || event.event === 'error') {
    const state = event.event === 'done' && (!data.status || data.status === 'completed') ? 'completed' : 'interrupted';
    close(state);
    for (const block of blocks) if (block.kind === 'tool' && ['running', 'approval_required'].includes(block.state)) block.state = 'interrupted';
  }
  return blocks;
}

export function restoreTranscript(value) {
  if (!Array.isArray(value)) return [];
  return value.filter(block => block && typeof block.id === 'string'
    && ['text', 'reasoning', 'tool', 'status'].includes(block.kind) && typeof block.state === 'string'
    && (block.kind === 'tool' ? typeof block.callId === 'string' : typeof block.text === 'string'))
    .map(block => ({ ...block }));
}

// Never merge across a structural boundary; controls and terminal events flush immediately.
export function createStreamBatcher(emit, { delayMs = 16, maxChars = 4096, maxEvents = 128 } = {}) {
  let pending;
  let count = 0;
  let timer;
  const flush = () => {
    clearTimeout(timer); timer = undefined;
    const event = pending; pending = undefined; count = 0;
    if (event) emit(event);
  };
  return {
    accept(event) {
      if (!textKinds[event.event] || typeof event.data?.delta !== 'string') { flush(); emit(event); return; }
      if (pending && (pending.event !== event.event || pending.requestId !== event.requestId
        || pending.data.partId !== event.data.partId || pending.data.attemptId !== event.data.attemptId)) flush();
      if (pending) pending = { ...event, data: { ...event.data, delta: pending.data.delta + event.data.delta } };
      else pending = { ...event, data: { ...event.data } };
      count++;
      if (pending.data.delta.length >= maxChars || count >= maxEvents || delayMs <= 0) flush();
      else if (!timer) timer = setTimeout(flush, delayMs);
    },
    flush,
    dispose() { clearTimeout(timer); pending = undefined; timer = undefined; count = 0; },
  };
}
