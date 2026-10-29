"""Hands asynchronous capability transport over the existing resource HMAC.

202 is admission only. A receipt is returned only after polling, correlation and
checksum validation. UNKNOWN/network ambiguity is non-retryable to the Agent.
"""
import asyncio
import hashlib
import json
from uuid import uuid5, NAMESPACE_URL

from adapters.local_runtime_http import HttpLocalRuntimeTransport
from contracts.local_runtime import LocalRuntimeExecutionResult, LocalRuntimeExecutionError


class HandsOutcomeUnknown(RuntimeError):
    code = 'HANDS_OUTCOME_UNKNOWN'
    retryable = False


class HandsAdmissionRejected(RuntimeError):
    """A definite protocol/auth/grant rejection, never an uncertain execution."""
    retryable = False

    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__('Hands operation rejected: '+code)


def receipt_checksum(receipt):
    data = {key:value for key,value in receipt.items() if key != 'checksum'}
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


class HandsHttpTransport(HttpLocalRuntimeTransport):
    async def health(self):
        response = await self._client.get(self.address.rsplit('/v1/executions',1)[0]+'/v1/health',timeout=5)
        response.raise_for_status()
        raw = response.json()
        profile = self.credential_provider.runtime(self.resource_id)
        supported = set(raw.get('capabilities',[]))
        return {'protocolVersion':'1','resourceId':self.resource_id,'status':'online' if raw.get('ok') else 'offline',
                'capabilities':[c for c in profile.capabilities if c in supported],
                'availableSlots':profile.capacity,'utilization':0.0}
    async def _call(self, method, suffix='', payload=None, key=None):
        body = b'' if payload is None else json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        path = self._path + suffix
        headers = self._signed_headers(method=method,path=path,body=body,idempotency_key=key)
        response = await self._client.request(method,self.address+suffix,headers=headers,content=body,timeout=15)
        if response.status_code not in (200,202):
            if response.status_code in (400,401,403,404,409,422):
                try: code = response.json()['error']['code']
                except (ValueError,KeyError,TypeError): code = 'HANDS_HTTP_'+str(response.status_code)
                raise HandsAdmissionRejected(response.status_code, str(code))
            raise HandsOutcomeUnknown('Hands rejected a signed operation: '+str(response.status_code))
        return response.json()

    async def execute(self, request):
        return await self.execute_with_identity(request, {})

    async def execute_with_identity(self, request, identity, event_sink=None):
        wire = request.model_dump(by_alias=True,mode='json')
        wire.pop('resourceId')  # Hands is already selected by the signed endpoint.
        wire['requestId'] = str(uuid5(NAMESPACE_URL,request.idempotency_key))
        if identity: wire['identity'] = dict(identity)
        if request.capability_id.value == 'fs.patch':
            data = wire['input']
            if 'old_text' in data: data['oldText'] = data.pop('old_text')
            if 'new_text' in data: data['newText'] = data.pop('new_text')
        execution_id = None
        try:
            record = await self._call('POST',payload=wire,key=request.idempotency_key)
            execution_id = record['executionId']
            cursor = -1
            deadline = asyncio.get_running_loop().time()+request.limits.timeout_seconds+30
            while record['state'] not in {'COMPLETED','FAILED','CANCELLED','UNKNOWN'}:
                if asyncio.get_running_loop().time() > deadline:
                    await self._call('POST','/'+execution_id+'/cancel',{'executionId':execution_id})
                    raise HandsOutcomeUnknown('Hands deadline reached; cancellation requested, reconciliation required')
                if event_sink:
                    events = await self._call('GET','/'+execution_id+'/events?afterSequence='+str(cursor))
                    for event in events['events']:
                        cursor = max(cursor,int(event['seq']))
                        await event_sink(event)
                await asyncio.sleep(.15)
                record = await self._call('GET','/'+execution_id)
            if event_sink:
                events = await self._call('GET','/'+execution_id+'/events?afterSequence='+str(cursor))
                for event in events['events']:
                    await event_sink(event)
            if record['state'] == 'UNKNOWN':
                raise HandsOutcomeUnknown('Hands execution '+execution_id+' is UNKNOWN; automatic replay forbidden')
            receipt = record.get('receipt')
            if not receipt or receipt_checksum(receipt) != receipt['checksum']:
                raise HandsOutcomeUnknown('Hands terminal receipt is missing or invalid')
            if any(receipt.get(key) != wire.get(key) for key in ['requestId','invocationId','capabilityId','idempotencyKey']):
                raise HandsOutcomeUnknown('Hands receipt correlation mismatch')
            if receipt.get('identity',{}) != identity or receipt['grantId'] != request.authorization.grant_id:
                raise HandsOutcomeUnknown('Hands receipt authority/identity mismatch')
            expected = {'COMPLETED':'completed','FAILED':'failed','CANCELLED':'cancelled'}[record['state']]
            if receipt['status'] != expected: raise HandsOutcomeUnknown('Hands state and receipt disagree')
            output = dict(receipt.get('output') or {})
            if request.capability_id.value == 'fs.read' and 'text' in output:
                output['content'] = output['text']  # Hands wire -> AgentOS file-tool observation.
            for channel in ('stdout','stderr'):
                if isinstance(output.get(channel),dict):
                    stream = output[channel]
                    output[channel] = stream.get('text','')
                    output[channel+'Truncated'] = bool(stream.get('truncated',False))
            output.update(executionId=execution_id,receiptChecksum=receipt['checksum'],handsReceipt=receipt)
            failure = None
            if expected in {'failed','cancelled'}:
                error = receipt.get('error') or {'code':'HANDS_CANCELLED','retryable':False,'message':'cancelled'}
                failure = LocalRuntimeExecutionError(**error)
                expected = 'failed'
            return LocalRuntimeExecutionResult(requestId=request.request_id,invocationId=request.invocation_id,
                status=expected,output=output,error=failure,startedAt=receipt['startedAt'],completedAt=receipt['completedAt'])
        except asyncio.CancelledError:
            if execution_id:
                await asyncio.shield(self._call('POST','/'+execution_id+'/cancel',{'executionId':execution_id}))
            raise
        except HandsOutcomeUnknown:
            raise
        except HandsAdmissionRejected:
            if execution_id is not None:
                raise HandsOutcomeUnknown('Admitted Hands execution cannot be reconciled; automatic replay forbidden')
            raise
        except Exception as exc:
            raise HandsOutcomeUnknown('Hands transport outcome requires reconciliation; no automatic replay') from exc

    async def query_execution(self, execution_id):
        return await self._call('GET','/'+execution_id)

    async def workspace_root(self, authorization):
        response = await self._client.get(self.address.rsplit('/v1/executions',1)[0]+'/v1/health',timeout=5)
        response.raise_for_status()
        return response.json()['workspaceRoot']
