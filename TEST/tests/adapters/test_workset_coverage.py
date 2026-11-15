import asyncio
from copy import deepcopy

import pytest

from adapters.model.native import NativeGeneralAgent
from adapters.model_adapter import StructuredGenerationError
from components.communicator.contracts import ContextPack
from components.content import ContentWorksetSession, SQLiteContentManifestStore
from contracts.content import ContentKind, WorksetSpec
from contracts.workflow import RuntimeMissionRecord, RuntimeRunRecord, WorkflowDefinition, WorkflowStep
from service.agents.base import AgentOutput, AgentRunContext


def context():
    task = RuntimeMissionRecord(missionId="mission-workset", title="Inspect every constraint")
    run = RuntimeRunRecord(missionId=task.mission_id, workflowId="native", domain="general", runtimeEngine="acg")
    return AgentRunContext(task=task, run=run,
        workflow=WorkflowDefinition(workflowId="native", name="native", domain="general", runtimeEngine="acg"),
        step=WorkflowStep(stepId="review", name="review", agentName="native_general_agent", capability="verification"),
        memory=[], contextPack=ContextPack(runId=run.run_id, stepId="review",
            data={"constraints": ["Never write externally"]}, evidenceRefs=["evidence:1"]), commitId="commit")


@pytest.mark.parametrize("error", ["MODEL_INPUT_BUDGET_EXCEEDED", "MODEL_OUTPUT_EXHAUSTED"])
def test_recursive_splits_cover_absolute_unicode_ranges_with_distinct_map_and_reduce_keys(error):
    class Agent(NativeGeneralAgent):
        def __init__(self):
            super().__init__()
            self.calls = []

        async def run(self, ctx):
            key, payload = next(iter(ctx.context_pack.source_data.items()))
            self.calls.append((ctx.commit_id, key, deepcopy(payload)))
            assert ctx.context_pack.data["constraints"] == ["Never write externally"]
            assert ctx.context_pack.evidence_refs == ["evidence:1"]
            if key.startswith("materialFragment:"):
                if len(payload["content"]) > 2:
                    raise StructuredGenerationError(error, "split this unit")
                parts = [payload["content"]]
            else:
                parts = payload["left"]["parts"] + payload["right"]["parts"]
            return AgentOutput(output={"parts": parts})

    agent = Agent()
    ctx = context()
    unit = {"sequence": 7, "content": "甲乙丙丁戊己庚辛壬", "characterRange": [20, 29], "rangeUnit": "unicode-codepoints"}
    result = asyncio.run(agent._execute_workset_unit(ctx, unit))
    assert "".join(result.output["parts"]) == unit["content"]
    leaves = [payload for _, key, payload in agent.calls if key.startswith("materialFragment:") and len(payload["content"]) <= 2]
    assert leaves[0]["characterRange"][0] == 20 and leaves[-1]["characterRange"][1] == 29
    assert all(a["characterRange"][1] == b["characterRange"][0] for a, b in zip(leaves, leaves[1:]))
    assert len({key for key, _, _ in agent.calls}) == len(agent.calls)
    assert ctx.context_pack.source_data == {}  # Workset contexts never mutate the parent.


def test_capacity_failure_after_tool_actions_does_not_split_and_repeat_effects():
    class Agent(NativeGeneralAgent):
        calls = 0

        async def run(self, ctx):
            self.calls += 1
            raise StructuredGenerationError("MODEL_INPUT_BUDGET_EXCEEDED", "tool result exceeds budget",
                                            audit={"toolActionsExecuted": 1})

    agent = Agent()
    with pytest.raises(StructuredGenerationError):
        asyncio.run(agent._execute_workset_unit(context(), {"sequence": 0, "content": "abcdef"}))
    assert agent.calls == 1


def test_sealing_requires_all_fragments_and_persisted_coverage_survives_restore(tmp_path):
    store = SQLiteContentManifestStore(tmp_path / "coverage.sqlite3")
    material = store.create_from_bytes(content="甲乙丙丁".encode(), kind=ContentKind.MATERIAL,
                                       owner_type="user", owner_id="u", max_fragment_bytes=6)
    kwargs = dict(store=store, spec=WorksetSpec(sourceManifestRefs=[material.manifest_id]),
                  run_id="run", step_id="review", commit_id="commit")
    session = ContentWorksetSession(**kwargs)
    units = list(session.pending_units())
    assert len(units) == 2
    session.persist_map_result(0, {"output": {"covered": True}}, unit=units[0])
    with pytest.raises(ValueError, match="uncovered"):
        session.seal()
    restored = ContentWorksetSession(**kwargs)
    assert [unit["sequence"] for unit in restored.pending_units()] == [1]
    coverage = restored.mapped_results()[0]["_worksetCoverage"]
    assert coverage["fragmentRef"] == units[0]["fragmentRef"]
    assert coverage["characterRange"] == [0, 2]
    restored.persist_map_result(1, {"output": {"covered": True}}, unit=units[1])
    assert restored.seal().sealed
    with pytest.raises(ValueError, match="outside"):
        restored.persist_map_result(2, {"output": {}})
    store.close()
