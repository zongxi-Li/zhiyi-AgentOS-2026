"""定义核心拥有的启动配置及确定性本地执行能力。"""

from __future__ import annotations

import hashlib
import json
import logging
from copy import deepcopy
from typing import Any

from adapters.model_adapter import StructuredGenerationError
from service.agents.base import AgentOutput, AgentProfile, AgentRunContext, BaseAgent
from contracts.communication import (
    ContextContractError,
    apply_contract_defaults,
    compact_contract_text_arrays,
    validate_contract_payload,
)
from contracts.workflow import WorkflowDefinition, WorkflowDefinitionType, utc_now
from adapters.model.native_prompt import (
    NativeCapabilityPromptBuilder,
    prompt_version_for_capability,
)
from support.acg.models import NATIVE_CAPABILITY_IDS
from components.communicator.contracts import ContextPack, input_revision


NATIVE_ACG_WORKFLOW_ID = "native_acg_runtime_v1"
GENERAL_EVIDENCE_WORKFLOW_ID = "general_evidence_decision"
NATIVE_AGENT_NAME = "native_general_agent"

logger = logging.getLogger(__name__)


def _workset_recovery_bounded(context) -> bool:
    """判断该节点是否处于 workset 恢复边界之内。

    workset 分片单元的超限必须原样上抛给外层的确定性材料二分；内层语义
    子任务拆分在边界内截胡会把外层恢复链饿死（历史缺陷：空拆分直接终结）。
    """
    pack = getattr(context, "context_pack", None)
    data = getattr(pack, "data", None) or {}
    return str(data.get("recoveryBoundary") or "") == "workset"


def _requested_reasoning_effort(context: AgentRunContext) -> str | None:
    value = str(context.task.input.get("reasoningEffort") or "").strip()
    return value or None

# Backward-compatible export derived from the native Catalog contribution.
NATIVE_CAPABILITIES = NATIVE_CAPABILITY_IDS


