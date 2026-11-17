"""Growing operator history keeps identity fences without a mission round quota."""
import asyncio

import pytest

from contracts.runtime_planning import RuntimePlanningDecision, RuntimeUserInput
from contracts.workflow import WorkflowStatus, utc_now
from runtime.planning_interaction import PlannerAnswerRequest, RuntimePlanningInteraction
from runtime.planning_operations import TaskOperationPreviewRequest
from runtime.review import ReviewConflictError
from support.stores.memory_workflow_store import MemoryWorkflowStore
from test_planning_loop import Planner, attach, prepared


def test_memory_planning_inbox_retains_all_inputs_and_rejects_operation_rebinding():
    store = MemoryWorkflowStore()
    for index in range(96):
        store.save_planning_input("run", f"input:{index}", {"content": f"requirement {index}"})
    assert len(store.list_planning_inputs("run")) == 96
    store.save_planning_input("run", "input:0", {"content": "requirement 0"})
    with pytest.raises(ValueError, match="operation conflict"):
        store.save_planning_input("run", "input:0", {"content": "changed requirement"})
    assert len(store.list_planning_inputs("run")) == 96


def test_operator_can_confirm_another_input_after_a_large_durable_history(tmp_path):
    runtime, _, run = prepared(tmp_path)
    attach(runtime, Planner(lambda observation, plan: RuntimePlanningDecision(
        observationId=observation.fingerprint(), action="wait", reason="await current operator input")))
    paused = asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert paused.status == WorkflowStatus.WAITING_REVIEW
    for index in range(96):
        item = RuntimeUserInput(sourceRunId=run.run_id, operationId=f"input:{index}",
            content=f"confirmed requirement {index}", submittedAt=utc_now())
        runtime.workflow_store.save_planning_input(run.run_id, item.operation_id,
            item.model_dump(by_alias=True, mode="json"))
    proposal = asyncio.run(RuntimePlanningInteraction(runtime).preview_operation(run.run_id,
        TaskOperationPreviewRequest(kind="user_input", operationId="next-confirmed-input",
            content="one further source requirement", permission="task_collaboration")))
    assert proposal["action"]["kind"] == "user_input"
    assert len(runtime.workflow_store.list_planning_inputs(run.run_id)) == 96


def test_more_than_thirty_two_real_clarification_rounds_can_finish(tmp_path):
    runtime, agent, run = prepared(tmp_path)

    def choose(observation, plan):
        if len(observation.human_answers) < 34:
            return RuntimePlanningDecision(observationId=observation.fingerprint(), action="wait",
                reason="ask the next authorized source question", question={"prompt": "Confirm the next source choice"})
        return RuntimePlanningDecision(observationId=observation.fingerprint(),
            action="continue" if observation.remaining_step_ids else "complete", reason="all source questions answered")

    planner = Planner(choose)
    attach(runtime, planner)
    interaction = RuntimePlanningInteraction(runtime)
    for index in range(34):
        paused = asyncio.run(runtime.execute_prepared_run(run.run_id))
        assert paused.status == WorkflowStatus.WAITING_REVIEW
        question = interaction.view(run.run_id)["question"]
        request = PlannerAnswerRequest(operationId=f"answer:{index}", questionId=question["questionId"],
            answer=f"confirmed source choice {index}", expectedRevision=paused.runtime_revision)
        ready = asyncio.run(interaction.answer(run.run_id, request))
        assert asyncio.run(interaction.answer(run.run_id, request)).runtime_revision == ready.runtime_revision
    result = asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert result.status == WorkflowStatus.COMPLETED and agent.calls == ["A", "B"]
    assert len(planner.observations[-1].human_answers) == 34
    with pytest.raises(ReviewConflictError, match="already used"):
        asyncio.run(interaction.answer(run.run_id, request.model_copy(update={"answer": "changed answer"})))
