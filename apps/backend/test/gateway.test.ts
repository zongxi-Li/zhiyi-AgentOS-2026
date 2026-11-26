import { createServer, type Server } from 'node:http';
import { once } from 'node:events';
import Fastify from 'fastify';
import multipart from '@fastify/multipart';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { PythonGateway, registerGateway } from '../src/gateway.js';
import { projectAgentOsResponse } from '../src/gateway-projections.js';

it('projects storage statistics without bodies or private metadata', () => {
  const projected = projectAgentOsResponse('/ai/agentos/v2/runs/run/storage', {
    runId: 'run', records: 2, logicalBytes: 123, growthBytes: null,
    states: { online: 2, payload: 'private' },
    largestRecord: { reference: 'output:ref', bytes: 100, contentType: 'application/json', body: 'secret' },
    body: 'secret', content_ref: 'private/path', pins: ['private-memory'],
  });
  expect(projected).toMatchObject({ runId: 'run', records: 2, logicalBytes: 123, growthBytes: null,
    states: { online: 2 }, largestRecord: { reference: 'output:ref', bytes: 100, contentType: 'application/json' } });
  expect(JSON.stringify(projected)).not.toMatch(/secret|private/u);
});

const identity = { actorId: '11111111-1111-4111-8111-111111111111', tenantId: null } as const;
const token = 'gateway-test-service-authentication-token';
const capabilityModes = ['planning', 'current_run', 'successor_run', 'denied'] as const;
type CapabilityMode = typeof capabilityModes[number];
const reviewCases = [
  { kind: 'workspace_revision_pending', reasonCode: 'WORKSPACE_REVIEW_REVISION_PENDING', canApprove: false,
    decisionRejected: false, displayReason: '系统正在处理审查计划的自动修订，完成正式校验后会继续执行。' },
  { kind: 'workspace_revision_blocked', reasonCode: 'WORKSPACE_REVIEW_REVISION_BLOCKED', canApprove: false,
    decisionRejected: true, displayReason: '修订方案试图更改已开始或已有最终结果的步骤，正式校验已拒绝该方案。',
    errorCode: 'INVALID_PROPOSAL', errorType: '_TransitionRejected' },
  { kind: 'planner_rejected', reasonCode: 'PLANNING_COMMIT_REJECTED', canApprove: false,
    decisionRejected: true, displayReason: '计划修订未通过正式校验，任务仍处于暂停状态。', errorCode: 'INVALID_PROPOSAL' },
  { kind: 'planner_wait', reasonCode: 'PLANNER_WAIT', canApprove: true,
    decisionRejected: false, displayReason: '等待外部材料' },
] as const;

function capabilityFixture(mode: CapabilityMode) {
  const recovery = mode === 'current_run' || mode === 'successor_run';
  return {
    schemaVersion: 1, missionId: `capabilities-${mode}`, runId: `capabilities-${mode}`,
    runtimeRevision: 7, status: recovery ? 'failed' : 'planning',
    isExecutionActive: !recovery, isSuperseded: false,
    lineage: { parentRunId: null, sourceRunId: null, rerunReason: null, supersedesRunId: null, supersededByRunId: null },
    canInspect: true, canDiscuss: true, canCancel: mode === 'planning', canReview: false,
    canExecuteFormalAction: mode === 'planning', formalActions: mode === 'planning' ? ['materialize'] : [],
    canResolveToolApproval: false, canAnswerPlanner: false, canCollaborate: mode === 'planning',
    canSetPermission: mode !== 'denied',
    canRetrySuccessor: mode === 'successor_run', canRecoverCurrentRun: mode === 'current_run',
    retryMode: recovery ? mode : null, retryStepId: recovery ? 'failed-step' : null,
    canRerunSuccessor: recovery, canDecideRevision: false, canApplyRevision: false, canDelete: recovery,
    unavailableReasons: mode === 'denied' ? [{ action: 'canExecuteFormalAction', code: 'AUTHORITY_DENIED' }] : [],
  };
}

