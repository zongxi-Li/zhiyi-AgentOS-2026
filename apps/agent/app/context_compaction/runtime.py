"""Thin request-scoped bridge to the independent TypeScript engine.

No algorithm duplication: this host supplies budget/Provider adapters and returns
SDK ModelInputData. Child processes never receive API credentials or run tools.
"""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
import json
import logging
import os
from pathlib import Path
import shutil
import time

logger = logging.getLogger(__name__)
WORKER = Path(__file__).resolve().parents[3] / "agentOS" / "src" / "oscode-context" / "src" / "worker.ts"


class CompactionBridgeError(RuntimeError):
    def __init__(self, message, code='COMPACTION_BRIDGE_FAILED'):
        super().__init__(message)
        self.code = code


def _wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _upper_bound(messages, instructions, tools):
    def images(value):
        if isinstance(value, dict):
            return int(value.get("type") in {"input_image", "image_url", "image"}) + sum(images(v) for v in value.values())
        return sum(images(v) for v in value) if isinstance(value, list) else 0
    return (len(instructions.encode("utf8")) + (len(_wire(tools).encode("utf8")) if tools else 0) + 64
            + sum(len(_wire(m).encode("utf8")) + 24 + images(m) * 8192 for m in messages))


def model_input_tools(agent):
    return [{"type": "function", "name": t.name, "description": t.description,
             "parameters": t.params_json_schema, "strict": t.strict_json_schema}
            for t in agent.tools if hasattr(t, "params_json_schema")]


def context_budget_metadata(agent):
    """Fixed allowance for the next text-history input, separate from Provider usage."""
    return {"contextFixedTokens": _upper_bound([], agent.instructions or "", model_input_tools(agent)),
            "contextTokenMethod": "utf8-upper-bound"}


