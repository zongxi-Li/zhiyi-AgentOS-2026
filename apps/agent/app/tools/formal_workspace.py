"""AgentOS-owned, NodeRunner-bound workspace tools. Hands owns no Agent loop."""
import asyncio
import hashlib
import json
from components.executor.value_storage import decode_body
import os
from pathlib import Path
import re
from uuid import uuid4

from adapters.tool.audited_runtime import AuditedToolRuntime
from adapters.tool.hands_http import HandsExecutionCancelled, HandsOutcomeUnknown
from support.async_tasks import await_settled
from components.resource.scheduler.binder import LeaseKeepAlive
from components.resource.scheduler.models import CandidateDecision, FilterReason, ReadyNodeSchedulingResult
from components.executor.value_store import SQLiteExecutionValueStore
from contracts import stable_checksum
from contracts.execution import NodeExecutionRecord
from contracts.resource import ExecutionRequirement, RuntimeKind
from contracts.local_runtime import LocalRuntimeExecutionRequest, LocalRuntimeExecutionLimits
from contracts.native_retrieval import (
    RETRIEVAL_COMMIT_SUFFIXES, RETRIEVAL_LEDGER_VERSION, retrieval_operation_key,
)
from contracts.planning_context import PLANNING_CONTEXT_OWNER, is_planning_context_snapshot
from contracts.runtime_events import RuntimeEvent
from contracts.tools import hands_tools, HOST_TOOL_FAILURE_CODES, HostToolExecutionError, ToolExecutionAuthorizationLost, ToolExecutionResult
from contracts.communication import validate_contract_payload
from runtime.events.live_events import runtime_event_broker
from app.tools.permissions import get_chat_permission_service, normalize_relative_path
from app.tools.task_approval import ApprovalPolicyChanged, TaskApprovalCoordinator
from support.work_timeouts import human_approval_wait

TOOLS = {'read_file':'fs.read','list_files':'fs.list','write_file':'fs.write','patch_file':'fs.patch','run_tests':'shell.exec'}
FIELDS = {'read_file':{'path'},'list_files':{'path'},'write_file':{'path','content'},
          'patch_file':{'path','oldText','newText'},'run_tests':{'path','runner'}}


