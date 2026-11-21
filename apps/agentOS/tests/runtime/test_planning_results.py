"""All committed outputs remain discoverable and readable by frozen address."""
import asyncio
from copy import deepcopy

import pytest

from components.executor.graph import ACGSuperstepError
from contracts import stable_checksum
from contracts.runtime_planning import RuntimePlanningDecision, RuntimePlanningObservation
from runtime.planning_results import PlanningResultReader, read_planning_result_page
from runtime.state_persistence import acg_execution_state_from_run
from service.agents.base import AgentOutput
from test_planning_loop import Agent, Planner, attach, prepared, runtime_at


class FindingsAgent(Agent):
    async def run(self, context):
        if context.step.step_id == "A":
            self.calls.append("A")
            return AgentOutput(output={"task_summary": "precise finding " * 300,
                "constraints": ["preserve evidence"], "assumptions": ["intentional omission is possible"],
                "open_questions": [f"unresolved question {index}" for index in range(30)]})
        return await super().run(context)


@pytest.fixture
def committed(tmp_path):
    runtime, agent, run = prepared(tmp_path, FindingsAgent())
    planner = Planner()
    attach(runtime, planner)
    final = asyncio.run(runtime.execute_prepared_run(run.run_id))
    return runtime, agent, final, planner.observations[0]


def test_index_contains_all_result_identities_optional_fields_sizes_and_unresolved_addresses(committed):
    runtime, _, final, observation = committed
    assert [entry.step_id for entry in observation.committed_results] == ["A", "B"]
    index = observation.committed_results[0]
    assert index.output_ref == final.execution_state["outputRefs"]["A"]
    assert index.objective == "do A" and index.task_key == "step:A" and index.title == "A"
    assert index.readable and index.commit_id and index.audit_ref
    assert "open_questions" in index.unresolved_fields
    field = next(field for field in index.fields if field.name == "open_questions")
    assert field.purpose == "unresolved" and field.item_count == 30 and field.byte_length > 0
    output = runtime.execution_value_store.get_output(run_id=final.run_id, output_ref=index.output_ref)
    assert index.output_checksum == stable_checksum(output)
    assert output["task_summary"] not in observation.model_dump_json()
    assert "unresolved question 29" not in observation.model_dump_json()


@pytest.mark.parametrize("field", ["task_summary", "open_questions"])
def test_pages_reconstruct_full_string_and_optional_array_using_existing_broker(committed, field):
    runtime, _, final, observation = committed
    reader = PlanningResultReader(services=runtime, observation=observation)
    expected = runtime.execution_value_store.get_output(run_id=final.run_id,
        output_ref=observation.committed_results[0].output_ref)[field]
    value, cursor, page_number = ("" if isinstance(expected, str) else []), None, 0
    while True:
        page = asyncio.run(reader.read_page(step_id="A", fields=[field], cursor=cursor,
            page_tokens=70, operation_id=f"page-{field}-{page_number}"))
        assert page["tokensDelivered"] <= 70 and page["graphVersion"] == observation.graph_version
        value += page["data"][field]
        cursor = page["nextCursor"]
        page_number += 1
        if cursor is None:
            break
    assert value == expected and page_number > 1


def test_read_receipt_replays_across_reader_restart_without_duplicating_source_body(committed, tmp_path):
    runtime, _, _, observation = committed
    arguments = dict(step_id="A", fields=["task_summary"], page_tokens=50, operation_id="frozen-page")
    page = read_planning_result_page(runtime, observation, **arguments)
    reopened, _ = runtime_at(tmp_path)
    assert read_planning_result_page(reopened, observation, **arguments) == page
    key = f"planning-result-read:{observation.fingerprint()}:{stable_checksum('frozen-page')}"
    receipt = reopened.execution_value_store.get_tool_value(run_id=observation.run_id, key=key)
    assert receipt["dataChecksum"] == stable_checksum(page["data"])
    assert "data" not in receipt and "precise finding" not in str(receipt)
    with pytest.raises(ValueError, match="conflicts"):
        read_planning_result_page(reopened, observation, **{**arguments, "fields": ["constraints"]})


