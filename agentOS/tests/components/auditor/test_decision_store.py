"""审计决定持久化与归属校验测试。"""

from __future__ import annotations

import components.auditor as auditor
from datetime import timedelta
from contracts.governance import PolicyDecision


def test_sqlite_decision_store_persists_and_verifies_step_ownership(tmp_path) -> None:
    """重启后仍只能由原 run 与原步骤读取同一份不可变审计决定。"""
    store_type = getattr(auditor, "SQLiteDecisionStore", None)

    assert store_type is not None
    first = store_type(db_path=tmp_path / "decisions.sqlite3")
    decision = PolicyDecision(
        decisionId="decision:audit:run-a:extract",
        subjectRef="pending:run-a:extract",
        outcome="review",
        policyRefs=["execution-risk.v1"],
        rationale="audit score=7",
    )
    first.save(run_id="run-a", step_id="extract", decision=decision)
    first.close()

    reopened = store_type(db_path=tmp_path / "decisions.sqlite3")
    restored = reopened.assert_decision(
        run_id="run-a",
        step_id="extract",
        decision_ref=decision.decision_id,
        outcomes={"review"},
    )

    assert restored.outcome == "review"
    try:
        reopened.assert_decision(
            run_id="run-a",
            step_id="summarize",
            decision_ref=decision.decision_id,
            outcomes={"review"},
        )
    except ValueError as exc:
        assert "belongs to step extract" in str(exc)
    else:
        raise AssertionError("cross-step decision access must fail")
    reopened.close()


def test_decision_store_reuses_same_logical_decision_after_retry(tmp_path) -> None:
    """同一节点重试产生不同时间戳时，应复用首次决定而不能阻断恢复。"""
    store_type = getattr(auditor, "SQLiteDecisionStore", None)
    assert store_type is not None
    store = store_type(db_path=tmp_path / "decisions.sqlite3")
    original = PolicyDecision(
        decisionId="decision:audit:run-a:extract",
        subjectRef="pending:run-a:extract",
        outcome="allow",
        policyRefs=["execution-risk.v1"],
        rationale="audit score=0",
    )
    retried = original.model_copy(
        update={"decided_at": original.decided_at + timedelta(seconds=1)}
    )

    store.save(run_id="run-a", step_id="extract", decision=original)
    store.save(run_id="run-a", step_id="extract", decision=retried)

    assert store.assert_decision(
        run_id="run-a",
        step_id="extract",
        decision_ref=original.decision_id,
        outcomes={"allow"},
    ).decided_at == original.decided_at
    store.close()