describe('Python gateway transport contracts', () => {
  it('retains a safe graph transition diagnostic without exposing its frozen source', () => {
    const result = projectAgentOsResponse('/ai/agentos/v2/runs/run/copilot', { planningProgress: {
      kind: 'blocked', status: 'blocked', message: '图交接受阻', observationId: 'observation', errorCode: 'GRAPH_TRANSITION_REJECTED',
      reason: 'source fingerprint differs', errorType: 'TransitionRejected', canApprove: false,
      sourceRun: { secret: 'PRIVATE' }
    } }) as { planningProgress: Record<string, unknown> };
    expect(result.planningProgress).toMatchObject({ kind: 'blocked', reason: 'source fingerprint differs', errorType: 'TransitionRejected', canApprove: false });
    expect(JSON.stringify(result)).not.toContain('PRIVATE');
  });
  it('keeps a planner failure code in the public trace without exposing model text', () => {
    const result = projectAgentOsResponse('/ai/agentos/v2/runs/run/trace', { runId: 'run', events: [{
      eventId: 'planning-failed', runId: 'run', eventType: 'task_status_changed',
      payload: { planningProgress: true, category: 'planner', kind: 'failed', stage: 'repair',
        errorCode: 'TASK_PLAN_CONTRACT_FAILED', reasoning_content: 'PRIVATE', prompt: 'PRIVATE' },
    }] }) as { events: { payload: Record<string, unknown> }[] };
    expect(result.events[0]!.payload).toMatchObject({ kind: 'failed', stage: 'repair', errorCode: 'TASK_PLAN_CONTRACT_FAILED' });
    expect(JSON.stringify(result)).not.toContain('PRIVATE');
  });
  let server: Server;
  let baseUrl: string;
  beforeAll(async () => {
    const capabilityResponses = new Map<string, unknown>();
    for (const mode of capabilityModes) {
      const actionCapabilities = { ...capabilityFixture(mode), internalDecision: 'PRIVATE' };
      const run = { runId: actionCapabilities.runId, missionId: actionCapabilities.missionId,
        status: actionCapabilities.status, runtimeRevision: actionCapabilities.runtimeRevision, actionCapabilities };
      capabilityResponses.set(`/ai/agentos/v2/runs/${run.runId}`, run);
      capabilityResponses.set(`/ai/agentos/v2/runs?capabilityMode=${mode}`, { items: [run], total: 1, page: 1, pageSize: 20 });
      capabilityResponses.set(`/ai/agentos/v2/missions/${run.missionId}/workspace`, {
        mission: { missionId: run.missionId }, activeRun: run, runs: [run], entries: [], graphNodes: [], diagnostics: [],
      });
    }
    capabilityResponses.set('/ai/agentos/v2/runs/capabilities-current_run/copilot', {
      review: { subjectId: 'graph', subjectType: 'planner', kind: 'workspace_revision_blocked',
        reason: 'Workspace review graph transition rejected: INVALID_PROPOSAL: started or settled work cannot be changed',
        reasonCode: 'WORKSPACE_REVIEW_REVISION_BLOCKED',
        displayReason: '修订方案试图更改已开始或已有最终结果的步骤，正式校验已拒绝该方案。',
        errorCode: 'INVALID_PROPOSAL', errorType: '_TransitionRejected', canApprove: false,
        decisionRejected: true, expectedRunUpdatedAt: '2026-11-16T12:00:00Z', secret: 'PRIVATE' },
      workspaceReview: { schemaVersion: 1, round: 2, graphVersion: 3, status: 'blocked',
        gaps: { missingReadCount: 1, missingListingCount: 0, unsupportedEntryCount: 0,
          missingReads: ['src/main.py'], missingListings: [], unsupportedEntries: [] }, rounds: [], private: 'PRIVATE' },
      exchanges: [{ operationId: 'recover-operation', action: { kind: 'recover', stepId: 'failed-step',
        expectedRevision: 7, retryMode: 'current_run', executeStepIds: ['failed-step'], reusedStepIds: [],
        content: '', internalDecision: 'PRIVATE' } }],
    });
    capabilityResponses.set('/ai/agentos/v2/runs/repair-progress/copilot', {
      runId: 'repair-progress', status: 'retrying', review: null,
      planningProgress: { kind: 'repairing', status: 'retrying',
        message: '正在根据审查反馈自动修正计划', observationId: 'denied-observation',
        errorCode: 'INVALID_PROPOSAL', rejectedPatch: 'PRIVATE' },
    });
    for (const review of reviewCases) {
      capabilityResponses.set(`/ai/agentos/v2/runs/review-${review.kind}/copilot`, {
        runId: `review-${review.kind}`, status: 'waiting_review',
        review: { subjectId: 'graph', subjectType: 'planner', reason: 'current diagnostic',
          expectedRunUpdatedAt: '2026-11-16T12:00:00Z', ...review, continuationPatch: { private: 'PRIVATE' } },
      });
    }
    server = createServer(async (request, reply) => {
      if (capabilityResponses.has(request.url ?? '')) {
        reply.setHeader('content-type', 'application/json');
        reply.end(JSON.stringify(capabilityResponses.get(request.url!)));
        return;
      }
      if (request.url === '/ai/slow') {
        setTimeout(() => reply.end('late'), 200).unref();
        return;
      }
      if (request.url?.startsWith('/ai/events')) {
        reply.writeHead(200, { 'content-type': 'text/event-stream' });
        reply.write('event: runtime\nid: 1\ndata: {"text":"首段"}\n\n');
        if (request.url === '/ai/events-idle') return;
        setTimeout(() => reply.end('event: done\ndata: {"usage":{"total_tokens":7}}\n\n'), 30).unref();
        return;
      }
      if (request.url === '/ai/agentos/v2/missions/mission/workspace/events') {
        reply.writeHead(200, { 'content-type': 'text/event-stream' });
        reply.write('id: 42\nevent: workspace.projection.updated\ndata: {"eventType":"workspace.projection.updated","schemaVersion":1,"missionId":"mission","projectionRevision":42}\n\n');
        reply.end(': workspace heartbeat\n\n');
        return;
      }
      if (request.url === '/ai/error') {
        reply.writeHead(409, { 'content-type': 'application/json', 'set-cookie': 'private=value' });
        reply.end(JSON.stringify({ code: 'REVISION_CONFLICT', message: 'revision changed', requestId: 'python-request' }));
        return;
      }
      const chunks: Buffer[] = [];
      for await (const chunk of request) chunks.push(Buffer.from(chunk));
      const body = Buffer.concat(chunks);
      if (request.url === '/ai/binary') {
        reply.writeHead(206, { 'content-type': 'application/octet-stream', 'content-disposition': 'attachment; filename="artifact.bin"', 'content-range': 'bytes 0-3/4' });
        reply.end(Buffer.from([0, 255, 127, 10]));
      } else if (request.url === '/ai/upload') {
        reply.writeHead(201, { 'content-type': request.headers['content-type'] }); reply.end(body);
      } else {
        reply.setHeader('content-type', 'application/json');
        reply.end(JSON.stringify({ method: request.method, path: request.url, headers: request.headers, body: body.toString() }));
      }
    });
    server.listen(0, '127.0.0.1'); await once(server, 'listening');
    const address = server.address();
    if (!address || typeof address === 'string') throw new Error('missing listener');
    baseUrl = `http://127.0.0.1:${address.port}`;
  });
  afterAll(async () => { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); });

  const gateway = () => new PythonGateway({ pythonBaseUrl: baseUrl, internalServiceToken: token });

  it.each(capabilityModes)('retains the complete %s capability snapshot through public Run and workspace HTTP responses', async mode => {
    const app = Fastify();
    app.decorateRequest('localIdentity', null);
    app.addHook('onRequest', async request => { request.localIdentity = identity; });
    registerGateway(app, gateway());
    try {
      const expected = capabilityFixture(mode);
      const run = await app.inject(`/api/agentos/v2/runs/${expected.runId}`);
      const list = await app.inject(`/api/agentos/v2/runs?capabilityMode=${mode}`);
      const workspace = await app.inject(`/api/agentos/v2/missions/${expected.missionId}/workspace`);
      for (const response of [run, list, workspace]) expect(response.statusCode).toBe(200);
      for (const actual of [run.json().actionCapabilities, list.json().items[0].actionCapabilities,
        workspace.json().activeRun.actionCapabilities, workspace.json().runs[0].actionCapabilities]) {
        expect(actual).toEqual(expected);
      }
      expect(JSON.stringify([run.json(), list.json(), workspace.json()])).not.toContain('PRIVATE');
    } finally {
      await app.close();
    }
  });

  it('retains the current Run recovery mode in public Copilot HTTP responses', async () => {
    const app = Fastify();
    app.decorateRequest('localIdentity', null);
    app.addHook('onRequest', async request => { request.localIdentity = identity; });
    registerGateway(app, gateway());
    try {
      const response = await app.inject('/api/agentos/v2/runs/capabilities-current_run/copilot');
      expect(response.statusCode).toBe(200);
      expect(response.json().review).toMatchObject({ kind: 'workspace_revision_blocked',
        displayReason: '修订方案试图更改已开始或已有最终结果的步骤，正式校验已拒绝该方案。',
        errorCode: 'INVALID_PROPOSAL', errorType: '_TransitionRejected', canApprove: false });
      expect(response.json().workspaceReview).toMatchObject({ schemaVersion: 1, status: 'blocked', graphVersion: 3,
        gaps: { missingReadCount: 1, missingReads: ['src/main.py'] } });
      expect(response.json().exchanges[0].action).toMatchObject({ kind: 'recover', stepId: 'failed-step', retryMode: 'current_run' });
      expect(response.body).not.toContain('PRIVATE');
    } finally {
      await app.close();
    }
  });

  it.each(reviewCases)('retains the $kind review cause and approval flag through public HTTP responses', async expected => {
    const app = Fastify();
    app.decorateRequest('localIdentity', null);
    app.addHook('onRequest', async request => { request.localIdentity = identity; });
    registerGateway(app, gateway());
    try {
      const response = await app.inject(`/api/agentos/v2/runs/review-${expected.kind}/copilot`);
      expect(response.statusCode).toBe(200);
      expect(response.json().review).toMatchObject(expected);
      expect(response.body).not.toContain('PRIVATE');
      expect(response.json().review).not.toHaveProperty('continuationPatch');
    } finally {
      await app.close();
    }
  });

  it('retains active planning repair progress through public HTTP without inventing a review', async () => {
    const app = Fastify();
    app.decorateRequest('localIdentity', null);
    app.addHook('onRequest', async request => { request.localIdentity = identity; });
    registerGateway(app, gateway());
    try {
      const response = await app.inject('/api/agentos/v2/runs/repair-progress/copilot');
      expect(response.statusCode).toBe(200);
      expect(response.json().planningProgress).toEqual({ kind: 'repairing', status: 'retrying',
        message: '正在根据审查反馈自动修正计划', observationId: 'denied-observation', errorCode: 'INVALID_PROPOSAL' });
      expect(response.json().review).toBeNull();
      expect(response.body).not.toContain('PRIVATE');
    } finally {
      await app.close();
    }
  });

  it('rebuilds trusted identity and service authentication, stripping supplied authority and cookie headers', async () => {
    const client = gateway();
    const response = await client.request('/ai/echo?cursor=a%2Fb', { identity, method: 'POST', body: { message: '真实输入' },
      headers: { authorization: 'old-user-jwt', cookie: 'session=old', 'x-authenticated-user-id': 'forged', 'x-internal-service-token': 'forged', 'x-authenticated-tenant-id': 'forged' } });
    const value = await response.json() as { path: string; headers: Record<string, string>; body: string };
    expect(value.path).toBe('/ai/echo?cursor=a%2Fb');
    expect(value.headers['x-internal-service-token']).toBe(token);
    expect(value.headers['x-authenticated-user-id']).toBe(identity.actorId);
    expect(value.headers['x-authenticated-tenant-id']).toBeUndefined();
    expect(value.headers.authorization).toBeUndefined(); expect(value.headers.cookie).toBeUndefined();
    expect(JSON.parse(value.body)).toEqual({ message: '真实输入' });
    client.close();
  });

  it('preserves HTTP business errors and binary responses through Fastify', async () => {
    const app = Fastify();
    app.decorateRequest('localIdentity', null);
    app.addHook('onRequest', async request => { request.localIdentity = identity; });
    registerGateway(app, gateway());
    const error = await app.inject('/ai/error');
    expect(error.statusCode).toBe(409); expect(error.json()).toEqual({ code: 'REVISION_CONFLICT', message: 'revision changed', requestId: 'python-request' });
    expect(error.headers['set-cookie']).toBeUndefined();
    const binary = await app.inject('/ai/binary');
    expect(binary.statusCode).toBe(206); expect(binary.rawPayload).toEqual(Buffer.from([0, 255, 127, 10]));
    expect(binary.headers['content-disposition']).toBe('attachment; filename="artifact.bin"');
    expect(binary.headers['content-range']).toBe('bytes 0-3/4');
    const apiAlias = await app.inject('/api/ai/error');
    expect(apiAlias.statusCode).toBe(409);
    expect(apiAlias.json().code).toBe('REVISION_CONFLICT');
    await app.close();
  });

  it('keeps raw multipart bytes after the parent registers multipart handling', async () => {
    const app = Fastify();
    await app.register(multipart);
    app.decorateRequest('localIdentity', null);
    app.addHook('onRequest', async request => { request.localIdentity = identity; });
    registerGateway(app, gateway());
    const bytes = Buffer.concat([Buffer.from('--test-boundary\r\nContent-Disposition: form-data; name="file"; filename="sample.bin"\r\nContent-Type: application/octet-stream\r\n\r\n'), Buffer.from([0, 255, 1, 10]), Buffer.from('\r\n--test-boundary--\r\n')]);
    const response = await app.inject({ method: 'POST', url: '/ai/upload', headers: { 'content-type': 'multipart/form-data; boundary=test-boundary' }, payload: bytes });
    expect(response.statusCode).toBe(201); expect(response.rawPayload).toEqual(bytes);
    await app.close();
  });

  it('forwards SSE chunks before completion and retains event ids and usage', async () => {
    const client = gateway();
    const response = await client.request('/ai/events', { identity });
    const reader = response.body!.getReader();
    expect(new TextDecoder().decode((await reader.read()).value)).toContain('event: runtime\nid: 1');
    let text = '';
    for (;;) { const chunk = await reader.read(); if (chunk.done) break; text += new TextDecoder().decode(chunk.value); }
    expect(text).toContain('"total_tokens":7'); client.close();
  });

  it('preserves workspace projection watermarks through the public read projection', () => {
    expect(projectAgentOsResponse('/ai/agentos/v2/missions/mission/workspace', {
      mission: { missionId: 'mission' }, projectionRevision: 42, projectionSchemaVersion: 1,
      runs: [], entries: [], graphNodes: [], diagnostics: []
    })).toMatchObject({ projectionRevision: 42, projectionSchemaVersion: 1 });
  });

  it('forwards Mission workspace SSE through the public alias without JSON projection', async () => {
    const app = Fastify();
    app.decorateRequest('localIdentity', null);
    app.addHook('onRequest', async request => { request.localIdentity = identity; });
    registerGateway(app, gateway());
    const response = await app.inject('/api/agentos/v2/missions/mission/workspace/events');
    expect(response.statusCode).toBe(200);
    expect(response.headers['content-type']).toContain('text/event-stream');
    expect(response.body).toContain('id: 42\nevent: workspace.projection.updated');
    expect(response.body).toContain('"projectionRevision":42');
    await app.close();
  });

  it('propagates cancellation, request deadlines and stream idle timeouts', async () => {
    const client = new PythonGateway({ pythonBaseUrl: baseUrl, internalServiceToken: token, aiTimeoutMs: 30, streamIdleTimeoutMs: 30 });
    await expect(client.request('/ai/slow', { identity })).rejects.toMatchObject({ status: 504, code: 'AI_UPSTREAM_TIMEOUT' });
    const signal = new AbortController();
    const response = await client.request('/ai/events-idle', { identity, signal: signal.signal });
    const reader = response.body!.getReader(); await reader.read(); signal.abort();
    await expect(reader.read()).rejects.toBeDefined();
    const idle = await client.request('/ai/events-idle', { identity });
    const idleReader = idle.body!.getReader(); await idleReader.read();
    await expect(idleReader.read()).rejects.toMatchObject({ status: 504 }); client.close();
  });

  it('rejects traversal and missing service credentials without making an upstream request', async () => {
    const client = gateway();
    for (const path of ['//third-party/ai/x', '/ai/%2e%2e/private', '/ai/../private', '/ai/%5cprivate']) {
      await expect(client.request(path, { identity })).rejects.toMatchObject({ status: 400 });
    }
    await expect(new PythonGateway({ pythonBaseUrl: baseUrl }).request('/ai/echo', { identity })).rejects.toMatchObject({ status: 503 });
    client.close();
  });
});