@pytest.mark.parametrize("change", ["step-ref", "unindexed", "field", "audit", "owner", "checksum"])
def test_reads_cannot_escape_frozen_committed_index_or_audit_ownership(committed, change):
    runtime, _, _, observation = committed
    arguments = dict(step_id="A", fields=["task_summary"], operation_id="invalid-read")
    if change == "step-ref":
        arguments["output_ref"] = observation.committed_results[1].output_ref
    elif change == "unindexed":
        arguments["step_id"] = "not-committed"
    elif change == "field":
        arguments["fields"] = ["not-an-output-field"]
    else:
        updates = {"audit": {"audit_ref": "unrelated-audit"}, "owner": {"source_run_id": "another-run"},
            "checksum": {"output_checksum": "0" * 64}}[change]
        entries = list(observation.committed_results)
        entries[0] = entries[0].model_copy(update=updates)
        observation = observation.model_copy(update={"committed_results": tuple(entries)})
    with pytest.raises(ValueError):
        read_planning_result_page(runtime, observation, **arguments)


def test_cursor_is_bound_to_source_fields_and_observation_version(committed):
    runtime, _, _, observation = committed
    page = read_planning_result_page(runtime, observation, step_id="A", fields=["task_summary"],
        page_tokens=50, operation_id="first")
    assert page["nextCursor"]
    other_field = observation.committed_results[1].fields[0].name
    for target, fields in (("A", ["open_questions"]), ("B", [other_field])):
        with pytest.raises(ValueError, match="cursor belongs"):
            read_planning_result_page(runtime, observation, step_id=target, fields=fields,
                cursor=page["nextCursor"], operation_id="different-source")
    changed = observation.model_copy(update={"graph_version": observation.graph_version + 1})
    with pytest.raises(ValueError, match="cursor belongs"):
        read_planning_result_page(runtime, changed, step_id="A", fields=["task_summary"],
            cursor=page["nextCursor"], operation_id="different-version")


def test_frozen_observation_never_discovers_later_completed_results(committed):
    runtime, _, final, observation = committed
    first = observation.model_copy(update={"steps": observation.steps[:1],
        "committed_results": observation.committed_results[:1], "remaining_step_ids": ("B",)})
    with pytest.raises(ValueError, match="one indexed"):
        read_planning_result_page(runtime, first, step_id="B", operation_id="later-result")
    assert final.get_step("B").status.value == "completed"
    read_planning_result_page(runtime, first, step_id="A", fields=["constraints"], operation_id="old-result")


def test_successor_output_reuses_original_commit_and_audit_without_forging_ownership(tmp_path):
    runtime, _, run = prepared(tmp_path, FindingsAgent(fail=True))
    attach(runtime, Planner(lambda observation, _: RuntimePlanningDecision(observationId=observation.fingerprint(),
        action="abort", reason="record failed suffix")))
    with pytest.raises(ACGSuperstepError):
        asyncio.run(runtime.execute_prepared_run(run.run_id))
    successor = runtime.prepare_single_step_retry(run.run_id, "B")
    observation = runtime.runtime_planning_coordinator.observe(successor, acg_execution_state_from_run(successor), "resume")
    index = observation.committed_results[0]
    assert index.source_run_id == run.run_id and index.output_ref != index.source_output_ref
    page = read_planning_result_page(runtime, observation, output_ref=index.output_ref,
        fields=["constraints"], operation_id="reused-output")
    assert page["data"] == {"constraints": ["preserve evidence"]}
    assert page["sourceRunId"] == run.run_id


def test_empty_index_does_not_change_legacy_observation_fingerprint():
    observation = RuntimePlanningObservation(missionId="mission", runId="run", graphId="graph",
        graphVersion=1, planVersion=1, wakeReason="exhausted", goal="goal", steps=(), remainingStepIds=())
    assert "committedResults" not in observation.model_dump(by_alias=True, mode="json")
    old = deepcopy(observation.model_dump(by_alias=True, mode="json"))
    assert RuntimePlanningObservation.model_validate(old).fingerprint() == observation.fingerprint()


def test_pending_review_result_is_diagnostic_context_without_approving_completion(committed):
    runtime, _, final, observation = committed
    source = observation.committed_results[0].model_copy(update={
        "readable": False, "unavailable_reason": "REVIEW_UNRESOLVED"})
    diagnostic = observation.model_copy(update={"committed_results": (source, *observation.committed_results[1:])})
    page = read_planning_result_page(runtime, diagnostic, step_id="A", fields=["constraints"],
        operation_id="candidate-diagnostic")
    assert page["data"]["constraints"] == ["preserve evidence"]
    assert page["status"] == "review_pending" and page["trust"] == "agent_generated"
    assert runtime.workflow_store.get_run(final.run_id).execution_state["outputRefs"] == final.execution_state["outputRefs"]
