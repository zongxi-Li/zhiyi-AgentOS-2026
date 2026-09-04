"""Scale and restore proof for the existing ACGExecutionGraph runtime."""

from __future__ import annotations

import asyncio

from components.executor.graph import ACGExecutionGraph, ACGExecutionState
from contracts import stable_checksum


ROOTS = tuple(f"root-{index:03d}" for index in range(500))
LEAVES = tuple(f"leaf-{index:03d}" for index in range(500))
NODES = ROOTS + LEAVES
EDGES = tuple(zip(ROOTS, LEAVES))


async def _execute(state: ACGExecutionState) -> tuple[ACGExecutionState, list[tuple[str, ...]]]:
    graph = ACGExecutionGraph(nodes=NODES, edges=EDGES)
    ready_progression: list[tuple[str, ...]] = []

    async def noop(step_id: str, current: ACGExecutionState):
        return {"outputSummary": step_id}

    async for event in graph.astream(state, noop):
        if event["type"] == "nodes_scheduled":
            ready_progression.append(tuple(event["stepIds"]))
    return state, ready_progression


def _summary(state: ACGExecutionState) -> dict[str, object]:
    return {
        "completed": state.completed_step_ids,
        "skipped": state.skipped_step_ids,
        "active": state.active_step_ids,
        "summaries": state.output_summaries,
    }


def test_thousand_node_graph_has_stable_ready_progression_and_summary() -> None:
    hashes = []
    for _ in range(3):
        state, progression = asyncio.run(
            _execute(ACGExecutionState(runId="scale-run", graphId="scale-1000"))
        )
        assert progression == [ROOTS, LEAVES]
        assert len(state.completed_step_ids) == 1000
        assert len(set(state.completed_step_ids)) == 1000
        assert state.active_step_ids == []
        assert state.skipped_step_ids == []
        hashes.append(stable_checksum(_summary(state)))

    assert len(set(hashes)) == 1


def test_thousand_node_checkpoint_restore_matches_fault_free_summary() -> None:
    complete, _ = asyncio.run(
        _execute(ACGExecutionState(runId="scale-run", graphId="scale-1000"))
    )
    restored_state = ACGExecutionState(
        runId="scale-run",
        graphId="scale-1000",
        completedStepIds=list(ROOTS),
        outputSummaries={step_id: step_id for step_id in ROOTS},
    )
    restored, progression = asyncio.run(_execute(restored_state))

    assert progression == [LEAVES]
    assert stable_checksum(_summary(restored)) == stable_checksum(_summary(complete))
