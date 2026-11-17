"""Real node/Hands integration for mandatory workspace observations, offline."""
import json

import pytest

from adapters.model_adapter import StructuredGenerationError
from adapters.agent_tools import AgentToolSession
from contracts.execution_evidence import (
    evaluate_run_workspace_observations, freeze_workspace_observations, workspace_observation_progress,
)
from test_unified_tools import Deny, GeneralAgent, context_for, node, stack as _hands_stack

stack = _hands_stack


def require_read(runner, step, *, path="note.txt", kind="file"):
    runner.run.input["workspaceBinding"] = {"workspaceId": "one", "grantId": "grant-one"}
    runner.run.steps = [step]
    freeze_workspace_observations(runner.run, [{"path": path, "kind": kind}])


def project_result(runner, step, result):
    runner.run.completed_step_ids = [step.step_id]
    runner.run.execution_state["outputRefs"] = {step.step_id: result["outputRef"]}


@pytest.mark.asyncio
async def test_valid_json_without_required_read_gets_feedback_and_continues_same_node(stack):
    runner, state, step, http = node(stack, GeneralAgent(), [
        {"answer": "already read"}, [("fs.read", {"path": "note.txt"})], {"answer": "file evidence"}])
    require_read(runner, step)
    result = await runner(step.step_id, state)
    project_result(runner, step, result)
    assert len(http.requests) == 3
    assert "Required gaps:" in http.requests[1]["messages"][-1]["content"]
    assert http.requests[1]["messages"][-1]["role"] == "user"
    assert len(stack.service.requests) == 1
    assert evaluate_run_workspace_observations(runner.run, runner.value_store) == ()
    call = result["toolCalls"][0]
    assert call["requestRef"] and call["receiptRef"] and call["workspaceId"] == "one"
    request = runner.value_store.get_output(run_id=runner.run.run_id, output_ref=call["requestRef"])["request"]
    receipt = runner.value_store.get_output(run_id=runner.run.run_id, output_ref=call["receiptRef"])
    assert call["executionId"].startswith("xhexec_")
    assert call["executionId"] != request["invocationId"] == receipt["invocationId"]
    # Commit replay does not create another model request or file read.
    await runner(step.step_id, state)
    assert len(http.requests) == 3 and len(stack.service.requests) == 1


@pytest.mark.asyncio
async def test_first_model_turn_receives_frozen_workspace_address_and_required_observations(stack):
    def inspect_workspace(payload):
        message = json.loads(payload["messages"][-1]["content"])
        assert message["requestType"] == "ExecutionRequest"
        assert "plannedTask" in message and "outputContract" in message
        assert all("WorkspaceExecutionContext" not in item["content"] for item in payload["messages"])
        assert message["workspace"]["trustClass"] == "runtime_authoritative"
        workspace = message["workspace"]["content"]
        assert workspace["status"] == "bound" and workspace["root"] == "."
        assert workspace["observationRequirements"][0]["path"] == "note.txt"
        return [("fs.read", {"path": "note.txt"})]

    runner, state, step, http = node(stack, GeneralAgent(), [inspect_workspace, {"answer": "file evidence"}])
    require_read(runner, step)
    runner.run.input["workspaceBinding"].update(workspaceRoot="C:/private/host-project")
    runner.task.input["workspaceBinding"] = {"workspaceId": "forged-workspace", "grantId": "forged-grant"}
    result = await runner(step.step_id, state)
    assert len(stack.service.requests) == 1 and len(http.requests) == 2
    assert stack.service.requests[0]["input"]["path"] == "note.txt"
    wire = json.dumps(http.requests, ensure_ascii=False)
    assert all(secret not in wire for secret in ["grant-one", "C:/private/host-project", "forged-grant"])
    assert runner.value_store.get_output(run_id=runner.run.run_id,
        output_ref=result["outputRef"]) == {"answer": "file evidence"}


@pytest.mark.asyncio
async def test_legacy_session_keeps_workspace_metadata_before_the_assigned_task(stack):
    prompt = "Inspect note.txt and report the verified evidence."

    def inspect_workspace(payload):
        assert payload["messages"][-1] == {"role": "user", "content": prompt}
        message = json.loads(payload["messages"][-2]["content"])
        assert message["requestType"] == "WorkspaceExecutionContext"
        assert message["workspace"]["content"]["root"] == "."
        assert message["workspace"]["trustClass"] == "runtime_authoritative"
        return [("fs.read", {"path": "note.txt"})]

    runner, _, step, http = node(stack, GeneralAgent(), [inspect_workspace, {"answer": "file evidence"}])
    require_read(runner, step)
    session = AgentToolSession(context_for(runner, step))
    result = await session.generate_json(prompt=prompt, schema=step.output_spec)

    assert result.data == {"answer": "file evidence"}
    assert len(http.requests) == 2 and len(stack.service.requests) == 1
    assert http.requests[1]["messages"][:3] == http.requests[0]["messages"]
    assert [item["role"] for item in http.requests[1]["messages"][3:]] == ["assistant", "tool"]
    assert "grant-one" not in json.dumps(http.requests, ensure_ascii=False)