class NativeGeneralAgent(BaseAgent):
    """执行原生启动能力的通用 Agent，并保持离线安全边界。

    它只根据运行时上下文、已注册能力和显式注入的模型/工具运行时工作；
    不直接访问供应商 SDK。模型不可用、工具结果非法或输出违反合同会以
    明确异常失败，而不会编造业务结果。
    """

    def __init__(self) -> None:
        super().__init__(
            AgentProfile(
                agentName=NATIVE_AGENT_NAME,
                domain="general",
                capabilities=list(NATIVE_CAPABILITY_IDS),
                capacity=4,
                allowedTools=[
                    "knowledge_search",
                    "current_datetime",
                ],
                description="Executes domain-neutral understanding, analysis, and artifact delivery.",
            )
        )
        self.prompt_builder = NativeCapabilityPromptBuilder()

    async def run(self, context: AgentRunContext) -> AgentOutput:
        """执行 ``context`` 所声明的一项能力并返回受合同约束的输出。

        信息检索能力仅经只读工具运行时取得证据；其余能力使用注入模型生成
        JSON，并至多进行一次解析或合同修复。成功时返回 ``AgentOutput``，
        缺少能力描述、模型、证据或得到非法结果时抛出结构化或运行时异常。
        该协程不保证并发调用间共享状态隔离，隔离责任由运行时提供。
        """
        objective = str(
            context.task.input.get("userIntent")
            or context.task.input.get("intent")
            or context.task.title
        ).strip()
        upstream = self._upstream_data(context)
        capability = (context.step.capability or "").strip()

        if context.content_workset_session is not None:
            return await self._run_workset(context)

        task_summary = str(upstream.get("task_summary") or objective)
        if capability == "information_retrieval":
            if context.tool_runtime is None:
                raise RuntimeError("read-only tool runtime is not configured")
            result = await context.tool_runtime.execute(
                "knowledge_search",
                {"query": task_summary[:500], "top_k": 5},
                commit_id=context.commit_id,
            )
            try:
                envelope = json.loads(result.text)
            except (TypeError, json.JSONDecodeError) as exc:
                raise RuntimeError("local knowledge search returned an invalid payload") from exc
            if not envelope.get("ok"):
                raise RuntimeError(
                    "local knowledge search failed: "
                    f"{envelope.get('error') or 'unknown error'}"
                )
            sources = [item.public_dict() for item in result.sources]
            evidence_refs = [item.citation_id for item in result.sources]
            retrieved_information = [
                str(item.get("snippet") or item.get("content") or "").strip()
                for item in ((envelope.get("data") or {}).get("results") or [])
                if isinstance(item, dict)
                and str(item.get("snippet") or item.get("content") or "").strip()
            ]
            if not evidence_refs:
                citation_id = "src_task_input_" + hashlib.sha256(
                    task_summary.encode("utf-8")
                ).hexdigest()[:16]
                sources = [{
                    "citationId": citation_id,
                    "title": "User-provided task facts (offline ACG)",
                    "filename": None,
                    "url": None,
                    "content": task_summary[:4000],
                    "provider": "task-input",
                    "retrievedAt": utc_now().isoformat(),
                }]
                evidence_refs = [citation_id]
                retrieved_information = [task_summary]
            return AgentOutput(
                output={
                    "retrieved_information": retrieved_information,
                    "sources": sources,
                    "evidence_refs": evidence_refs,
                    "retrieval_mode": (
                        "local_knowledge" if result.sources else "task_input_only"
                    ),
                },
                summary=f"Prepared {len(evidence_refs)} offline evidence source(s).",
                sources=sources,
                toolExecutions=[item.public_dict() for item in result.tool_executions],
                evidenceRefs=evidence_refs,
            )
        if capability == "evidence_analysis" and not upstream.get("evidence_refs"):
            raise RuntimeError("evidence_analysis requires upstream evidence references")

        descriptor = context.capability_descriptor
        if descriptor is None:
            raise StructuredGenerationError(
                "CAPABILITY_DESCRIPTOR_UNAVAILABLE",
                f"Capability descriptor is unavailable: {capability or '<empty>'}",
            )
        runtime = context.model_runtime
        if runtime is None or not runtime.is_available():
            raise StructuredGenerationError(
                "MODEL_UNAVAILABLE",
                "No production model is configured for native ACG execution.",
            )

        output_schema = dict(context.step.output_spec or descriptor.output_contract)
        generation_schema = self._generation_schema(capability, output_schema)
        pack = context.context_pack
        source_data = getattr(pack, "source_data", {}) if pack is not None else {}
        evidence_refs = list(getattr(pack, "evidence_refs", []) or []) if pack is not None else []
        prompt_method = (
            self.prompt_builder.build_artifact
            if capability == "artifact_generation"
            else self.prompt_builder.build
        )
        prompt = prompt_method(
            capability_descriptor=descriptor,
            step_goal=context.step.goal or context.step.name,
            acceptance_criteria=list(context.step.acceptance_criteria),
            source_refs=list(context.step.source_refs),
            logical_role=context.step.logical_role,
            task_title=context.task.title,
            task_input=dict(context.task.input),
            context_data=upstream,
            source_data=dict(source_data) if isinstance(source_data, dict) else {},
            evidence_refs=evidence_refs,
            output_schema=generation_schema,
        )
        thinking_mode = str(context.task.input.get("thinkingMode") or "disabled")
        output_thinking_mode = thinking_mode
        timeout_seconds = 180.0 if capability == "artifact_generation" else 120.0
        # 默认由精确模型 API/适配器决定单次输出能力。Harness 不用 capability 名称
        # 猜测 4096/8192，也不通过人为缩短内容获得表面上的合同成功。
        max_output_tokens = None
        invocations: list[dict[str, Any]] = []
        base_prompt_version = prompt_version_for_capability(capability)
        repair_used = False
        thinking_fallback_reason: str | None = None
        recovered_output: dict[str, Any] | None = None
        try:
            generated = await runtime.generate_json(
                prompt=prompt,
                schema=generation_schema,
                thinking_mode=thinking_mode,
                reasoning_effort=_requested_reasoning_effort(context),
                timeout_seconds=timeout_seconds,
                max_output_tokens=max_output_tokens,
                prompt_version=base_prompt_version,
                commit_id=context.commit_id,
            )
        except StructuredGenerationError as exc:
            thinking_enabled = thinking_mode.strip().lower() not in {
                "",
                "disabled",
                "false",
                "none",
                "off",
            }
            if exc.code == "MODEL_OUTPUT_EXHAUSTED" and capability == "artifact_generation":
                recovered_output, recovery_invocations = await self._recover_artifact_by_sections(
                    context=context,
                    runtime=runtime,
                    original_prompt=prompt,
                    thinking_mode=output_thinking_mode,
                    timeout_seconds=timeout_seconds,
                    prompt_version=base_prompt_version,
                    exhausted_audit=exc.audit,
                )
                invocations.extend(recovery_invocations)
            elif exc.code == "MODEL_OUTPUT_EXHAUSTED" and not _workset_recovery_bounded(context):
                try:
                    recovered_output, recovery_invocations = await self._recover_capability_by_subtasks(
                        context=context, runtime=runtime, original_prompt=prompt,
                        output_schema=generation_schema, thinking_mode=output_thinking_mode,
                        timeout_seconds=timeout_seconds, prompt_version=base_prompt_version,
                        exhausted_audit=exc.audit,
                    )
                    invocations.extend(recovery_invocations)
                except StructuredGenerationError as split_exc:
                    if split_exc.code != "MODEL_OUTPUT_NO_PROGRESS":
                        raise
                    # 语义拆分无进展时回落到确定性分段续写，而不是把整个运行判死；
                    # sectioned 恢复自身失败则以原无进展错误上抛。
                    logger.warning(
                        "semantic split produced no progress; falling back to sectioned continuation"
                    )
                    try:
                        recovered_output, section_invocations = await self._recover_artifact_by_sections(
                            context=context, runtime=runtime, original_prompt=prompt,
                            thinking_mode=output_thinking_mode, timeout_seconds=timeout_seconds,
                            prompt_version=f"{base_prompt_version}.sectioned-fallback",
                            exhausted_audit=(exc.audit if isinstance(exc.audit, dict) else None),
                        )
                        invocations.extend(section_invocations)
                    except StructuredGenerationError:
                        logger.exception("sectioned fallback failed after empty semantic split")
                        raise split_exc from None
            elif exc.code == "MODEL_EMPTY_RESPONSE" and thinking_enabled:
                thinking_fallback_reason = exc.code
                output_thinking_mode = "disabled"
                generated = await runtime.generate_json(
                    prompt=prompt,
                    schema=generation_schema,
                    thinking_mode=output_thinking_mode,
                    reasoning_effort=_requested_reasoning_effort(context),
                    timeout_seconds=timeout_seconds,
                    max_output_tokens=max_output_tokens,
                    prompt_version=(
                        f"{base_prompt_version}.thinking-finalization1"
                    ),
                    commit_id=context.commit_id,
                )
            elif exc.code != "MODEL_OUTPUT_INVALID_JSON":
                raise
            else:
                repair_used = True
                generated = await runtime.generate_json(
                    prompt=self.prompt_builder.build_json_repair(
                        original_prompt=prompt,
                        validation_error=str(exc),
                    ),
                    schema=generation_schema,
                    thinking_mode=output_thinking_mode,
                    reasoning_effort=_requested_reasoning_effort(context),
                    timeout_seconds=timeout_seconds,
                    max_output_tokens=max_output_tokens,
                    prompt_version=f"{base_prompt_version}.json-repair1",
                    commit_id=context.commit_id,
                )
        if recovered_output is not None:
            output = recovered_output
        else:
            generation_audit = generated.audit_record()
            if thinking_fallback_reason:
                generation_audit["usage"].update(
                    {
                        "thinkingFallback": True,
                        "thinkingFallbackReason": thinking_fallback_reason,
                        "requestedThinkingMode": thinking_mode,
                        "effectiveThinkingMode": output_thinking_mode,
                    }
                )
            invocations.append(generation_audit)
            output = apply_contract_defaults(dict(generated.data), generation_schema)
            if capability == "artifact_generation":
                output = self._normalize_artifact_output(context, output)
        output = self._normalize_output_evidence_refs(output, evidence_refs)
        if capability in {"verification", "artifact_generation"}:
            output = self._enforce_verification_evidence(output)
        output = compact_contract_text_arrays(output, output_schema)
        try:
            validate_contract_payload(
                output,
                output_schema,
                step_id=context.step.step_id,
                direction="output",
            )
        except ContextContractError as exc:
            if repair_used:
                raise StructuredGenerationError(
                    "OUTPUT_CONTRACT_VIOLATION",
                    str(exc),
                ) from exc
            repair_used = True
            repaired = await runtime.generate_json(
                prompt=self.prompt_builder.build_repair(
                    original_prompt=prompt,
                    invalid_data=output,
                    validation_error=str(exc),
                ),
                schema=generation_schema,
                thinking_mode=output_thinking_mode,
                reasoning_effort=_requested_reasoning_effort(context),
                timeout_seconds=timeout_seconds,
                max_output_tokens=max_output_tokens,
                prompt_version=f"{base_prompt_version}.repair1",
                commit_id=context.commit_id,
            )
            invocations.append(repaired.audit_record())
            output = apply_contract_defaults(dict(repaired.data), generation_schema)
            if capability == "artifact_generation":
                output = self._normalize_artifact_output(context, output)
            output = self._normalize_output_evidence_refs(output, evidence_refs)
            if capability in {"verification", "artifact_generation"}:
                output = self._enforce_verification_evidence(output)
            output = compact_contract_text_arrays(output, output_schema)
            try:
                validate_contract_payload(
                    output,
                    output_schema,
                    step_id=context.step.step_id,
                    direction="output",
                )
            except ContextContractError as repair_exc:
                raise StructuredGenerationError(
                    "OUTPUT_CONTRACT_VIOLATION",
                    str(repair_exc),
                ) from repair_exc

        return AgentOutput(
            output=output,
            summary=f"Native capability completed: {capability}.",
            modelInvocations=invocations,
        )

    async def _recover_capability_by_subtasks(
        self, *, context: AgentRunContext, runtime: Any, original_prompt: str,
        output_schema: dict[str, Any], thinking_mode: str, timeout_seconds: float,
        prompt_version: str, exhausted_audit: dict[str, Any] | None,
        depth: int = 0,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Decompose an exhausted semantic unit, execute children, then pairwise reduce."""
        if depth >= 8:
            raise StructuredGenerationError(
                "MODEL_OUTPUT_NO_PROGRESS",
                "semantic unit remained output-exhausted after additive decomposition",
                audit=exhausted_audit,
            )
        subtask_schema = {
            "type": "object",
            "properties": {
                "subtasks": {
                    "type": "array",
                    # 空拆分是本次事故的直接死因：合同层必须先行拒绝，
                    # 让修复指令有机会进入纠偏重试而不是业务层事后判死。
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "goal": {"type": "string"},
                            "sourceScope": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["title", "goal", "sourceScope"],
                    },
                }
            },
            "required": ["subtasks"],
        }
        invocations = (
            [dict(exhausted_audit)]
            if isinstance(exhausted_audit, dict) and exhausted_audit else []
        )
        plan = await runtime.generate_json(
            prompt=(
                f"{original_prompt}\nThe current semantic unit exceeded one response. Start a new "
                "planning operation and decompose it into smaller non-overlapping, independently "
                "complete sub-units whose union preserves the entire goal, constraints, evidence "
                "and acceptance criteria. Decide the useful subtask count. Return plan JSON only."
            ),
            schema=subtask_schema, thinking_mode=thinking_mode,
            reasoning_effort=_requested_reasoning_effort(context),
            timeout_seconds=timeout_seconds, max_output_tokens=None,
            prompt_version=f"{prompt_version}.capacity-split1",
            commit_id=f"{context.commit_id or 'capability'}:split:{depth}",
        )
        invocations.append(plan.audit_record())
        subtasks = list(plan.data.get("subtasks") or [])
        split_attempts = [plan.audit_record()]
        if not subtasks:
            # 纠偏重试：明确要求至少一个子任务；模型找不到切分点时允许以单元素
            # 透传作为最低合法形态。二次仍为空才上报无进展（并携带完整尝试审计）。
            corrective_plan = await runtime.generate_json(
                prompt=(
                    f"{original_prompt}\nThe current semantic unit exceeded one response. Start a new "
                    "planning operation and decompose it into smaller non-overlapping, independently "
                    "complete sub-units whose union preserves the entire goal. Your previous response "
                    "contained an EMPTY subtask list, which is invalid. Return AT LEAST ONE sub-task; "
                    "if decomposition is impossible, return exactly one sub-task covering the whole unit. "
                    "Return plan JSON only."
                ),
                schema=subtask_schema, thinking_mode=thinking_mode,
                reasoning_effort=_requested_reasoning_effort(context),
                timeout_seconds=timeout_seconds, max_output_tokens=None,
                prompt_version=f"{prompt_version}.capacity-split-retry1",
                commit_id=f"{context.commit_id or 'capability'}:split:{depth}:retry",
            )
            split_attempts.append(corrective_plan.audit_record())
            subtasks = list(corrective_plan.data.get("subtasks") or [])
            if not subtasks:
                raise StructuredGenerationError(
                    "MODEL_OUTPUT_NO_PROGRESS",
                    "capacity split returned no semantic sub-units after corrective retry",
                    audit={
                        "capacitySplitAttempts": len(split_attempts),
                        "invocations": [
                            item for item in (exhausted_audit, *split_attempts)
                            if isinstance(item, dict)
                        ],
                    },
                )
        invocations.extend(split_attempts[1:])
        partials: list[dict[str, Any]] = []
        for index, subtask in enumerate(subtasks):
            subprompt = (
                f"{original_prompt}\nExecute only this independently complete sub-unit. Preserve "
                "all supported details in its scope and return the original output schema.\n"
                f"SUBTASK={json.dumps(subtask, ensure_ascii=False)}"
            )
            try:
                generated = await runtime.generate_json(
                    prompt=subprompt, schema=output_schema, thinking_mode=thinking_mode,
                    reasoning_effort=_requested_reasoning_effort(context),
                    timeout_seconds=timeout_seconds, max_output_tokens=None,
                    prompt_version=f"{prompt_version}.capacity-part1",
                    commit_id=f"{context.commit_id or 'capability'}:part:{depth}:{index}",
                )
                invocations.append(generated.audit_record())
                partials.append(apply_contract_defaults(dict(generated.data), output_schema))
            except StructuredGenerationError as exc:
                if exc.code != "MODEL_OUTPUT_EXHAUSTED":
                    raise
                partial, audits = await self._recover_capability_by_subtasks(
                    context=context, runtime=runtime, original_prompt=subprompt,
                    output_schema=output_schema, thinking_mode=thinking_mode,
                    timeout_seconds=timeout_seconds, prompt_version=prompt_version,
                    exhausted_audit=exc.audit, depth=depth + 1,
                )
                partials.append(partial)
                invocations.extend(audits)

        level = partials
        round_index = 0
        while len(level) > 1:
            reduced: list[dict[str, Any]] = []
            for pair_index in range(0, len(level), 2):
                pair = level[pair_index:pair_index + 2]
                if len(pair) == 1:
                    reduced.append(pair[0])
                    continue
                merge_prompt = (
                    f"{original_prompt}\nMerge these two complete partial results without losing "
                    "supported facts, calculations, constraints, evidence, assumptions or gaps. "
                    "Deduplicate only semantically identical content. Return the original schema.\n"
                    f"LEFT={json.dumps(pair[0], ensure_ascii=False)}\n"
                    f"RIGHT={json.dumps(pair[1], ensure_ascii=False)}"
                )
                try:
                    merged = await runtime.generate_json(
                        prompt=merge_prompt, schema=output_schema, thinking_mode=thinking_mode,
                        reasoning_effort=_requested_reasoning_effort(context),
                        timeout_seconds=timeout_seconds, max_output_tokens=None,
                        prompt_version=f"{prompt_version}.capacity-reduce1",
                        commit_id=(
                            f"{context.commit_id or 'capability'}:reduce:"
                            f"{depth}:{round_index}:{pair_index // 2}"
                        ),
                    )
                    invocations.append(merged.audit_record())
                    reduced.append(apply_contract_defaults(dict(merged.data), output_schema))
                except StructuredGenerationError as exc:
                    if exc.code != "MODEL_OUTPUT_EXHAUSTED":
                        raise
                    merged_data, audits = await self._recover_capability_by_subtasks(
                        context=context, runtime=runtime, original_prompt=merge_prompt,
                        output_schema=output_schema, thinking_mode=thinking_mode,
                        timeout_seconds=timeout_seconds, prompt_version=prompt_version,
                        exhausted_audit=exc.audit, depth=depth + 1,
                    )
                    reduced.append(merged_data)
                    invocations.extend(audits)
            level = reduced
            round_index += 1
        return level[0], invocations

    async def _recover_artifact_by_sections(
        self, *, context: AgentRunContext, runtime: Any, original_prompt: str,
        thinking_mode: str, timeout_seconds: float, prompt_version: str,
        exhausted_audit: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Replace a truncated monolithic artifact with outline -> sections -> assembly."""
        text_list = {"type": "array", "items": {"type": "string"}}
        section_plan = {
            "type": "object",
            "properties": {
                "title": {"type": "string"}, "goal": {"type": "string"},
                "sourceFields": text_list,
            },
            "required": ["title", "goal", "sourceFields"],
        }
        outline_schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "executiveSummary": {"type": "string"},
                "sections": {"type": "array", "items": section_plan},
                "calculations": {"type": "array", "items": {"type": "object"}},
                "assumptions": text_list,
                "openQuestions": text_list,
                "sourceRefs": text_list,
            },
            "required": [
                "title", "executiveSummary", "sections", "calculations",
                "assumptions", "openQuestions", "sourceRefs",
            ],
        }
        invocations = (
            [dict(exhausted_audit)]
            if isinstance(exhausted_audit, dict) and exhausted_audit else []
        )
        outline = await runtime.generate_json(
            prompt=(
                f"{original_prompt}\nThe complete artifact exceeded one response. Start a new "
                "semantic operation and design only a lossless chapter outline. Decide chapter "
                "count and granularity from mission coverage and usefulness. Do not write chapter "
                "prose yet. Return outline JSON only."
            ),
            schema=outline_schema, thinking_mode=thinking_mode,
            reasoning_effort=_requested_reasoning_effort(context),
            timeout_seconds=timeout_seconds, max_output_tokens=None,
            prompt_version=f"{prompt_version}.capacity-outline1",
            commit_id=f"{context.commit_id or 'artifact'}:outline",
        )
        invocations.append(outline.audit_record())
        outline_data = apply_contract_defaults(dict(outline.data), outline_schema)
        sections: list[dict[str, Any]] = []
        for index, section in enumerate(outline_data.get("sections") or []):
            generated, audits = await self._generate_artifact_section(
                context=context, runtime=runtime, original_prompt=original_prompt,
                section=dict(section), thinking_mode=thinking_mode,
                timeout_seconds=timeout_seconds, prompt_version=prompt_version,
                path=str(index),
            )
            sections.extend(generated)
            invocations.extend(audits)

        verification_schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["passed", "partial", "failed"]},
                "checks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "criterion": {"type": "string"},
                            "result": {"type": "string"},
                            "evidence": {"type": "string"},
                        },
                        "required": ["criterion", "result", "evidence"],
                    },
                },
                "unresolvedGaps": text_list,
            },
            "required": ["status", "checks", "unresolvedGaps"],
        }
        verification = await runtime.generate_json(
            prompt=(
                f"{original_prompt}\nVerify the assembled chapter index against every acceptance "
                "criterion, constraint, evidence requirement and expected artifact. A check without "
                "evidence cannot pass. Return verification JSON only.\n"
                "ASSEMBLED_CHAPTER_INDEX="
                + json.dumps(
                    [
                        {
                            "title": item.get("title"),
                            "sourceFields": item.get("sourceFields") or [],
                        }
                        for item in sections
                    ],
                    ensure_ascii=False,
                )
            ),
            schema=verification_schema, thinking_mode=thinking_mode,
            reasoning_effort=_requested_reasoning_effort(context),
            timeout_seconds=timeout_seconds, max_output_tokens=None,
            prompt_version=f"{prompt_version}.capacity-verification1",
            commit_id=f"{context.commit_id or 'artifact'}:verification",
        )
        invocations.append(verification.audit_record())
        output = {
            "deliverable": {
                "title": outline_data["title"],
                "executiveSummary": outline_data["executiveSummary"],
                "sections": sections,
                "calculations": outline_data["calculations"],
                "assumptions": outline_data["assumptions"],
                "openQuestions": outline_data["openQuestions"],
                "sourceRefs": outline_data["sourceRefs"],
            },
            "verification": dict(verification.data),
        }
        return self._normalize_artifact_output(context, output), invocations

    async def _generate_artifact_section(
        self, *, context: AgentRunContext, runtime: Any, original_prompt: str,
        section: dict[str, Any], thinking_mode: str, timeout_seconds: float,
        prompt_version: str, path: str, depth: int = 0,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Generate one complete section; recursively split only after output exhaustion."""
        text_list = {"type": "array", "items": {"type": "string"}}
        section_schema = {
            "type": "object",
            "properties": {
                "title": {"type": "string"}, "content": {"type": "string"},
                "sourceFields": text_list,
            },
            "required": ["title", "content", "sourceFields"],
        }
        try:
            generated = await runtime.generate_json(
                prompt=(
                    f"{original_prompt}\nGenerate this one complete artifact chapter. Preserve all "
                    "supported detail assigned to it; do not summarize merely to reduce length. "
                    f"Return section JSON only.\nSECTION={json.dumps(section, ensure_ascii=False)}"
                ),
                schema=section_schema, thinking_mode=thinking_mode,
                reasoning_effort=_requested_reasoning_effort(context),
                timeout_seconds=timeout_seconds, max_output_tokens=None,
                prompt_version=f"{prompt_version}.section1",
                commit_id=f"{context.commit_id or 'artifact'}:section:{path}",
            )
            return [apply_contract_defaults(dict(generated.data), section_schema)], [generated.audit_record()]
        except StructuredGenerationError as exc:
            if exc.code != "MODEL_OUTPUT_EXHAUSTED":
                raise
            if depth >= 8:
                raise StructuredGenerationError(
                    "MODEL_OUTPUT_NO_PROGRESS",
                    "artifact section remained output-exhausted after additive decomposition",
                    audit=exc.audit,
                ) from exc
            subsection_schema = {
                "type": "object",
                "properties": {
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"}, "goal": {"type": "string"},
                                "sourceFields": text_list,
                            },
                            "required": ["title", "goal", "sourceFields"],
                        },
                    },
                },
                "required": ["sections"],
            }
            split = await runtime.generate_json(
                prompt=(
                    f"{original_prompt}\nThe declared section exceeded one response. Decompose it "
                    "into smaller non-overlapping subsections whose union preserves its complete "
                    f"goal and sources. Return subsection outline JSON only.\nSECTION={json.dumps(section, ensure_ascii=False)}"
                ),
                schema=subsection_schema, thinking_mode=thinking_mode,
                reasoning_effort=_requested_reasoning_effort(context),
                timeout_seconds=timeout_seconds, max_output_tokens=None,
                prompt_version=f"{prompt_version}.section-split1",
                commit_id=f"{context.commit_id or 'artifact'}:section:{path}:split",
            )
            children = list(split.data.get("sections") or [])
            if not children:
                raise StructuredGenerationError(
                    "MODEL_OUTPUT_NO_PROGRESS", "artifact section split returned no children"
                )
            results: list[dict[str, Any]] = []
            audits = [dict(exc.audit)] if isinstance(exc.audit, dict) and exc.audit else []
            audits.append(split.audit_record())
            for index, child in enumerate(children):
                child_results, child_audits = await self._generate_artifact_section(
                    context=context, runtime=runtime, original_prompt=original_prompt,
                    section=dict(child), thinking_mode=thinking_mode,
                    timeout_seconds=timeout_seconds, prompt_version=prompt_version,
                    path=f"{path}.{index}", depth=depth + 1,
                )
                results.extend(child_results)
                audits.extend(child_audits)
            return results, audits

    async def _run_workset(self, context: AgentRunContext) -> AgentOutput:
        """Map immutable material fragments, then reduce them as a balanced tree."""
        session = context.content_workset_session
        mapped: list[AgentOutput] = []
        for envelope in session.mapped_results():
            mapped.append(AgentOutput.model_validate(envelope))
        for unit in session.pending_units():
            result = await self._execute_workset_unit(context, unit)
            session.persist_map_result(
                int(unit["sequence"]),
                result.model_dump(by_alias=True, mode="json"),
            )
            mapped.append(result)
        session.seal()
        if not mapped:
            raise StructuredGenerationError("WORKSET_EMPTY", "Workset has no material fragments")

        level = mapped
        round_index = 0
        reduction_results: list[AgentOutput] = []
        while len(level) > 1:
            reduced: list[AgentOutput] = []
            for pair_index in range(0, len(level), 2):
                pair = level[pair_index:pair_index + 2]
                if len(pair) == 1:
                    reduced.append(pair[0])
                    continue
                result = await self._reduce_workset_pair(
                    context, pair[0], pair[1], round_index, pair_index // 2
                )
                reduced.append(result)
                reduction_results.append(result)
            level = reduced
            round_index += 1
        final = level[0]
        all_invocations = [
            invocation
            for result in [*mapped, *reduction_results]
            for invocation in result.model_invocations
        ]
        return final.model_copy(update={
            "summary": (
                f"Workset completed from {len(mapped)} persisted fragment result(s); "
                f"reduced in {round_index} level(s)."
            ),
            "model_invocations": all_invocations,
        })

    async def _execute_workset_unit(
        self, context: AgentRunContext, unit: dict[str, Any], *, depth: int = 0
    ) -> AgentOutput:
        subcontext = self._workset_context(
            context,
            source_key=f"materialFragment:{unit['sequence']}:{depth}",
            source_payload=unit,
            commit_suffix=f"map:{unit['sequence']}:{depth}",
            boundary=True,
        )
        try:
            return await self.run(subcontext)
        except StructuredGenerationError as exc:
            content = str(unit.get("content") or "")
            if exc.code != "MODEL_OUTPUT_EXHAUSTED" or len(content) < 2:
                raise
            midpoint = len(content) // 2
            left_unit = {**unit, "content": content[:midpoint], "subrange": f"0:{midpoint}"}
            right_unit = {**unit, "content": content[midpoint:], "subrange": f"{midpoint}:{len(content)}"}
            left = await self._execute_workset_unit(context, left_unit, depth=depth + 1)
            right = await self._execute_workset_unit(context, right_unit, depth=depth + 1)
            reduced = await self._reduce_workset_pair(
                context, left, right, depth, int(unit["sequence"])
            )
            exhausted_audit = [dict(exc.audit)] if isinstance(exc.audit, dict) and exc.audit else []
            return reduced.model_copy(update={
                "model_invocations": [
                    *exhausted_audit,
                    *left.model_invocations,
                    *right.model_invocations,
                    *reduced.model_invocations,
                ],
            })

    async def _reduce_workset_pair(
        self, context: AgentRunContext, left: AgentOutput, right: AgentOutput,
        round_index: int, pair_index: int,
    ) -> AgentOutput:
        return await self.run(self._workset_context(
            context,
            source_key=f"worksetReducer:{round_index}:{pair_index}",
            source_payload={
                "instruction": (
                    "Merge both complete partial results. Preserve every supported fact, item, "
                    "constraint, source reference, assumption and unresolved gap; deduplicate only "
                    "semantically identical content."
                ),
                "left": left.output,
                "right": right.output,
            },
            commit_suffix=f"reduce:{round_index}:{pair_index}",
        ))

    @staticmethod
    def _workset_context(
        context: AgentRunContext, *, source_key: str,
        source_payload: dict[str, Any], commit_suffix: str,
        boundary: bool = False,
    ) -> AgentRunContext:
        original_pack = context.context_pack
        original_data = dict(getattr(original_pack, "data", {}) or {})
        if boundary:
            original_data["recoveryBoundary"] = "workset"
        original_sources = dict(getattr(original_pack, "source_data", {}) or {})
        original_sources[source_key] = source_payload
        pack = ContextPack(
            runId=context.run.run_id,
            stepId=context.step.step_id,
            objective=getattr(original_pack, "objective", "") if original_pack else "",
            stepGoal=context.step.goal or context.step.name,
            data=original_data,
            sourceData=original_sources,
            evidenceRefs=list(getattr(original_pack, "evidence_refs", ()) or ()),
            tokensDelivered=0,
            tokensAvailable=0,
            sourceStepIds=list(getattr(original_pack, "source_step_ids", ()) or ()),
            inputRevision=input_revision({"data": original_data, "sourceData": original_sources}),
            attemptId=str(context.commit_id or ""),
        )
        step_input = dict(context.step.input)
        step_input.pop("workset", None)
        step = context.step.model_copy(update={"input": step_input})
        return context.model_copy(update={
            "step": step,
            "context_pack": pack,
            "content_workset_session": None,
            "commit_id": f"{context.commit_id or 'workset'}:{commit_suffix}",
        })

    @staticmethod
    def _enforce_verification_evidence(output: dict[str, Any]) -> dict[str, Any]:
        verification = output.get("verification")
        if not isinstance(verification, dict) or verification.get("status") != "passed":
            return output
        checks = verification.get("checks")
        evidence_complete = bool(checks) and all(
            isinstance(check, dict) and str(check.get("evidence") or "").strip()
            for check in checks
        )
        if evidence_complete:
            return output
        normalized = dict(output)
        verification = dict(verification)
        verification["status"] = "partial"
        gap_key = "unresolvedGaps" if "unresolvedGaps" in verification else "unresolved_gaps"
        gaps = list(verification.get(gap_key) or [])
        gaps.append("Verification cannot pass because one or more checks lack evidence.")
        verification[gap_key] = list(dict.fromkeys(gaps))
        normalized["verification"] = verification
        return normalized

    @staticmethod
    def _normalize_output_evidence_refs(
        output: dict[str, Any],
        allowlisted_refs: list[str],
    ) -> dict[str, Any]:
        """Prevent a model from minting evidence identities outside ContextPack."""
        key = "evidence_refs" if "evidence_refs" in output else "evidenceRefs" if "evidenceRefs" in output else None
        if key is None:
            return output
        allowed = list(dict.fromkeys(str(item) for item in allowlisted_refs if str(item).strip()))
        normalized = dict(output)
        normalized[key] = [
            str(item) for item in output.get(key, [])
            if str(item) in set(allowed)
        ]
        if not normalized[key] and allowed:
            normalized[key] = allowed
        return normalized

    @staticmethod
    def _generation_schema(
        capability: str,
        output_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Return the semantic contract owned by the model.

        Runtime output remains governed by ``output_schema``.  Final Markdown and
        the Artifact envelope are deterministic projections, so asking the model
        to reproduce them would duplicate the deliverable and waste its bounded
        completion budget.
        """

        schema = deepcopy(output_schema)
        if capability != "artifact_generation":
            return schema
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return schema
        semantic_fields = {"deliverable", "verification"}
        schema["properties"] = {
            name: value
            for name, value in properties.items()
            if name in semantic_fields
        }
        schema["required"] = [
            name
            for name in schema.get("required", [])
            if name in semantic_fields
        ]
        return schema

    @classmethod
    def _normalize_artifact_output(
        cls,
        context: AgentRunContext,
        output: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = dict(output)
        deliverable = normalized.get("deliverable")
        if not isinstance(deliverable, dict):
            deliverable = {
                "title": context.task.title,
                "executiveSummary": str(deliverable or ""),
                "sections": [],
                "calculations": [],
                "assumptions": [],
                "openQuestions": [],
                "sourceRefs": [],
            }
            normalized["deliverable"] = deliverable
        final_answer = cls._render_artifact_markdown(
            deliverable,
            normalized.get("verification"),
        )
        normalized["final_answer"] = final_answer
        artifact_id = "artifact_" + hashlib.sha256(
            f"{context.run.run_id}:{context.step.step_id}:{context.step.attempt}".encode(
                "utf-8"
            )
        ).hexdigest()[:16]
        normalized["artifact"] = {
            "artifactId": artifact_id,
            "type": "report",
            "artifactKey": str(context.step.input.get("artifactKey") or "primary")
            if isinstance(context.step.input, dict)
            else "primary",
            "title": str(deliverable.get("title") or context.task.title),
            "mediaType": "text/markdown",
            "content": final_answer,
            "structuredData": deliverable,
        }
        # Keep the singular envelope for the existing runtime contract while
        # exposing the multi-artifact shape needed by the identity projection.
        normalized["artifacts"] = [dict(normalized["artifact"])]
        return normalized

    @staticmethod
    def _render_artifact_markdown(
        deliverable: dict[str, Any],
        verification: Any,
    ) -> str:
        """Render one user-facing artifact from the structured semantic result."""

        def text(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, str):
                return value.strip()
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

        title = text(deliverable.get("title")) or "Workflow deliverable"
        executive_summary = text(deliverable.get("executiveSummary"))
        language_sample = title + executive_summary
        chinese = any("\u4e00" <= character <= "\u9fff" for character in language_sample)
        labels = {
            "calculations": "计算与依据" if chinese else "Calculations and basis",
            "formula": "公式" if chinese else "Formula",
            "inputs": "输入" if chinese else "Inputs",
            "result": "结果" if chinese else "Result",
            "assumptions": "假设" if chinese else "Assumptions",
            "questions": "待确认事项" if chinese else "Open questions",
            "sources": "来源引用" if chinese else "Source references",
            "verification": "验收核对" if chinese else "Verification",
            "status": "状态" if chinese else "Status",
            "gaps": "未解决缺口" if chinese else "Unresolved gaps",
        }
        lines = [f"# {title}"]
        if executive_summary:
            lines.extend(["", executive_summary])

        for section in deliverable.get("sections") or []:
            if not isinstance(section, dict):
                continue
            section_title = text(section.get("title"))
            content = text(section.get("content"))
            if section_title:
                lines.extend(["", f"## {section_title}"])
            if content:
                lines.extend(["", content])

        calculations = deliverable.get("calculations") or []
        if calculations:
            lines.extend(["", f"## {labels['calculations']}"])
            for calculation in calculations:
                if not isinstance(calculation, dict):
                    continue
                name = text(calculation.get("name"))
                if name:
                    lines.extend(["", f"### {name}"])
                for key in ("formula", "inputs", "result", "assumptions"):
                    value = calculation.get(key)
                    if value in (None, "", []):
                        continue
                    rendered = ", ".join(text(item) for item in value) if isinstance(value, list) else text(value)
                    lines.append(f"- **{labels[key]}**: {rendered}")

        for key, label in (
            ("assumptions", labels["assumptions"]),
            ("openQuestions", labels["questions"]),
            ("sourceRefs", labels["sources"]),
        ):
            values = deliverable.get(key) or []
            if values:
                lines.extend(["", f"## {label}"])
                lines.extend(f"- {text(item)}" for item in values)

        if isinstance(verification, dict):
            lines.extend(["", f"## {labels['verification']}"])
            status = text(verification.get("status"))
            if status:
                lines.append(f"- **{labels['status']}**: {status}")
            for check in verification.get("checks") or []:
                if not isinstance(check, dict):
                    continue
                criterion = text(check.get("criterion"))
                result = text(check.get("result"))
                evidence = text(check.get("evidence"))
                rendered = " — ".join(item for item in (criterion, result, evidence) if item)
                if rendered:
                    lines.append(f"- {rendered}")
            gaps = verification.get("unresolvedGaps") or []
            if gaps:
                lines.append(f"- **{labels['gaps']}**: " + "; ".join(text(item) for item in gaps))

        return "\n".join(lines).strip()

    @staticmethod
    def _upstream_data(context: AgentRunContext) -> dict[str, Any]:
        pack = context.context_pack
        data = getattr(pack, "data", None) if pack is not None else None
        return dict(data) if isinstance(data, dict) else {}


def native_bootstrap_definition() -> WorkflowDefinition:
    """返回进入既有规划引擎的空原生 ACG 工作流定义。

    返回的定义不含步骤，只提供稳定的工作流标识和领域元数据，供后续规划
    填充；函数不注册对象、不读写全局状态，对每次调用返回独立合同对象。
    """

    return WorkflowDefinition(
        workflowId=NATIVE_ACG_WORKFLOW_ID,
        name="知弈OS原生 ACG 运行时",
        domain="general",
        intent="general",
        runtimeEngine="acg",
        definitionType=WorkflowDefinitionType.NATIVE_BOOTSTRAP,
        description="Core-owned planner bootstrap for native domain-neutral tasks.",
        steps=[],
    )


def general_evidence_definition() -> WorkflowDefinition:
    """Return the bounded Core-owned evidence decision planning template."""

    return WorkflowDefinition(
        workflowId=GENERAL_EVIDENCE_WORKFLOW_ID,
        name="Core General Evidence Decision",
        domain="general",
        intent="evidence_decision",
        runtimeEngine="acg",
        definitionType=WorkflowDefinitionType.NATIVE_BOOTSTRAP,
        description=(
            "Core-owned evidence decision workflow with extraction, retrieval, "
            "evidence analysis, comparison, validation, human review, and citation report."
        ),
        tags=["general", "evidence", "decision", "review", "citation"],
        requiredCapabilities=[
            "task_understanding",
            "information_extraction",
            "information_retrieval",
            "evidence_analysis",
            "comparative_analysis",
            "verification",
            "artifact_generation",
        ],
        reviewCapability="verification",
        steps=[],
    )


def register_native_runtime(*, agent_registry, workflow_registry) -> None:
    """向给定注册表登记原生 Agent 与启动工作流。

    两个参数必须提供兼容的 ``register`` 方法；本函数按 Agent、工作流顺序
    执行注册，重复项或注册表错误由其实现直接抛出，不吞没异常也不实现
    外部持久化。
    """

    agent_registry.register(NativeGeneralAgent())
    workflow_registry.register(native_bootstrap_definition())
    workflow_registry.register(general_evidence_definition())


__all__ = [
    "NATIVE_ACG_WORKFLOW_ID",
    "GENERAL_EVIDENCE_WORKFLOW_ID",
    "NATIVE_AGENT_NAME",
    "NATIVE_CAPABILITIES",
    "NativeGeneralAgent",
    "general_evidence_definition",
    "native_bootstrap_definition",
    "register_native_runtime",
]