describe('workbench response compatibility', () => {
  it('preserves effective task policy and approval provenance through the query gateway', () => {
    const actor = { userId: 'operator', tenantId: null };
    const policy = { missionId: 'mission', permission: 'task_collaboration', approvalMode: 'full', policyRevision: 4,
      updatedAt: '2026-11-17T06:00:00Z', operationId: 'change', effectiveApprovalMode: 'full', effectiveScopeMatch: true,
      workspaceScope: { workspaceId: 'workspace', grantId: 'grant', resourceId: 'hands' }, updatedBy: actor };
    const decision = { source: 'policy', policyRevision: 4, decidedAt: '2026-11-17T06:00:01Z', actor };
    const result = projectAgentOsResponse('/ai/agentos/v2/runs/run/copilot', {
      approvalMode: 'full', policyRevision: 4, approvalPolicy: { ...policy, secret: 'PRIVATE' },
      toolActivity: [{ executionId: 'execution', approvalDecision: { ...decision, command: 'PRIVATE' } }],
    }) as Record<string, any>;
    expect(result).toMatchObject({ approvalMode: 'full', policyRevision: 4, approvalPolicy: policy });
    expect(result.toolActivity[0].approvalDecision).toEqual(decision);
    expect(JSON.stringify(result)).not.toContain('PRIVATE');
  });
  it('projects the public initial plan and tool receipts without exposing runtime bodies', () => {
    const plan = { planVersion: 3, commitId: 'commit', commitmentRevision: 2,
      objective: 'Inspect the project', constraints: ['Keep existing behavior'], expectedArtifacts: ['report'],
      relations: [{ sourceKey: 'inspect', targetKey: 'report', relationType: 'depends_on' }],
      tasks: [{ key: 'inspect', title: 'Inspect source', objective: 'Locate the cause',
        rationale: 'Read the relevant source before changing behavior', acceptanceCriteria: ['Identify the cause'],
        sourceRefs: ['source:task'], capabilities: ['read'] }] };
    const activity = { executionId: 'execution', tool: 'fs.list', status: 'succeeded', stepId: 'inspect',
      attemptId: 'attempt', receiptRef: 'tool:receipt', createdAt: '2026-11-13T12:00:00Z' };
    const source = { runId: 'run', initialPlan: { ...plan, reasoning_content: 'PRIVATE',
      relations: [...plan.relations.map(relation => ({ ...relation, private: 'PRIVATE' })),
        { sourceKey: { private: 'PRIVATE' }, targetKey: 'report', relationType: 'depends_on' }],
      tasks: plan.tasks.map(task => ({ ...task, capabilities: [...task.capabilities, { private: 'PRIVATE' }], modelMessages: ['PRIVATE'] })) },
      toolActivity: [{ ...activity, content: 'PRIVATE', output: { fileBody: 'PRIVATE' }, authorization: { secret: 'PRIVATE' } }],
      executionState: { rawModelMessages: 'PRIVATE' } };
    const snapshot = structuredClone(source);
    const result = projectAgentOsResponse('/ai/agentos/v2/runs/run/copilot', source) as Record<string, unknown>;
    expect(result.initialPlan).toEqual(plan);
    const runDetail = projectAgentOsResponse('/ai/agentos/v2/runs/run', source);
    expect(runDetail).toMatchObject({ runId: 'run', initialPlan: plan });
    expect(JSON.stringify(runDetail)).not.toContain('PRIVATE');
    expect(runDetail).not.toHaveProperty('executionState');
    expect(result.toolActivity).toEqual([activity]);
    expect(JSON.stringify(result)).not.toContain('PRIVATE');
    expect(result).not.toHaveProperty('executionState');
    expect(source).toEqual(snapshot);
  });

  it('keeps Copilot review diagnostics through the HTTP projection whitelist', () => {
    const result = projectAgentOsResponse('/ai/agentos/v2/runs/run/copilot', { review: {
      subjectId: 'graph', subjectType: 'planner', reason: 'technical rejection', reasonCode: 'PLANNING_COMMIT_REJECTED',
      kind: 'planner_rejected', displayReason: '计划修订未通过正式校验', errorCode: 'INVALID_PROPOSAL',
      errorType: '_TransitionRejected', canApprove: false, decisionRejected: true,
      expectedRunUpdatedAt: '2026-11-16T12:00:00Z', private: 'PRIVATE' },
    }) as Record<string, any>;
    expect(result.review).toMatchObject({ kind: 'planner_rejected', displayReason: '计划修订未通过正式校验',
      errorCode: 'INVALID_PROPOSAL', errorType: '_TransitionRejected', canApprove: false });
    expect(JSON.stringify(result)).not.toContain('PRIVATE');
  });

  it('projects the selected Run planning version through the same public plan shape', () => {
    const plan = { planVersion: 2, commitId: null, commitmentRevision: null,
      objective: 'Revise the inspection plan', constraints: ['Read only'], expectedArtifacts: ['report'],
      relations: [{ sourceKey: 'inspect', targetKey: 'verify', relationType: 'depends_on' }],
      tasks: [{ key: 'verify', title: 'Verify findings', objective: 'Check source references',
        rationale: 'Verify the findings before publication', acceptanceCriteria: ['Cite source paths'],
        sourceRefs: ['source:inspection'], capabilities: ['read'] }] };
    const source = { runId: 'run', plan: { ...plan, metadata: { private: 'PRIVATE' },
      tasks: plan.tasks.map(task => ({ ...task, capabilities: [...task.capabilities, { token: 'PRIVATE' }],
        agentRegistration: { principal: 'PRIVATE' } })) },
      executionState: { messages: 'PRIVATE' }, siblingPlans: ['PRIVATE'] };
    const before = structuredClone(source);
    const result = projectAgentOsResponse('/ai/agentos/v2/runs/run/plan', source);
    expect(result).toEqual({ runId: 'run', plan });
    expect(JSON.stringify(result)).not.toContain('PRIVATE');
    expect(source).toEqual(before);
    expect(projectAgentOsResponse('/ai/agentos/v2/runs/run/plan', { runId: 'run', plan: null }))
      .toEqual({ runId: 'run', plan: null });
  });

  it('keeps absent Copilot plan data compatible and rejects nested values in public scalar fields', () => {
    expect(projectAgentOsResponse('/ai/agentos/v2/runs/run/copilot', { runId: 'run' }))
      .toMatchObject({ initialPlan: null, toolActivity: [] });
    const privateValue = { reasoning_content: 'PRIVATE' };
    const result = projectAgentOsResponse('/ai/agentos/v2/runs/run/copilot', {
      initialPlan: { planVersion: privateValue, commitId: privateValue, commitmentRevision: privateValue,
        objective: privateValue, constraints: ['public constraint', privateValue], expectedArtifacts: [privateValue],
        tasks: [{ key: 'task', title: privateValue, objective: privateValue, rationale: privateValue,
          acceptanceCriteria: ['public criterion', privateValue], sourceRefs: ['source:task', privateValue] }] },
      toolActivity: [{ executionId: 'execution', tool: privateValue, status: privateValue, stepId: privateValue,
        attemptId: privateValue, receiptRef: privateValue, createdAt: privateValue }],
    }) as Record<string, unknown>;
    expect(result.initialPlan).toMatchObject({ planVersion: null, commitId: null, commitmentRevision: null,
      objective: null, constraints: ['public constraint'], expectedArtifacts: [],
      tasks: [{ key: 'task', title: null, objective: null, rationale: null,
        acceptanceCriteria: ['public criterion'], sourceRefs: ['source:task'] }] });
    expect(result.toolActivity).toEqual([{ executionId: 'execution', tool: null, status: null, stepId: null,
      attemptId: null, receiptRef: null, createdAt: null }]);
    expect(JSON.stringify(result)).not.toContain('PRIVATE');
  });

  it('preserves heterogeneous resource provenance in catalog projections', () => {
    const projected = projectAgentOsResponse('/ai/agentos/v2/resources', { total: 1, items: [{
      profile: { resourceId: 'runtime:edge:acme', resourceType: 'worker', deploymentTier: 'edge',
        provider: 'Acme', sourceType: 'kubernetes', adapter: 'k8s-agentos', capabilities: [], domains: [],
        version: 1, enabled: true, capacity: 4 }, snapshot: {}, snapshotVersion: 1
    }] }) as { items: Array<{ profile: Record<string, unknown> }> };

    expect(projected.items[0].profile).toMatchObject({ provider: 'Acme', sourceType: 'kubernetes', adapter: 'k8s-agentos' });
  });

  it('retains the workbench graph, execution resource and node health field names', () => {
    expect(projectAgentOsResponse('/ai/agentos/v2/missions/mission', { mission: {}, tasks: [], blueprints: [{ graphId: 'graph', version: 1 }], runs: [] })).toHaveProperty('graphs', [{ graphId: 'graph', version: 1, createdAt: null }]);
    expect(projectAgentOsResponse('/ai/agentos/v2/nodes', { items: [{ profile: { nodeId: 'node' }, health: { status: 'healthy' }, snapshotVersion: 2 }], total: 1 })).toMatchObject({ items: [{ healthStatus: 'healthy' }] });
    expect(projectAgentOsResponse('/ai/agentos/v2/runs/run/graph', { graphId: 'graph', version: 3,
      nodes: [], edges: [], workspaceReview: { schemaVersion: 1, round: 1, graphVersion: 3, status: 'blocked',
        gaps: { missingReadCount: 0, missingListingCount: 0, unsupportedEntryCount: 0 }, rounds: [], private: 'PRIVATE' } }))
      .toMatchObject({ workspaceReview: { schemaVersion: 1, graphVersion: 3, status: 'blocked', gaps: { missingReadCount: 0 } } });
    expect(projectAgentOsResponse('/ai/agentos/v2/runs/run/execution-tree', { run: {}, blueprint: { graphId: 'graph', version: 1, graph: { nodes: [], edges: [] } }, nodes: [{ task: { taskId: 'task', constraints: [] }, attempts: [{ attempt: {}, executions: [], executionBinding: { resourceId: 'resource' } }] }] })).toMatchObject({ graph: { graphId: 'graph' }, lifecycles: [], nodes: [{ attempts: [{ resourceUse: { resourceId: 'resource' } }] }] });
  });
  it('projects graph history as reference-only version facts', () => {
    const result = projectAgentOsResponse('/ai/agentos/v2/runs/run/graph/versions', {
      runId: 'run', graphId: 'graph', currentBlueprintId: null, currentGraphVersion: 2,
      executionState: 'PRIVATE-RUNTIME', proposals: [{ candidateGraph: 'PRIVATE-PROPOSAL' }],
      items: [{ blueprintId: null, graphId: 'graph', graphVersion: 2, taskPlanVersion: 2,
        current: true, status: 'active', createdAt: null, predecessorBlueprintId: 'blueprint:1', reason: 'Read another page',
        activationId: 'activation:2', handoffId: null, nodes: 'PRIVATE-NODES', executionPermit: 'PRIVATE-PERMIT',
        patch: { patchId: 'patch:2', addedNodeIds: ['read:2'], updatedNodeIds: [], removedNodeIds: [],
          addedEdgeCount: 1, removedEdgeCount: 0, addedNodes: 'PRIVATE-BODY' },
        inherited: { completedStepIds: ['read:1'], skippedStepIds: [], attemptIds: ['attempt:1'],
          outputRefs: { 'read:1': 'output:1', secret: { body: 'PRIVATE-OUTPUT' } }, pendingMemory: 'PRIVATE-MEMORY' } }],
    });
    expect(result).toEqual({ runId: 'run', graphId: 'graph', currentBlueprintId: null, currentGraphVersion: 2,
      items: [{ blueprintId: null, graphId: 'graph', graphVersion: 2, taskPlanVersion: 2, current: true,
        status: 'active', createdAt: null, predecessorBlueprintId: 'blueprint:1', reason: 'Read another page',
        activationId: 'activation:2', handoffId: null,
        patch: { patchId: 'patch:2', addedNodeIds: ['read:2'], updatedNodeIds: [], removedNodeIds: [], addedEdgeCount: 1, removedEdgeCount: 0 },
        inherited: { completedStepIds: ['read:1'], skippedStepIds: [], attemptIds: ['attempt:1'], outputRefs: { 'read:1': 'output:1' } } }],
      proposals: [] });
    expect(JSON.stringify(result)).not.toContain('PRIVATE');
  });
  it('returns formal Run references and allowlisted coordination facts', () => {
    const projectTree = (operational: unknown) => projectAgentOsResponse('/ai/agentos/v2/runs/run/execution-tree', {
      run: { runId: 'run' }, blueprint: {}, nodes: [], operational,
    });
    const projected = projectTree({
      communicationRefs: ['communication:one', { payload: 'PRIVATE' }],
      memoryRefs: ['memory:one'],
      evidenceRefs: ['evidence:one'],
      leaseStatuses: { lease: 'released', unexpected: { payload: 'PRIVATE' } },
      controlFrames: [{ controlId: 'loop', controlType: 'loop', iteration: 2, region: ['step'], observedStates: ['PRIVATE'] }],
      loopIterations: { loop: 2 },
      consensusResults: { gate: { accepted: true, quorum: 2, rawVotes: 'PRIVATE' } },
      debateSessions: { step: { round: 2, phase: 'complete', resultArtifactRef: 'artifact:one', participants: ['step'], transcript: 'PRIVATE' } },
      recoveryOutcome: { payload: 'PRIVATE' },
    });

    expect(projected).toHaveProperty('operational', {
      communicationRefs: ['communication:one'], memoryRefs: ['memory:one'], evidenceRefs: ['evidence:one'],
      leaseStatuses: { lease: 'released' },
      controlFrames: [{ controlId: 'loop', controlType: 'loop', iteration: 2, region: ['step'] }],
      loopIterations: { loop: 2 },
      consensusResults: { gate: { accepted: true, quorum: 2 } },
      debateSessions: { step: { round: 2, phase: 'complete', resultArtifactRef: 'artifact:one', participants: ['step'] } },
    });
    expect(JSON.stringify(projected)).not.toContain('PRIVATE');
    expect(projectTree(null)).toHaveProperty('operational', null);
  });
  it('preserves historical graph identity and edge conditions without runtime overlays', () => {
    const result = projectAgentOsResponse('/ai/agentos/v2/runs/run/graph', {
      runId: 'run', graphId: 'graph', blueprintId: 'blueprint:1', graphVersion: 1, taskPlanVersion: 4, historical: true,
      nodes: [{ nodeId: 'read:1', metadata: { semanticTaskKey: 'read', private: 'PRIVATE-NODE' } }],
      edges: [{ edgeId: 'edge:1', sourceId: 'read:1', targetId: 'review', condition: 'evidence_ready', metadata: {} }],
      completedStepIds: ['future'], activeStepIds: ['future'], skippedStepIds: ['future'], workspaceReview: { round: 9 },
      resourceBindings: 'PRIVATE-RESOURCES', executionState: 'PRIVATE-RUNTIME',
    });
    expect(result).toMatchObject({ blueprintId: 'blueprint:1', historical: true, graphVersion: 1, taskPlanVersion: 4,
      nodes: [{ display: { semanticTaskKey: 'read' } }], edges: [{ condition: 'evidence_ready' }] });
    for (const field of ['completedStepIds', 'activeStepIds', 'skippedStepIds', 'workspaceReview', 'resourceBindings', 'executionState']) {
      expect(result).not.toHaveProperty(field);
    }
    expect(JSON.stringify(result)).not.toContain('PRIVATE');
  });
  it('preserves the compiler task-plan mapping on historical RGraph nodes', () => {
    const result = projectAgentOsResponse('/ai/agentos/v2/runs/run/graph', {
      historical: true, graphId: 'graph', graphVersion: 2, taskPlanVersion: 2,
      nodes: [
        { nodeId: 'expanded-read', metadata: { taskPlanKey: 'inspect', private: 'PRIVATE' } },
        { nodeId: 'explicit', metadata: { taskPlanKey: 'fallback', semanticTaskKey: 'canonical' } },
        { nodeId: 'invalid', metadata: { semanticTaskKey: { private: 'PRIVATE' }, taskPlanKey: { private: 'PRIVATE' } } },
      ],
      edges: [],
    });
    expect(result).toMatchObject({ nodes: [
      { nodeId: 'expanded-read', display: { semanticTaskKey: 'inspect' } },
      { nodeId: 'explicit', display: { semanticTaskKey: 'canonical' } },
      { nodeId: 'invalid', display: { semanticTaskKey: null } },
    ] });
    expect(JSON.stringify(result)).not.toContain('PRIVATE');
    expect(JSON.stringify(result)).not.toContain('taskPlanKey');
  });
  it('projects review, lineage and output references without exposing execution snapshots', () => {
    const result = projectAgentOsResponse('/ai/agentos/v2/runs/run', { runId: 'run', missionId: 'mission', status: 'waiting_review',
      executionState: { graphVersion: 2, reviewPayload: { subjectId: 'review', secret: 'private' }, parentRunId: 'parent', outputRefs: { step: 'manifest' }, outputSummaries: { step: 'summary' }, pendingMemory: 'private' } });
    expect(result).toMatchObject({ runId: 'run', graphVersion: 2, review: { subjectId: 'review' }, lineage: { parentRunId: 'parent' }, outputs: [{ stepId: 'step', outputRef: 'manifest', summary: 'summary' }] });
    expect(JSON.stringify(result)).not.toContain('private'); expect(result).not.toHaveProperty('executionState');
  });
  it('preserves product output content while keeping dynamic history/catalog associations readable', () => {
    expect(projectAgentOsResponse('/ai/agentos/v2/runs/run/outputs/ref', { runId: 'run', outputRef: 'ref', content: { report: ['完整输出', false, 1.25, null] } })).toMatchObject({ content: { kind: 'object', members: [{ name: 'report', value: { kind: 'list', items: [{ text: '完整输出' }, { bool: false }, { number: 1.25 }, { kind: 'null' }] } }] } });
    expect(projectAgentOsResponse('/ai/agentos/v2/runs/run/history-config', { runId: 'run', input: { pluginData: { plugin: { enabled: false, limit: 2, name: 'saved', internal: { private: true } } } } })).toMatchObject({ input: { pluginData: [{ pluginId: 'plugin', entries: [{ name: 'enabled', bool: false }, { name: 'limit', number: 2 }, { name: 'name', text: 'saved' }] }] } });
  });
});
