"""Graph selection preserves dependency, branch, and admission boundaries."""

from components.scheduler import dependency_status, select_ready_steps


def test_frontier_excludes_active_steps_and_waiting_dependencies():
    assert select_ready_steps(
        ["done", "active", "first", "next", "control"],
        step_ids={"done", "active", "first", "next"},
        predecessors={"first": {"done"}, "next": {"first"}},
        completed={"done"}, active={"active"},
    ) == ("first",)


def test_conditional_join_waives_only_its_own_unselected_branch():
    assert dependency_status({"a", "b"}, [{"a", "b"}], {"a"}, {"b"}) == "ready"
    assert dependency_status({"a", "b", "outside"}, [{"a", "b"}], {"a"}, {"b", "outside"}) == "skip"
    assert dependency_status({"a", "b"}, [{"a", "b"}], set(), {"a", "b"}) == "skip"


def test_capacity_limit_preserves_graph_order_without_starting_dependents():
    kwargs = dict(step_ids={"a", "b", "c"}, predecessors={"c": {"a"}}, completed=())
    assert select_ready_steps(["b", "a", "c"], limit=1, **kwargs) == ("b",)
    assert select_ready_steps(["b", "a", "c"], limit=0, **kwargs) == ()