class TypeScriptInputFilter:
    def __init__(self, *, context_id, model, base_url, api_key, budget, config, tools, tokenizer=None, node="", invoke=None, session=None, notify=None, measure_only=False):
        self.context_id, self.model, self.base_url, self.api_key = context_id, model, base_url, api_key
        self.budget, self.config, self.tools, self.tokenizer = budget, config, tools, tokenizer
        self.node, self.invoke = node, invoke
        self.process = None
        self.last_metrics = None
        self._lock = asyncio.Lock()
        self.session, self.notify = session, notify
        self._overlay_source = self._overlay_result = None
        self.anchor = None
        self.sent_basis = None
        self.summary_calls = 0
        self.context_usage = None
        self._response_measured = False
        self.measure_only = measure_only

    def fixed_hash(self, instructions):
        return hashlib.sha256(_wire([self.base_url.rstrip('/'), self.model, instructions or '', self.tools]).encode()).hexdigest()

    def record_usage(self, usage):
        # A single response's prompt usage, never the accumulated Runner usage.
        prompt = getattr(usage, 'prompt_tokens', None)
        if type(prompt) is not int or prompt <= 0 or not self.sent_basis:
            return None
        self.record_input_tokens(prompt)
        self._response_measured = True
        if self.anchor:
            output = getattr(usage, 'completion_tokens', 0)
            output = output if type(output) is int and output >= 0 else 0
            self.anchor['outputTokens'] = output
            self.context_usage = self._usage(self.anchor['inputTokens'] + output, 'provider', 'model')
            self.anchor['watermark'] = self.context_usage
        return self.context_usage

    def _usage(self, used, measurement, source):
        confirmed = (self.anchor or {}).get('watermark', {}).get('confirmedTokens')
        if measurement == 'provider':
            confirmed = used
        return {'usedTokens': used, 'maxTokens': self.budget['contextWindow'],
                'measurement': measurement, 'source': source,
                **({'confirmedTokens': confirmed} if confirmed is not None else {})}

    def measure_input(self, data):
        measured = _upper_bound(data.input, data.instructions or '', self.tools)
        method = 'utf8-upper-bound'
        anchor = self.anchor or (self.session.last_view.metadata.get('_usageAnchor')
                                 if self.session and self.session.last_view else None)
        if anchor and anchor.get('fixedHash') == self.fixed_hash(data.instructions):
            count = anchor.get('count')
            if (type(count) is int and 0 < count <= len(data.input) and type(anchor.get('inputTokens')) is int
                    and hashlib.sha256(_wire(data.input[:count]).encode()).hexdigest() == anchor.get('prefixHash')):
                covered, base = count, anchor['inputTokens']
                response_count = anchor.get('responseCount', 0)
                if (type(response_count) is int and response_count > 0
                        and hashlib.sha256(_wire(data.input[count:count+response_count]).encode()).hexdigest() == anchor.get('responseHash')):
                    covered += response_count
                    base += anchor.get('outputTokens', 0)
                measured = base + _upper_bound(data.input[covered:], '', []) - 64
                method = 'single-request-usage+utf8-delta-upper-bound'
                self.anchor = anchor
        return measured, method

    async def record_response(self, response):
        if not self._response_measured:
            from types import SimpleNamespace
            usage = getattr(response, 'usage', None)
            state = self.record_usage(SimpleNamespace(prompt_tokens=getattr(usage, 'input_tokens', None),
                completion_tokens=getattr(usage, 'output_tokens', 0)))
            if state and self.notify:
                self.notify('model_context', {'contextUsage': state})
        if not self.anchor or not self._response_measured:
            return
        # SDK 自己负责 output -> replay input 的协议转换，不另建一套消息规范。
        from agents.models.interface import ModelResponse
        from agents.usage import Usage
        replay = ModelResponse(response.output, Usage(), response.id).to_input_items()
        self.anchor.update(responseCount=len(replay), responseHash=hashlib.sha256(_wire(replay).encode()).hexdigest())
        await self.save_usage_anchor()

    def record_input_tokens(self, count):
        if type(count) is int and count > 0 and self.sent_basis:
            self.anchor = {**self.sent_basis, 'inputTokens': count}
            if self.last_metrics:
                self.last_metrics = {**self.last_metrics, 'actualInputTokens': count}

    async def save_usage_anchor(self):
        if self.anchor and self.session and self.session.last_view:
            try:
                await asyncio.to_thread(self.session.projection_store.save_anchor, self.anchor, self.session.last_view.epoch)
            except Exception as error:
                logger.warning('oscode_usage_anchor_not_saved type=%s', type(error).__name__)

    def report(self, phase, **data):
        if self.notify:
            self.notify('model_phase', {'phase': phase, **data})

    async def _send(self, value):
        if self.process is None or self.process.stdin is None:
            raise CompactionBridgeError("Compaction worker is not running")
        self.process.stdin.write((_wire(value) + "\n").encode("utf8"))
        await self.process.stdin.drain()

    async def __call__(self, call):
        from agents.run import ModelInputData
        source = call.model_data.input
        data = call.model_data
        if self._overlay_source and _wire(source[:len(self._overlay_source)]) == _wire(self._overlay_source):
            data = ModelInputData(input=self._overlay_result + source[len(self._overlay_source):], instructions=data.instructions)
        # With a committed projection, soft-pressure summaries can wait for idle.
        # First migration and hard overflow remain explicitly cancellable preparation.
        warm = self.session and self.session.last_view and self.session.last_view.metadata.get('projectionVersion')
        hard = self.budget['contextWindow'] - self.budget['outputReserve'] - self.budget['safetyMargin']
        measured, _ = self.measure_input(data)
        result = await self.project(data, local_only=bool(warm and measured <= hard))
        self.sent_basis = {'count': len(result.input), 'prefixHash': hashlib.sha256(_wire(result.input).encode()).hexdigest(),
                           'fixedHash': self.fixed_hash(result.instructions)}
        self._response_measured = False
        if _wire(source) != _wire(result.input):
            self._overlay_source, self._overlay_result = source, result.input
            if self.session:
                self.session.pending_projection = (source, result.input, self.last_metrics or {})
        return result

    async def project(self, data, *, force=False, local_only=False):
        from agents.run import ModelInputData
        # Cheap UTF-8 upper bound admits short input without spawning a process,
        # loading tokenizers or making any auxiliary Provider call.
        limit = self.budget["contextWindow"] - self.budget["outputReserve"] - self.budget["safetyMargin"]
        started = time.perf_counter()
        measured, method = self.measure_input(data)
        self.context_usage = self._usage(measured if method.startswith('single-request') else None,
                                        'upper-bound' if method.startswith('single-request') else 'unknown', 'prepared')
        self.report('context_measured', contextUsage=self.context_usage)
        threshold = min(int(limit * self.config.get('triggerRatio', .85)), self.budget.get('workingSetTriggerTokens', limit))
        if not force and (self.measure_only or measured < threshold):
            self.last_metrics = {'status': 'unchanged', 'inputTokens': measured, 'outputTokens': measured,
                'tokenMethod': method, 'hardInputLimit': limit,
                'workingSetTriggerTokens': threshold,
                'workingSetTargetTokens': min(int(limit * self.config.get('targetRatio', .65)), self.budget.get('workingSetTargetTokens', limit)),
                'softOverBudget': measured >= threshold, 'summaryCalls': 0}
            self.last_metrics['contextUsage'] = self.context_usage
            self.report('context_ready', workingContext=self.last_metrics,
                        responseTimings={'contextMeasureMs': round((time.perf_counter() - started) * 1000)})
            return data
        self.report('context_pruning')
        async with self._lock:
            source_hash = hashlib.sha256(_wire(data.input).encode('utf8')).digest()
            try:
                async with asyncio.timeout(120):
                    if self.process is None:
                        executable = self.node or shutil.which("node")
                        if not executable:
                            raise CompactionBridgeError("Node >=24.9 is required when OScode compaction is enabled")
                        # Do not inherit .env, provider keys or service credentials.
                        child_env = {key: value for key, value in os.environ.items()
                                     if key.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "WINDIR"}}
                        self.process = await asyncio.create_subprocess_exec(
                            executable, str(WORKER), stdin=asyncio.subprocess.PIPE,
                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                            env=child_env, limit=32 * 1024 * 1024)
                    await self._send({"type": "project", "request": {
                        "contextId": self.context_id, "provider": self.base_url.rstrip("/"), "model": self.model,
                          "force": force, "localOnly": local_only,
                          **({'sourceUsage': {'inputTokens': measured, 'sourceHash': source_hash.hex(), 'tokenMethod': method}}
                             if method.startswith('single-request') else {}),
                        'summaryCallsRemaining': max(0, self.config.get('maxSummaryCalls', 16) - self.summary_calls),
                        "messages": data.input, "instructions": data.instructions or "", "tools": self.tools,
                        "budget": self.budget}, "config": self.config, "tokenizer": self.tokenizer})
                    while True:
                        line = await self.process.stdout.readline()
                        if not line:
                            raise CompactionBridgeError("Compaction worker exited; original history retained")
                        reply = json.loads(line)
                        if reply.get("type") == "summarize":
                            self.report('context_summary')
                            self.summary_calls += 1
                            try:
                                from app.ai_engine.model_runtime import generate_with_runtime_model
                                from app.llm.capabilities import provider_model_capabilities
                                invoke = self.invoke or generate_with_runtime_model
                                parameters = {"max_tokens": reply["maxTokens"]}
                                if provider_model_capabilities(self.model, self.base_url).supports_json_object:
                                    parameters["response_format"] = {"type": "json_object"}
                                async with asyncio.timeout(45):
                                    summary = await invoke(text=reply["text"], context=[{"role": "system", "content": reply["instruction"]}],
                                                           model=self.model, base_url=self.base_url, api_key=self.api_key,
                                                           reasoning_effort="disabled", parameters=parameters)
                                await self._send({"type": "summary", "id": reply["id"], "result": {
                                    "text": summary["text"], "totalTokens": summary.get("total_tokens") or summary.get("tokens_used") or 0}})
                            except asyncio.CancelledError:
                                raise
                            except Exception as error:
                                logger.warning("oscode_context_summary_failed type=%s", type(error).__name__)
                                await self._send({"type": "summary", "id": reply["id"], "error": True})
                        elif reply.get("type") == "result":
                            if hashlib.sha256(_wire(data.input).encode('utf8')).digest() != source_hash:
                                raise CompactionBridgeError("Source history changed while summarizing")
                            result = reply["projection"]
                            self.last_metrics = {"status": result["status"], **result["metrics"]}
                            known = str(self.last_metrics.get('tokenMethod', '')).startswith('single-request')
                            self.context_usage = self._usage(self.last_metrics['outputTokens'] if known else None,
                                'upper-bound' if known else 'unknown',
                                'compaction' if result['status'] in {'pruned', 'summarized'} else 'prepared')
                            self.last_metrics['contextUsage'] = self.context_usage
                            self.report('context_ready', workingContext=self.last_metrics,
                                contextUsage=self.context_usage,
                                responseTimings={'contextProjectionMs': round((time.perf_counter() - started) * 1000),
                                                 'contextSummaryMs': result['metrics'].get('summaryLatencyMs', 0)})
                            log = logger.warning if result["metrics"].get("failed") else logger.info
                            log("oscode_context_compaction %s", _wire({"status": result["status"], **result["metrics"]}))
                            return ModelInputData(input=result["messages"], instructions=data.instructions)
                        else:
                            raise CompactionBridgeError("Compaction rejected input; original history retained", reply.get('code', 'COMPACTION_BRIDGE_FAILED'))
            except BaseException:
                await self.close()
                raise

    async def close(self):
        process, self.process = self.process, None
        if process is not None:
            if process.stdin:
                process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()


