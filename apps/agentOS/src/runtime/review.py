"""ACG 审核决定的应用边界：校验、批准/拒绝迁移与延迟记忆提交。

本服务从 ``WorkflowRuntime`` 机械迁移而来（PR-8C.3）。它回答"审核决定是否
合法、批准后恢复输入是什么"：operation 幂等、期望 revision/step 状态、
checkpoint 审核主体身份、拒绝终态收敛、批准后 deferred memory 落库。
Run 锁与执行并发权威仍在 facade——本服务不触碰 ``run_lock_manager``；
批准后的"怎么继续跑"由 facade 调用 ACGExecutionService 完成，本服务只交还
恢复输入，不 import 也不驱动执行循环。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from components.executor import ACGExecutionState, ACGNodeRunner
from components.memory import MemoryService, StructuredMemoryEvent
from components.mission_manager.state_machine import StateMachine
from contracts.execution import WorkflowProgressPhase
from contracts.memory import MemoryPolicy, MemoryType
from contracts.workflow import (
    ReviewDecision,
    ReviewDecisionType,
    RuntimeRunRecord,
    StepStatus,
    TraceEventType,
    WorkflowStatus,
    WorkflowStep,
    utc_now,
)
from runtime.ports import CollaboratorAccess, RuntimeCollaborators
from support.stores._policy import acg_review_subject


class ReviewConflictError(ValueError):
    """表示客户端读取审核对象后，运行或步骤已被其他操作更新。"""


@dataclass
class ACGReviewOutcome:
    """审核应用结果：终态 Run，或批准路径的恢复输入。"""

    run: RuntimeRunRecord
    resume_state: ACGExecutionState | None = None


class ReviewService(CollaboratorAccess):
    """在已持有的 Run 锁内应用一个 ACG 审核决定（approve / reject / 幂等重放）。"""

    def __init__(
        self,
        *,
        collaborators: RuntimeCollaborators,
        state_machine: StateMachine,
        set_run_lifecycle: Callable[..., RuntimeRunRecord],
        mark_failed: Callable[[str], None],
        validate_state_references: Callable[..., None],
    ) -> None:
        self.ports = collaborators
        self.state_machine = state_machine
        self._set_run_lifecycle = set_run_lifecycle
        self._mark_failed = mark_failed
        self._validate_state_references = validate_state_references

    def apply_acg(self, decision: ReviewDecision) -> ACGReviewOutcome:
        """校验审核决定并产出恢复输入；锁与续跑由 facade 负责。"""
        run = self.workflow_store.get_run(decision.run_id)
        existing = self.find_review_operation(run, decision.operation_id)
        if existing is not None:
            if existing.get("stepId") == decision.step_id and existing.get("decision") == decision.decision.value:
                return ACGReviewOutcome(run=run)
            raise ReviewConflictError("review operation id was already used for a different decision")
        if run.status != WorkflowStatus.WAITING_REVIEW:
            raise ReviewConflictError("workflow run is no longer waiting for review")
        checkpoint_id = str(run.execution_state.get("checkpointId") or "")
        checkpoint_data = self.checkpoint_store.load(run_id=run.run_id, checkpoint_id=checkpoint_id)
        if checkpoint_data is None:
            raise ValueError("review checkpoint does not exist for this run")
        restored = ACGExecutionState.model_validate(checkpoint_data)
        subject_type, subject_id = acg_review_subject(restored.review_payload)
        if subject_type == "planner" and (restored.review_payload or {}).get("question"):
            raise ReviewConflictError("Planner clarification requires an answer, not review approval")
        if decision.step_id != subject_id:
            raise ReviewConflictError("review decision does not match the persisted ACG subject")
        step = run.get_step(subject_id) if subject_type == "step" else None
        if (
            decision.expected_run_updated_at is not None
            and run.updated_at != decision.expected_run_updated_at
        ):
            raise ReviewConflictError("workflow run revision changed")
        if step is not None and step.status != StepStatus.WAITING_REVIEW:
            raise ReviewConflictError("workflow step is no longer waiting for review")
        if (
            step is not None
            and decision.expected_step_status is not None
            and step.status != decision.expected_step_status
        ):
            raise ReviewConflictError("workflow step state changed")
        # 拒绝路径也必须验证 checkpoint 中的审计引用。否则攻击者可借由“直接
        # 拒绝”绕过归属检查，留下无法解释的审核记录或伪造的待写入意图。
        self._validate_state_references(run=run, state=restored)
        if decision.decision is not ReviewDecisionType.APPROVED:
            if step is not None:
                self._transition_step(step, StepStatus.FAILED)
            run.error = {"code": "review_rejected", "message": decision.comment[:500]}
            self.trace_store.append(
                run,
                TraceEventType.REVIEW_DECIDED,
                step_id=subject_id,
                observation="ACG review rejected",
                payload={
                    "subjectType": subject_type,
                    "decision": decision.decision.value,
                    "operationId": decision.operation_id,
                    "reviewer": decision.reviewer,
                    "comment": decision.comment,
                    "deferredMemoryDiscarded": isinstance(
                        (restored.review_payload or {}).get("pendingMemory"), dict
                    ),
                },
            )
            run = self._set_run_lifecycle(run, status=WorkflowStatus.FAILED, phase=WorkflowProgressPhase.FAILED)
            self._mark_failed(run.mission_id)
            self.workflow_store.save_run(run)
            return ACGReviewOutcome(run=run)
        if step is not None:
            self._commit_deferred_memory(run=run, step=step, state=restored)
        # The node result was committed before the interrupt; approval
        # resolves the review projection and must not leave a stale
        # WAITING_REVIEW step in an otherwise completed persisted run.
        if step is not None:
            self._transition_step(step, StepStatus.COMPLETED)
        self.trace_store.append(
            run,
            event_type=TraceEventType.REVIEW_DECIDED,
            step_id=subject_id,
            observation="ACG review approved",
            payload={
                "subjectType": subject_type,
                "decision": decision.decision.value,
                "operationId": decision.operation_id,
                "reviewer": decision.reviewer,
                "comment": decision.comment,
            },
        )
        return ACGReviewOutcome(run=run, resume_state=restored)

    def _commit_deferred_memory(
        self,
        *,
        run: RuntimeRunRecord,
        step: WorkflowStep,
        state: ACGExecutionState,
    ) -> None:
        """在人工批准后按待写入的结构化事件落入正式记忆。

        待写入意图只携带输出引用、策略、审计决定和经过白名单验证的 MemoryEvent；
        输出引用仍需按 run/step 校验，但完整输出正文不会进入 MemoryStore。
        """
        review_payload = state.review_payload or {}
        pending = review_payload.get("pendingMemory")
        if pending is None:
            return
        if not isinstance(pending, dict):
            raise ValueError("review pendingMemory must be an object")
        output_ref = pending.get("outputRef")
        policy_id = pending.get("policyId")
        write_type = pending.get("writeType")
        decision_ref = pending.get("auditDecisionRef")
        memory_event = pending.get("memoryEvent")
        if not all(isinstance(value, str) and value for value in (output_ref, policy_id, write_type, decision_ref)):
            raise ValueError("review pendingMemory is incomplete")
        if review_payload.get("auditDecisionRef") != decision_ref:
            raise ValueError("review pendingMemory audit decision does not match review payload")
        allowed_audit_outcomes = {"review"}
        if step.requires_review:
            # A Blueprint-declared review gate is authoritative even when the
            # generic output-risk audit independently returns ``allow``.
            allowed_audit_outcomes.add("allow")
        self.decision_store.assert_decision(
            run_id=run.run_id,
            step_id=step.step_id,
            decision_ref=decision_ref,
            outcomes=allowed_audit_outcomes,
        )
        policy = ACGNodeRunner._memory_policy(step.input)
        if not policy["write"]:
            raise ValueError("review pendingMemory exists while step memory write is disabled")
        if policy["policyId"] != policy_id or policy["writeType"].value != write_type:
            raise ValueError("review pendingMemory does not match frozen memory policy")
        self.execution_value_store.assert_reference(
            kind="output",
            run_id=run.run_id,
            step_id=step.step_id,
            reference=output_ref,
        )
        event = StructuredMemoryEvent.model_validate(memory_event)
        if event.run_id != run.run_id or event.step_id != step.step_id:
            raise ValueError("review pendingMemory event belongs to a different run or step")
        record = MemoryService(store=self.memory_store).remember_step_output(
            run_id=run.run_id,
            step_id=step.step_id,
            output=event.model_dump(by_alias=True, mode="json"),
            memory_type=MemoryType(write_type),
            policy=MemoryPolicy(
                policyId=policy_id,
                allowedTypes=[MemoryType(write_type)],
                requireAudit=bool(policy["requireAudit"]),
            ),
        )
        if record is None:
            raise ValueError("review deferred memory was rejected by frozen policy")
        state.memory_refs[step.step_id] = record.memory_id
        self.trace_store.append(
            run,
            TraceEventType.DATA_CONSUMED,
            step_id=step.step_id,
            observation="Deferred memory committed after review approval",
            payload={
                "policyId": policy_id,
                "writeType": write_type,
                "written": True,
                "memoryEventRef": event.event_id,
                "auditDecisionRef": decision_ref,
            },
        )

    @staticmethod
    def find_review_operation(run: RuntimeRunRecord, operation_id: str | None) -> dict | None:
        if not operation_id:
            return None
        for event in run.trace:
            if event.event_type != TraceEventType.REVIEW_DECIDED:
                continue
            payload = event.payload or {}
            if payload.get("operationId") == operation_id:
                return {**payload, "stepId": event.step_id}
        return None

    def _transition_step(self, step: WorkflowStep, status: StepStatus) -> None:
        step.status = self.state_machine.transition(step.status, status)
        if status == StepStatus.RUNNING:
            step.started_at = step.started_at or utc_now()
        if status == StepStatus.COMPLETED:
            step.completed_at = step.completed_at or utc_now()


__all__ = ["ACGReviewOutcome", "ReviewConflictError", "ReviewService"]
