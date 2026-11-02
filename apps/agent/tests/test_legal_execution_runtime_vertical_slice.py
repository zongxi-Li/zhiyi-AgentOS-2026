"""Golden integration tests for the Legal Pack on the execution runtime."""

from __future__ import annotations

import json

from contracts.planning import TaskImplementationBinding, TaskPlan, PlannedTask, TaskPlanRelation
from contracts.workflow import ReviewDecision, ReviewDecisionType, StepStatus, WorkflowStatus

from packs.legal.planning import build_contract_review_blueprint


_SECRET_MARKER = "TOP-SECRET-CONTRACT-BODY-REF-ONLY-20260815"


def _environment(tmp_path) -> dict[str, str]:
    return {
        "AGENTOS_WORKFLOW_DB_PATH": str(tmp_path / "workflows.sqlite3"),
        "AGENTOS_LANGGRAPH_CHECKPOINT_DB": str(tmp_path / "checkpoints.sqlite3"),
        "AGENTOS_EXECUTION_VALUE_DB": str(tmp_path / "values.sqlite3"),
        "AGENTOS_EXECUTION_MEMORY_DB": str(tmp_path / "memory.sqlite3"),
        "AGENTOS_PROVENANCE_DB": str(tmp_path / "provenance.sqlite3"),
        "AGENTOS_AUDIT_DB": str(tmp_path / "decisions.sqlite3"),
    }


def _output(runtime, run, step_id: str) -> dict:
    output_ref = run.execution_state["outputRefs"][step_id]
    return runtime.execution_value_store.get_output(
        run_id=run.run_id,
        output_ref=output_ref,
    )