def build_input_filter(*, agent, context_id: str, model: str, base_url: str, api_key: str, model_policies=None, session=None, notify=None, measure_only=False):
    from app.config import settings
    from app.llm.capabilities import provider_model_capabilities
    policy = dict((model_policies or {}).get(f"{base_url.rstrip('/')}::{model}", {}))
    caps = provider_model_capabilities(model, base_url)
    window = policy.get("context_window", caps.context_window_tokens)
    reserve = getattr(agent.model_settings, "max_tokens", None) or policy.get("output_reserve", min(4096, caps.max_output_tokens or 4096))
    margin = policy.get("safety_margin", 1024)
    if (not isinstance(window, int) or isinstance(window, bool) or window < 1
            or not isinstance(reserve, int) or isinstance(reserve, bool) or reserve < 1
            or not isinstance(margin, int) or isinstance(margin, bool) or margin < 0
            or reserve + margin >= window):
        raise CompactionBridgeError("Configure a verified model-specific context window/output/safety budget")
    if caps.max_output_tokens and reserve > caps.max_output_tokens:
        raise CompactionBridgeError("Output reserve exceeds provider output maximum")
    names = {"trigger_ratio": "triggerRatio", "target_ratio": "targetRatio", "retain_turns": "retainTurns",
             "retain_ratio": "retainRatio", "summary_max_tokens": "summaryMaxTokens", "max_summary_calls": "maxSummaryCalls",
             "threshold_chars": "thresholdChars", "head_chars": "headChars", "tail_chars": "tailChars"}
    names.update({'recent_tool_groups': 'recentToolGroups', 'recent_tail_tokens': 'recentTailTokens'})
    config = {target: policy[source] for source, target in names.items() if source in policy}
    if policy.get('working_set_trigger_tokens'):
        config = {'recentToolGroups': 5, 'recentTailTokens': 14000, 'summaryMaxTokens': 4096,
                  'maxSummaryCalls': 2, **config}
        if type(config['maxSummaryCalls']) is not int or config['maxSummaryCalls'] < 1:
            raise CompactionBridgeError('Invalid summary call budget')
        config['maxSummaryCalls'] = min(2, config['maxSummaryCalls'])
    tools = model_input_tools(agent)
    tokenizer = None
    if policy.get("tokenizer_json") or policy.get("tokenizer_config"):
        if not policy.get("tokenizer_json") or not policy.get("tokenizer_config"):
            raise CompactionBridgeError("Tokenizer JSON and config must be configured together")
        tokenizer = {"json": policy["tokenizer_json"], "config": policy["tokenizer_config"]}
    agent.model_settings = replace(agent.model_settings, max_tokens=reserve)
    budget = {"contextWindow": window, "outputReserve": reserve, "safetyMargin": margin}
    for source, target in [('working_set_trigger_tokens', 'workingSetTriggerTokens'), ('working_set_target_tokens', 'workingSetTargetTokens')]:
        if source in policy:
            value = policy[source]
            if type(value) is not int or value < 1:
                raise CompactionBridgeError('Invalid working-set budget')
            budget[target] = value
    if budget.get('workingSetTargetTokens', 0) >= budget.get('workingSetTriggerTokens', window - reserve - margin):
        raise CompactionBridgeError('Invalid working-set hysteresis')
    return TypeScriptInputFilter(context_id=context_id, model=model, base_url=base_url, api_key=api_key,
                                 budget=budget,
                                 config=config, tools=tools, tokenizer=tokenizer,
                                 node=getattr(settings, "OSCODE_CONTEXT_COMPACTION_NODE", ""), session=session, notify=notify, measure_only=measure_only)
