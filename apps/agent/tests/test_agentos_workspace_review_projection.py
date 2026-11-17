from copy import deepcopy

from app.api.agentos_v2 import project_graph
from contracts.workflow import RuntimeRunRecord


def test_graph_endpoint_only_joins_persisted_matching_review_facts():
    fact = {"schemaVersion": 1, "round": 2, "graphVersion": 3, "status": "reading",
            "gaps": {"missingReadCount": 9, "missingListingCount": 1, "unsupportedEntryCount": 0},
            "rounds": [{"round": 1, "graphVersion": 2, "action": "revise", "addedStepIds": ["read-2"],
                        "observationRef": "observation:1", "traceRefs": ["trace:1"]}]}
    run = RuntimeRunRecord(run_id="review-run", mission_id="review-mission", workflow_id="review-workflow",
                           domain="general", runtime_engine="acg", acg_blueprint={"graphId": "g", "version": 3,
                            "nodes": [{"nodeId": "read-2"}], "edges": []},
                           execution_state={"workspaceReview": fact})
    before = deepcopy(run.model_dump())
    result = project_graph(run)
    assert result["workspaceReview"]["round"] == 2
    assert result["workspaceReview"]["gaps"]["missingReadCount"] == 9
    assert result["workspaceReview"]["rounds"][0]["observationRef"] == "observation:1"
    assert result["nodes"] == [{"nodeId": "read-2"}]
    assert result["edges"] == []
    assert run.model_dump() == before