class FormalWorkspaceTools:
    def __init__(self, runtime, fallback, context=None, guard=None):
        self.runtime,self.fallback,self.context,self.guard = runtime,fallback,context,guard
        self.allowed_tools = frozenset(TOOLS)|frozenset(TOOLS.values())|frozenset(getattr(fallback,'allowed_tools',()))
        self.permissions = get_chat_permission_service()
        if not hasattr(runtime,'formal_tool_pending'): runtime.formal_tool_pending = {}

    def scoped(self, allowed):
        return AuditedToolRuntime(delegate=self, allowed_tools=self.allowed_tools).scoped(allowed)

    def bind_context(self, context, guard):
        return FormalWorkspaceTools(self.runtime,self.fallback,context,guard)

    def list_tools(self):
        return hands_tools()

    def describe(self, name):
        return next((tool for tool in self.list_tools() if tool.name == name), None)

    def prove_not_dispatched(self, *, run, node, operation, tool, raw_arguments,
                             workspace, connection, execution_value_store, memory_policy=None):
        """Read the formal write-ahead barrier; never infer an approval decision.

        execute() commits its request before dispatch. Only this exact adapter
        and ledger implementation can turn an absent request into non-invocation
        evidence. The core separately proves the Attempt ended and closes every
        declaration/activity in the operation before admitting a fresh Attempt.
        """
        if (type(self) is not FormalWorkspaceTools or self.runtime.tool_runtime is not self
                or any(name in vars(self) or getattr(type(self), name) is not implementation
                       for name, implementation in _FORMAL_WRITE_AHEAD_BOUNDARY)):
            raise ValueError('tool recovery requires the installed formal write-ahead adapter')
        store = self.runtime.execution_value_store
        if (store is not execution_value_store or type(store) is not SQLiteExecutionValueStore
                or 'put_tool_value' in vars(store)
                or type(store).put_tool_value is not _SQLITE_TOOL_WRITE_AHEAD):
            raise ValueError('tool recovery requires the unchanged formal write-ahead ledger')
        database = next((row[2] for row in connection.execute('PRAGMA database_list') if row[1] == 'main'), '')
        if not database or Path(database).resolve() != store.db_path.resolve():
            raise ValueError('tool recovery proof and execution ledger use different databases')
        retrieval_session = tool == 'native.retrieval.model-session'
        empty_session = (tool == 'native.tool-session' or retrieval_session) and operation == node.operation_id and raw_arguments is None
        if (workspace != run.input.get('workspaceBinding') or not empty_session and (
                tool not in {'fs.write', 'fs.patch', 'shell.exec'}
                or re.fullmatch(re.escape(node.operation_id) + r':tools:\d+:call:\d+', operation) is None)):
            raise ValueError('tool recovery declaration or frozen workspace does not match')
        row = connection.execute('SELECT payload_json FROM acg_node_executions WHERE run_id=? AND operation_id=?',
                                 (run.run_id, node.operation_id)).fetchone()
        if row is None or NodeExecutionRecord.model_validate_json(row[0]) != node:
            raise ValueError('tool recovery lacks the exact durable node identity')
        if empty_session:
            from components.executor.memory_input import read_frozen_memory_retrieval
            from components.executor.execution_guidance import read_undispatched_guidance_inputs

            memory_input = read_frozen_memory_retrieval(connection, run=run, execution=node, policy=memory_policy)
            internal_refs = {memory_input[0]} if memory_input is not None else set()
            internal_refs.update(read_undispatched_guidance_inputs(connection, run=run, node=node))
            # Core recovery has already verified these read-only prologue slots.
            if retrieval_session:
                internal_refs.update('tool:' + hashlib.sha256((run.run_id + ':' +
                    retrieval_operation_key(node.operation_id, name) + suffix).encode()).hexdigest()
                    for name in RETRIEVAL_COMMIT_SUFFIXES for suffix in (':request', ':result'))
            prefix = node.operation_id + ':'
            model_ref = 'tool:' + hashlib.sha256((run.run_id + ':' + node.operation_id + ':tools:0:model-turn').encode()).hexdigest()
            activity = connection.execute(
                    "SELECT reference,step_id,kind,operation_id,CASE WHEN step_id=? THEN payload_json END "
                    "FROM execution_values WHERE run_id=? AND reference LIKE 'tool:%' AND ("
                    "reference=? OR substr(json_extract(payload_json,'$.request.invocationId'),1,?)=? "
                    "OR substr(json_extract(payload_json,'$.response.requestId'),1,?)=? "
                    "OR json_extract(payload_json,'$.identity.commitId')=? "
                    "OR json_extract(payload_json,'$.record.commitId')=? "
                    "OR json_extract(payload_json,'$.commitId')=?)",
                    (PLANNING_CONTEXT_OWNER, run.run_id, model_ref, len(prefix), prefix, len(prefix), prefix,
                     node.operation_id, node.operation_id, node.operation_id))
            for reference, owner, kind, operation_id, snapshot_body in activity:
                if reference in internal_refs:
                    continue
                if is_planning_context_snapshot(run_id=run.run_id, reference=reference,
                        step_id=owner, kind=kind, operation_id=operation_id,
                        payload=decode_body(
                            connection, run_id=run.run_id, reference=reference, encoded=snapshot_body)
                            if snapshot_body is not None else None):
                    # A sealed diagnostic copy of an internal input is not a
                    # second model/tool admission. Original WALs remain visible.
                    continue
                raise ValueError('native session has admitted model or tool work')
            return {'source': 'formal-workspace-write-ahead.v1',
                    'identity': dict(runId=run.run_id, stepId=node.step_id, attemptId=node.attempt_id,
                                    commitId=node.operation_id),
                    'operationKey': operation, 'capabilityId': tool,
                    'workspaceId': workspace['workspaceId'], 'grantId': workspace['grantId'], 'dispatched': False}
        for suffix in (':request', ':admission', ':receipt', ':result', ':unsettled'):
            reference = 'tool:' + hashlib.sha256((run.run_id + ':' + operation + suffix).encode()).hexdigest()
            if connection.execute('SELECT 1 FROM execution_values WHERE reference=?', (reference,)).fetchone():
                raise ValueError('tool was admitted or dispatched; explicit side-effect reconciliation required')
        return {'source': 'formal-workspace-write-ahead.v1',
                'identity': dict(runId=run.run_id, stepId=node.step_id, attemptId=node.attempt_id,
                                 commitId=node.operation_id),
                'operationKey': operation, 'capabilityId': tool,
                'declarationHash': stable_checksum({'tool': tool, 'arguments': raw_arguments}),
                'workspaceId': workspace['workspaceId'], 'grantId': workspace['grantId'], 'dispatched': False}

    async def verified_observations(self, context):
        """Verify only receipt references delivered by this node's ContextPack.

        This consumes existing evidence; it grants no filesystem or Shell tool
        to the verification/synthesis agent and never scans another node's data.
        """
        from adapters.tool.hands_http import receipt_checksum
        found = {}
        def visit(value):
            if isinstance(value,dict):
                if value.get('receiptRef') and value.get('receiptChecksum'):
                    found[value['receiptRef']] = value
                for child in value.values(): visit(child)
            elif isinstance(value,list):
                for child in value: visit(child)
        visit(getattr(context.context_pack,'data',{}))
        if not found:
            return []
        if self.context is not context or self.guard is None:
            raise PermissionError('Bound NodeRunner context required for receipt verification')
        self.guard()
        observations=[]
        for ref,record in found.items():
            receipt=self.runtime.execution_value_store.get_output(run_id=context.run.run_id,output_ref=ref)
            if receipt_checksum(receipt)!=record['receiptChecksum'] or receipt['checksum']!=record['receiptChecksum']:
                raise RuntimeError('HANDS_EVIDENCE_CHECKSUM_MISMATCH')
            identity=receipt.get('identity',{})
            if identity.get('runId')!=context.run.run_id or any(identity.get(k)!=record.get(k) for k in ['stepId','attemptId','commitId']):
                raise RuntimeError('HANDS_EVIDENCE_IDENTITY_MISMATCH')
            observations.append({'kind':'hands_execution_receipt','executionId':record['executionId'],
                'receiptRef':ref,'receiptChecksum':receipt['checksum'],'content':receipt})
        return observations

    async def previous_attempt_observations(self, context):
        """Read admitted retry evidence through the same bound tool authority."""
        if self.context is not context or self.guard is None:
            raise PermissionError('Bound NodeRunner context required for retry evidence')
        self.guard()
        from runtime.orchestration.permit_recovery import settled_retry_observations
        return settled_retry_observations(self.runtime, context.run, context.step.step_id)

    async def _execute_retrieval(self, name, arguments, **kwargs):
        from app.tools.catalog import ReadOnlyToolCatalog
        from app.tools.contracts import ToolRunResult
        from app.tools.runtime import AgentsToolRuntime

        # Only the built-in, read-only catalog earns this ledger protocol.
        fallback = self.fallback
        if (type(fallback) is not AgentsToolRuntime or 'execute' in vars(fallback)
                or type(fallback.catalog) is not ReadOnlyToolCatalog or 'execute' in vars(fallback.catalog)):
            return await fallback.execute(name, arguments, **kwargs)
        context = self.context
        if self.guard is not None:
            try:
                self.guard()
            except Exception as exc:
                raise ToolExecutionAuthorizationLost('Retrieval no longer owns its execution authority') from exc
        identity = dict(runId=context.run.run_id, stepId=context.step.step_id,
                        attemptId=context.attempt_id, commitId=context.commit_id)
        if not all(identity.values()):
            return await fallback.execute(name, arguments, **kwargs)
        key = retrieval_operation_key(context.commit_id, name)
        store = self.runtime.execution_value_store
        request = {"version": RETRIEVAL_LEDGER_VERSION, "identity": identity, "tool": name,
                   "callHash": stable_checksum({"arguments": arguments, "options": kwargs})}
        ownership = dict(run_id=context.run.run_id, step_id=context.step.step_id)
        store.put_tool_value(**ownership, key=key + ':request', payload=request)
        cached = store.get_tool_value(run_id=context.run.run_id, key=key + ':result')
        if cached is not None:
            result = ToolRunResult.model_validate(cached['result'])
            if cached != self._retrieval_result(request, result):
                raise ValueError('retrieval replay result does not match its request')
            return result
        result = await fallback.execute(name, arguments, **kwargs)
        store.put_tool_value(**ownership, key=key + ':result', payload=self._retrieval_result(request, result))
        return result

    @staticmethod
    def _retrieval_result(request, result):
        payload = result.model_dump(by_alias=True, mode='json')
        return {"identity": request['identity'], "retrievalRequestHash": stable_checksum(request),
                "resultHash": stable_checksum(payload), "result": payload}

    async def execute(self, name, arguments, *, operation_key=None, **kwargs):
        requested_name = name
        definition = self.describe(name)
        if definition is not None:
            validate_contract_payload(arguments, definition.parameters, step_id='hands', direction='input')
            if name == 'shell.exec' and 'runner' in arguments:
                name = 'run_tests'
            elif name != 'shell.exec':
                name = next(alias for alias, capability in TOOLS.items() if capability == name)
        if name not in TOOLS and name != 'shell.exec':
            context = self.context
            if (context is not None and context.step.capability == 'information_retrieval'
                    and context.commit_id and name in RETRIEVAL_COMMIT_SUFFIXES
                    and kwargs.get('commit_id') == context.commit_id + RETRIEVAL_COMMIT_SUFFIXES[name]):
                return await self._execute_retrieval(name, arguments, **kwargs)
            return await self.fallback.execute(name,arguments,**kwargs)
        context,rt = self.context,self.runtime
        if context is None or self.guard is None or not operation_key: raise PermissionError('Formal NodeRunner authority required')
        self.guard()
        authority = getattr(rt, 'workspace_authority', None)
        authorization = authority.resolve(context.run) if authority else rt.local_runtime_authorization
        fields = definition.parameters['properties'] if definition else FIELDS[name]
        if set(arguments)-set(fields): raise PermissionError('Tool input cannot declare host authority')
        path = normalize_relative_path(arguments.get('workdir','.') if name=='shell.exec' else arguments.get('path'))
        if path is None: raise PermissionError('Workspace relative path required')
        data = dict(arguments,path=path)
        approval_name = name
        approval_data = data
        if name == 'shell.exec':
            data = dict(arguments, workdir=path)
            approval_name,approval_data = 'run_command',{'command':arguments['command'],'cwd':path}
        elif name == 'run_tests':
            # Managed test command, not a model-supplied security profile or executable.
            if any(c in path for c in "'\"`\n\r") or path.startswith('-'): raise PermissionError('Invalid test path')
            runner = arguments.get('runner', 'pytest')
            if runner == 'pytest':
                executable = os.environ['AGENTOS_WORKSPACE_TEST_PYTHON']
                argv = ['-m', 'pytest', '-q', path]
            elif runner == 'node':
                executable = os.environ['AGENTOS_WORKSPACE_TEST_NODE']
                argv = ['--test'] + ([] if path == '.' else [path])
            elif runner == 'npm-test':
                if path != '.': raise PermissionError('npm-test runs only the authorized project test script')
                executable = os.environ['AGENTOS_WORKSPACE_TEST_NPM']
                argv = ['test']
            else: raise PermissionError('Unconfigured test runner')
            if not os.path.isabs(executable) or not os.path.isfile(executable):
                raise PermissionError('Trusted test executable unavailable')
            quote = lambda value: "'" + value.replace("'", "''") + "'"
            command = '& ' + ' '.join(quote(v) for v in [executable, *argv])
            data = {'command':command,'workdir':'.', 'executable': executable, 'argv': argv}
            approval_name,approval_data = 'run_command',{'command':command,'cwd':'.'}
        elif name == 'patch_file':
            approval_data = {'path':path}
        run_id,step_id = context.run.run_id,context.step.step_id
        identity = dict(runId=run_id,stepId=step_id,attemptId=context.attempt_id,commitId=context.commit_id)
        if not all(identity.values()): raise PermissionError('Frozen execution identity required')
        previous = rt.execution_value_store.get_tool_value(run_id=run_id, key=operation_key+':request')
        cached = rt.execution_value_store.get_tool_value(run_id=run_id, key=operation_key+':result')
        if previous is not None and cached is None:
            # Reuse the existing Hands service's durable idempotency admission,
            # never a new operation key. A changed node attempt/input/grant must
            # be reconciled rather than replayed as a different external action.
            prior_request = previous['request']
            if (previous['identity'] != identity or prior_request['input'] != data
                or prior_request['capabilityId'] != TOOLS.get(name,name)
                or prior_request['authorization'] != authorization.model_dump(by_alias=True,mode='json')):
                raise HandsOutcomeUnknown('Frozen Hands request must be reconciled before changing identity')
        if cached is not None:
            record = cached['record']
            if (previous['request']['input'] != data or previous['request']['capabilityId'] != TOOLS.get(name,name)
                or any(record.get(field) != identity[field] for field in ('runId','stepId','commitId'))
                or record.get('grantId') != authorization.grant_id or record.get('workspaceId') != authorization.workspace_id):
                raise PermissionError('Tool replay must retain its frozen input and workspace authority')
            return ToolExecutionResult(data=cached['data'], record=record)
        approval_ids = set()
        async def emit(kind,payload):
            if kind == 'hands_event' and payload.get('executionId'):
                rt.execution_value_store.put_tool_value(run_id=run_id,step_id=step_id,
                    key=operation_key+':admission',payload={'executionId':payload['executionId'],**identity})
            approval = payload.get('approval')
            if approval:
                approval_id = approval['approvalId']
                if kind == 'approval_required':
                    approval_ids.add(approval_id)
                    rt.formal_tool_pending[approval_id] = approval
                else:
                    rt.formal_tool_pending.pop(approval_id, None)
                    approval_ids.discard(approval_id)
            await runtime_event_broker.publish(run_id,RuntimeEvent(eventType='tool.'+kind,runId=run_id,
                nodeId=step_id,attemptId=context.attempt_id,sequence=0,payload={**payload,
                    'operationKey':operation_key,
                    'target':str(approval_data.get('path') or approval_data.get('command') or approval_data.get('cwd') or '')[:512]}))
        coordinator = TaskApprovalCoordinator(rt, self.permissions)
        approval_context = coordinator.bind_context(context, self.guard, authorization)
        outcome_unknown = False
        tool_failure = dict(identity, tool=TOOLS.get(name, name), operationKey=operation_key,
                            resourceId=rt.local_runtime_resource.profile.runtime_id)
        async def cleanup():
            try:
                await keepalive.stop()
            finally:
                if not outcome_unknown:
                    rt.resource_binder.release(scheduled.lease.lease_id)

        while True:
            approval_decision = previous.get('approvalDecision') if previous else None
            if previous is None:
                try:
                    with human_approval_wait():
                        approval_decision = await self.permissions.authorize(
                            tool_name=approval_name, arguments=approval_data, call_id=operation_key,
                            session_id=run_id, workspace_id=authorization.workspace_id, emit=emit,
                            trusted_context=approval_context,
                            automatic_decision=lambda: coordinator.automatic_decision(approval_context))
                finally:
                    for approval_id in tuple(approval_ids):
                        approval = rt.formal_tool_pending.get(approval_id)
                        if approval:
                            await emit('approval_resolved', {'approval': {**approval, 'status': 'cancelled'}})
            async def prepare_allocation():
                nonlocal authorization
                self.guard()  # Approval or capacity waits may outlive the permit.
                if authority: authorization = authority.resolve(context.run)
                healthy = await rt.local_runtime_health_projector.refresh(rt.local_runtime_transport)
                self.guard()
                if not healthy:
                    profile = rt.resource_plane.runtime(rt.local_runtime_resource.profile.runtime_id)
                    reasons = [FilterReason.UNHEALTHY]
                    if not profile.enabled: reasons.append(FilterReason.DISABLED)
                    if profile.draining: reasons.append(FilterReason.DRAINING)
                    return ReadyNodeSchedulingResult(
                        status='queued' if profile.enabled and not profile.draining else 'rejected',
                        reason='EXECUTION_RESOURCE_UNAVAILABLE', candidates=[CandidateDecision(
                            resourceId=profile.runtime_id, accepted=False, reasons=reasons)])

            # Every tool operation receives its own terminal capacity lease.
            # Contention belongs to the scheduler, not the Agent's reasoning or
            # failure path. Admission still revalidates approval after waiting.
            try:
                scheduled = await rt.resource_binder.wait_ready(run_id=run_id,step_id=step_id,
                    attempt_id=f'{context.attempt_id}:tool:{operation_key}:lease:{uuid4().hex}',
                    requirement=ExecutionRequirement(requiredCapabilities=[TOOLS.get(name,name)],runtimeKinds=[RuntimeKind.EXECUTION_BACKEND],
                        allowedRuntimeIds=[rt.local_runtime_resource.profile.runtime_id]),
                    before_attempt=prepare_allocation,
                    on_queued=lambda decision: emit('capacity_waiting', {'tool': requested_name, 'reason': decision.reason}))
            except Exception as exc:
                code = getattr(exc, 'code', None)
                if code not in HOST_TOOL_FAILURE_CODES:
                    raise
                if isinstance(exc, ToolExecutionAuthorizationLost):
                    exc.details = {**tool_failure, 'phase':'tool_scheduling'}
                    raise
                raise HostToolExecutionError(code, 'Hands tool admission failed',
                    retryable=code == 'SCHEDULER_UNAVAILABLE',
                    details={**tool_failure, 'phase':'tool_scheduling'}) from exc
            if scheduled.binding is None or scheduled.lease is None:
                code = ('EXECUTION_CAPACITY_UNAVAILABLE' if scheduled.reason == 'NO_CAPACITY'
                        else scheduled.reason or 'NO_ELIGIBLE_RESOURCE')
                raise HostToolExecutionError(code, 'Hands tool resource is unavailable',
                    details={**tool_failure, 'phase': 'tool_scheduling', 'schedulingReason': scheduled.reason,
                        'candidateReasons': [{'resourceId': c.resource_id, 'reasons': [r.value for r in c.reasons]}
                                             for c in scheduled.candidates]})
            keepalive = LeaseKeepAlive(rt.resource_binder.coordinator,scheduled.lease)
            try:
                keepalive.start()
                request = LocalRuntimeExecutionRequest(protocolVersion='1',requestId=operation_key,invocationId=operation_key,
                    resourceId=scheduled.binding.resource_id,capabilityId=TOOLS.get(name,name),authorization=authorization,
                    input=data,limits=LocalRuntimeExecutionLimits(timeoutSeconds=90,maxStdoutBytes=64000,maxStderrBytes=32000),
                    idempotencyKey=operation_key)
                payload = {'request': request.model_dump(by_alias=True, mode='json'), 'identity': identity}
                if approval_decision:
                    payload['approvalDecision'] = approval_decision
                if previous is not None:
                    # A durable request already passed admission. Preserve its
                    # original authorization even after the policy is disabled.
                    if payload != previous:
                        raise HandsOutcomeUnknown('Frozen Hands request changed during replay')
                    request_ref = rt.execution_value_store.put_tool_value(run_id=run_id,step_id=step_id,
                        key=operation_key+':request',payload=previous)
                else:
                    request_ref = coordinator.admit(context=approval_context,
                        approval_decision=approval_decision,resource_id=scheduled.binding.resource_id,
                        commit=lambda: rt.execution_value_store.put_tool_value(run_id=run_id,step_id=step_id,
                            key=operation_key+':request',payload=payload))
            except BaseException as exc:
                await await_settled(asyncio.create_task(cleanup(), name=f'hands-lease-cleanup:{operation_key}'))
                if isinstance(exc, ApprovalPolicyChanged):
                    continue
                raise
            break
        try:
            self.guard()
            if authority: authority.resolve(context.run)
            await emit('execution_started',{'tool':requested_name,'bindingId':scheduled.binding.binding_id,**identity})
            cancellation = None
            try:
                result = await rt.local_runtime_transport.execute_with_identity(request,identity,
                    event_sink=lambda event: emit('hands_event',event))
            except HandsExecutionCancelled as exc:
                cancellation, result = exc, exc.result
            receipt = result.output.get('handsReceipt')
            if not receipt: raise RuntimeError('Verified Hands receipt required before node completion')
            ref = rt.execution_value_store.put_tool_value(run_id=run_id,step_id=step_id,key=operation_key+':receipt',payload=receipt)
            record = {'tool':requested_name,'status':result.status,'executionId':result.output['executionId'],
                'receiptChecksum':receipt['checksum'],'receiptRef':ref,'resourceId':scheduled.binding.resource_id,
                'bindingId':scheduled.binding.binding_id,'requestRef':request_ref,**identity}
            record['workspaceId'] = authorization.workspace_id
            record['grantId'] = authorization.grant_id
            if approval_decision: record['approvalDecision'] = approval_decision
            if name == 'run_tests': record['managedTest'] = True
            # Bounded display projection; receipts and authorization remain owned
            # by the execution ledger, not by the transcript.
            preview = {key: result.output[key] for key in ('text', 'content', 'entries', 'stdout', 'stderr', 'exitCode')
                       if key in result.output}
            await emit('execution_completed',{**record,
                'resultPreview': json.dumps(preview, ensure_ascii=False, default=str)[:4096] if preview else ''})
            if cancellation is not None:
                raise cancellation
            # Drain a renewal already in flight before declaring/cacheing success.
            await keepalive.stop()
            if keepalive.failure: raise HandsOutcomeUnknown('Hands lease renewal failed; reconcile before retry')
            data = dict(result.output, status=result.status)
            if result.error: data['error'] = result.error.model_dump(mode='json')
            rt.execution_value_store.put_tool_value(run_id=run_id,step_id=step_id,
                key=operation_key+':result',payload={'data':data,'record':record})
            return ToolExecutionResult(data=data,record=record)
        except HandsOutcomeUnknown as exc:
            # Transport uncertainty for trusted read-only tools affects this
            # operation. Integrity faults and unknown side effects affect the
            # runtime. Neither case fabricates a terminal receipt or result.
            outcome_unknown = not (TOOLS.get(name, name) in {'fs.read', 'fs.list'}
                and exc.reconciliation_reason == 'transport_unavailable' and exc.quarantine_scope == 'operation')
            exc.details = {**tool_failure, 'phase': 'tool_settlement'}
            if outcome_unknown:
                rt.resource_plane.set_runtime_health(scheduled.binding.resource_id, healthy=False)
                rt.resource_plane.set_runtime_enabled(scheduled.binding.resource_id, enabled=False)
            rt.execution_value_store.put_tool_value(run_id=run_id,step_id=step_id,key=operation_key+':unsettled',
                payload={'leaseId':scheduled.lease.lease_id,'resourceId':scheduled.binding.resource_id,
                         'reason':'external_outcome_unknown', 'reconciliationReason':exc.reconciliation_reason,
                         'quarantineScope':'runtime' if outcome_unknown else 'operation', **identity})
            raise
        finally:
            await await_settled(asyncio.create_task(cleanup(), name=f"hands-lease-cleanup:{operation_key}"))


_FORMAL_WRITE_AHEAD_BOUNDARY = tuple((name, getattr(FormalWorkspaceTools, name))
    for name in ('execute', '_execute_retrieval', 'describe', 'list_tools', 'bind_context', 'scoped'))
_SQLITE_TOOL_WRITE_AHEAD = SQLiteExecutionValueStore.put_tool_value
