"""WKN ACG 向 AgentOS 身份控制面发布生命周期事实的最小端口。"""

from __future__ import annotations

from typing import Any, Protocol


class AcgIdentityLifecyclePort(Protocol):
    """执行内核只依赖此端口，不依赖 V2 Repository 或具体数据库。"""

    def new_task_id(self) -> str: ...
    def on_task_created(self, task: Any) -> None: ...
    def new_run_id(self, task_id: str) -> str: ...
    def on_run_prepared(
        self,
        task: Any,
        run: Any,
        blueprint: Any,
        task_plan: Any,
        task_node_bindings: Any,
    ) -> None: ...
    def on_graph_patch_prepared(
        self,
        task: Any,
        old_run: Any,
        new_run: Any,
        blueprint: Any,
        task_plan: Any,
        task_node_bindings: Any,
        patch_id: str,
    ) -> None: ...
    def on_blueprint_revised(
        self,
        run: Any,
        blueprint: Any,
        task_plan_patch: Any | None = None,
    ) -> None: ...
    def ensure_attempt(self, run: Any, step_id: str, attempt_number: int) -> str: ...
    def on_resource_bound(
        self, *, attempt_id: str, binding: Any, agent_id: str, model_id: str
    ) -> None: ...
    def on_step_started(self, *, run_id: str, attempt_id: str, step_id: str) -> str: ...
    def on_step_succeeded(
        self,
        *,
        run_id: str,
        attempt_id: str,
        step_execution_id: str,
        result: dict[str, Any],
    ) -> None: ...
    def on_step_failed(
        self,
        *,
        run_id: str,
        attempt_id: str,
        step_execution_id: str,
        reason: str,
    ) -> None: ...
    def on_step_cancelled(
        self,
        *,
        run_id: str,
        attempt_id: str,
        step_execution_id: str,
        reason: str,
    ) -> None: ...
    def on_run_finished(self, run_id: str, status: str) -> None: ...
    def on_run_superseded(
        self, run_id: str, new_run_id: str, patch_id: str
    ) -> None: ...


__all__ = ["AcgIdentityLifecyclePort"]