async def test_legal_contract_review_restarts_and_resumes_without_replaying_commits(
    tmp_path, managed_default_runtime
):
    build_runtime, close_owned = managed_default_runtime
    environment = _environment(tmp_path)
    first = build_runtime(environment=environment)
    workflow = first.workflow_registry.get("legal_contract_review_v1")
    mission = first.create_mission(
        title="Legal contract review golden run",
        domain="legal",
        intent="contract_review",
        workflow_id=workflow.workflow_id,
        input={
            "contractText": (
                f"{_SECRET_MARKER}. The final payment is not conditional on final acceptance; "
                "the supplier may reuse customer data for model training."
            ),
            "webSearchEnabled": True,
            "thinkingMode": "disabled",
        },
    )

    # TaskPlan is the semantic source. Pack helper steps are declared explicitly;
    # the executable ACG is built only after this plan has been assembled.
    task_plan_nodes = [
        *workflow.planning_nodes,
        PlannedTask(
            key="helper:statute-retrieve",
            title="Legal statute retrieval",
            objective="Retrieve relevant legal sources through the authorized tool runtime",
            acceptanceCriteria=("Retrieved sources have stable evidence references",),
            metadata={"plannerStrategy": "legal_pack_explicit_plan"},
        ),
        PlannedTask(
            key="helper:auto-review",
            title="Automatic low-risk review",
            objective="Apply the bounded automatic review path when the risk route selects it",
            capabilityRequirements=("human_review_gate",),
            acceptanceCriteria=("The low-risk review result is explicit",),
            metadata={"plannerStrategy": "legal_pack_explicit_plan"},
        ),
    ]
    task_plan_relations = [
        *workflow.planning_relations,
        TaskPlanRelation(
            sourceKey="contract-understanding",
            targetKey="helper:statute-retrieve",
            relationType="depends_on",
        ),
        TaskPlanRelation(
            sourceKey="helper:statute-retrieve",
            targetKey="risk-analysis",
            relationType="depends_on",
        ),
        TaskPlanRelation(
            sourceKey="helper:statute-retrieve",
            targetKey="legal-evidence",
            relationType="depends_on",
        ),
        TaskPlanRelation(
            sourceKey="revision-advice",
            targetKey="helper:auto-review",
            relationType="depends_on",
        ),
        TaskPlanRelation(
            sourceKey="helper:auto-review",
            targetKey="review-report",
            relationType="depends_on",
        ),
    ]
    task_plan = TaskPlan(
        missionId=mission.mission_id,
        planVersion=1,
        nodes=tuple(task_plan_nodes),
        relations=tuple(task_plan_relations),
    )

    blueprint = build_contract_review_blueprint(workflow)
    binding_map = (
        ("contract-understanding", "parse_contract"),
        ("clause-classification", "classify_clauses"),
        ("risk-analysis", "risk_detect"),
        ("legal-evidence", "legal_evidence_match"),
        ("revision-advice", "suggestion_generate"),
        ("review-decision", "human_review"),
        ("review-report", "report_generate"),
        ("helper:statute-retrieve", "statute_retrieve"),
        ("helper:auto-review", "auto_review"),
    )
    task_bindings = tuple(
        TaskImplementationBinding(planNodeKey=plan_key, acgNodeId=step_id)
        for plan_key, step_id in binding_map
    )
    mission.input.update({
        "acgBlueprint": blueprint.model_dump(by_alias=True, mode="json"),
        "taskPlan": task_plan.model_dump(by_alias=True, mode="json"),
        "taskBindings": [
            item.model_dump(by_alias=True, mode="json")
            for item in task_bindings
        ],
    })
    first.workflow_store.save_mission(mission)

    paused = await first.start(
        mission.mission_id,
        workflow_id=workflow.workflow_id,
        review_mode="human_in_loop",
    )

    assert paused.status is WorkflowStatus.WAITING_REVIEW
    assert paused.current_step_id == "human_review"
    assert paused.get_step("human_review").status is StepStatus.WAITING_REVIEW
    assert "auto_review" in paused.execution_state["skippedStepIds"]
    assert _output(first, paused, "parse_contract")["contract_type"]
    assert _output(first, paused, "risk_detect")["risks"]
    assert _output(first, paused, "statute_retrieve")["sources"]
    statute_memory = first.memory_store.get(f"memory:{paused.run_id}:statute_retrieve")
    evidence_memory = first.memory_store.get(f"memory:{paused.run_id}:legal_evidence_match")
    assert statute_memory is not None and statute_memory.memory_type.value == "evidence"
    assert evidence_memory is not None and evidence_memory.memory_type.value == "evidence"
    assert paused.execution_state["memoryRefs"]["statute_retrieve"] == statute_memory.memory_id
    assert paused.execution_state["memoryRefs"]["legal_evidence_match"] == evidence_memory.memory_id
    assert any(
        event.event_type.value == "tool_called" and event.step_id == "statute_retrieve"
        for event in paused.trace
    )
    parallel_batches = [
        event.payload.get("stepIds")
        for event in paused.trace
        if event.event_type.value == "step_scheduled"
    ]
    assert any(set(batch or ()) == {"classify_clauses", "statute_retrieve"} for batch in parallel_batches)

    human_commit_id = f"commit:{paused.run_id}:human_review:0"
    committed_before = first.execution_value_store.get_node_commit(
        run_id=paused.run_id,
        commit_id=human_commit_id,
    )
    assert committed_before is not None
    assert committed_before["stage"] == "committed"
    assert first.memory_store.get(f"memory:{paused.run_id}:human_review") is None

    checkpoint_id = paused.execution_state["checkpointId"]
    checkpoint_before = first.checkpoint_store.load(
        run_id=paused.run_id,
        checkpoint_id=checkpoint_id,
    )
    checkpoint_version = first.checkpoint_store.latest_version(run_id=paused.run_id)
    state_json = json.dumps(paused.execution_state, ensure_ascii=False, sort_keys=True)
    checkpoint_json = json.dumps(checkpoint_before, ensure_ascii=False, sort_keys=True)
    assert _SECRET_MARKER not in state_json
    assert _SECRET_MARKER not in checkpoint_json
    assert "outputRefs" in checkpoint_before
    assert "contextRefs" in checkpoint_before

    repeated = await first.execute_prepared_run(paused.run_id)
    assert repeated.execution_state["checkpointId"] == checkpoint_id
    assert first.checkpoint_store.latest_version(run_id=paused.run_id) == checkpoint_version
    trace_ids_before = [event.event_id for event in repeated.trace]
    succeeded_before = {
        step_id: sum(
            event.event_type.value == "step_succeeded" and event.step_id == step_id
            for event in repeated.trace
        )
        for step_id in paused.completed_step_ids
    }
    provenance_before = first.provenance_store.load_ledger(
        run_id=paused.run_id,
        mission_id=paused.mission_id,
    )
    provenance_ids_before = {
        event.event_id
        for event in [
            *provenance_before.productions,
            *provenance_before.consumptions,
            *provenance_before.interactions,
        ]
    }
    close_owned(first)

    second = build_runtime(environment=environment)
    resumed_calls: list[str] = []
    for agent in second.agent_registry.all():
        original = agent.run
        agent_name = agent.profile.agent_name

        async def counted(context, *, _original=original, _agent_name=agent_name):
            resumed_calls.append(f"{context.step.step_id}:{_agent_name}")
            return await _original(context)

        agent.run = counted

    completed = await second.apply_review(
        ReviewDecision(
            runId=paused.run_id,
            stepId="human_review",
            decision=ReviewDecisionType.APPROVED,
            operationId="legal-golden-approve",
            reviewer="golden-reviewer",
            comment="approved after legal review",
        )
    )

    assert completed.status is WorkflowStatus.COMPLETED
    assert resumed_calls == ["report_generate:report_generate"]
    assert second.execution_value_store.get_node_commit(
        run_id=completed.run_id,
        commit_id=human_commit_id,
    ) == committed_before
    assert second.memory_store.get(f"memory:{completed.run_id}:human_review") is not None
    assert completed.output == {
        "outputRef": completed.execution_state["outputRefs"]["report_generate"]
    }
    report = _output(second, completed, "report_generate")
    assert report["report_markdown"]
    assert "approved after legal review" in report["report_markdown"]

    trace_ids_after = [event.event_id for event in completed.trace]
    assert len(trace_ids_after) == len(set(trace_ids_after))
    assert trace_ids_after[: len(trace_ids_before)] == trace_ids_before
    for step_id, count_before in succeeded_before.items():
        assert sum(
            event.event_type.value == "step_succeeded" and event.step_id == step_id
            for event in completed.trace
        ) == count_before

    provenance_after = second.provenance_store.load_ledger(
        run_id=completed.run_id,
        mission_id=completed.mission_id,
    )
    provenance_ids_after = [
        event.event_id
        for event in [
            *provenance_after.productions,
            *provenance_after.consumptions,
            *provenance_after.interactions,
        ]
    ]
    assert len(provenance_ids_after) == len(set(provenance_ids_after))
    assert provenance_ids_before.issubset(provenance_ids_after)
    close_owned(second)


async def test_legal_planner_uses_real_execution_capability_catalog(
    tmp_path, managed_default_runtime
):
    build_runtime, close_owned = managed_default_runtime
    runtime = build_runtime(environment=_environment(tmp_path))
    mission = runtime.create_mission(
        title="Review a software services contract and produce a legal report",
        domain="legal",
        intent="contract_review",
        workflow_id="legal_contract_review_v1",
        input={
            "userIntent": "parse and classify the contract, identify risks and evidence, then produce a report",
            "usePlanner": True,
            "planningDiversity": "stable",
            "planningSeed": 20260815,
        },
    )

    _, prepared = runtime.prepare_run(
        mission.mission_id,
        workflow_id="legal_contract_review_v1",
        review_mode="human_in_loop",
    )

    assert prepared.acg_blueprint is not None
    assert prepared.execution_state["planningSeed"] == 20260815
    assert prepared.execution_state["selectedCapabilities"]
    assert all(step.capability for step in prepared.steps)
    assert any(
        "Planner produced ACG" in event.observation
        for event in prepared.trace
    )
    close_owned(runtime)