@pytest.mark.asyncio
async def test_repeated_no_tool_candidates_fail_on_unchanged_observation_state(stack):
    runner, state, step, http = node(stack, GeneralAgent(), [{"answer": "pretend"}] * 3)
    require_read(runner, step)
    with pytest.raises(StructuredGenerationError) as error:
        await runner(step.step_id, state)
    assert error.value.code == "AGENT_NO_PROGRESS"
    assert len(http.requests) == 2 and not stack.service.requests
    assert not [c for c in runner.value_store.list_node_commits(run_id=runner.run.run_id)
                if c.get("stage") == "committed"]


@pytest.mark.asyncio
@pytest.mark.parametrize("defect", ["wrong_file", "failed_read"])
async def test_unrelated_or_failed_reads_do_not_satisfy_obligation(stack, defect):
    path = "wrong.txt" if defect == "wrong_file" else "note.txt"
    runner, state, step, http = node(stack, GeneralAgent(), [
        [("fs.read", {"path": path})], {"answer": "pretend"}, {"answer": "pretend"}, {"answer": "pretend"}])
    require_read(runner, step)
    stack.service.failed = defect == "failed_read"
    with pytest.raises(StructuredGenerationError) as error:
        await runner(step.step_id, state)
    assert error.value.code == "AGENT_NO_PROGRESS"
    assert len(http.requests) == 3 and len(stack.service.requests) == 1


@pytest.mark.asyncio
async def test_listing_returns_to_acg_with_remaining_read_gap(stack):
    runner, state, step, _ = node(stack, GeneralAgent(), [
        [("fs.list", {"path": "."})], {"answer": "directory contains note.txt"}])
    require_read(runner, step, path=".", kind="directory")
    result = await runner(step.step_id, state)
    project_result(runner, step, result)
    assert evaluate_run_workspace_observations(runner.run, runner.value_store) == (
        "workspace_observation_incomplete:0",)


@pytest.mark.asyncio
async def test_complete_file_batch_returns_to_acg_with_unlisted_directory_gap(stack):
    def acquire_batch(payload):
        instructions = "\n".join(item["content"] for item in payload["messages"] if item["role"] == "system")
        assert "one useful work unit" in instructions
        assert "existing output contract" in instructions and "remaining gaps" in instructions
        return [("fs.read", {"path": "note.txt"})]

    partial = {"answer": "Read note.txt. The root directory is not enumerated; further coverage remains."}
    runner, state, step, http = node(stack, GeneralAgent(), [acquire_batch, partial])
    require_read(runner, step, path=".", kind="directory")
    result = await runner(step.step_id, state)
    project_result(runner, step, result)

    assert len(http.requests) == 2 and len(stack.service.requests) == 1
    assert result["toolCalls"][0]["receiptRef"]
    assert runner.value_store.get_output(run_id=runner.run.run_id, output_ref=result["outputRef"]) == partial
    assert workspace_observation_progress(runner.run, runner.value_store)[0]["missingListings"] == ["."]
    assert evaluate_run_workspace_observations(runner.run, runner.value_store) == (
        "workspace_observation_incomplete:0",)
    await runner(step.step_id, state)
    assert len(http.requests) == 2 and len(stack.service.requests) == 1


@pytest.mark.asyncio
async def test_listing_and_reading_files_satisfies_directory_observation(stack):
    runner, state, step, http = node(stack, GeneralAgent(), [
        [("fs.list", {"path": "."})], [("fs.read", {"path": "note.txt"})], {"answer": "read all"}])
    require_read(runner, step, path=".", kind="directory")
    result = await runner(step.step_id, state)
    project_result(runner, step, result)
    assert evaluate_run_workspace_observations(runner.run, runner.value_store) == ()
    wire = json.dumps(http.requests, ensure_ascii=False)
    assert "grant-one" not in wire and "agentos_dispatch" not in wire


@pytest.mark.asyncio
@pytest.mark.parametrize("attempt", ["unknown_tool", "bad_arguments", "permission_denied"])
async def test_failed_tool_attempts_return_safe_committed_outcomes_to_acg(stack, attempt):
    name, arguments = "fs.read", {"path": 123}
    if attempt == "unknown_tool":
        name, arguments = "invented", {}
    elif attempt == "permission_denied":
        stack.permissions.policy = Deny()
        name, arguments = "shell.exec", {"command": "mock only"}
    runner, state, step, http = node(stack, GeneralAgent(), [
        [(name, arguments)], {"answer": "failed attempt observed"}])
    result = await runner(step.step_id, state)
    outcomes = [call for call in result["toolCalls"] if call.get("status") == "failed"]
    assert len(outcomes) == 1 and outcomes[0]["errorCode"]
    assert not outcomes[0].get("receiptRef") and "arguments" not in outcomes[0]
    assert not stack.service.requests and len(http.requests) == 2
