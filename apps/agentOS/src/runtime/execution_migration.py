"""ACG 执行底座迁移期间对外稳定暴露的错误类型。"""

from __future__ import annotations


class ExecutionEngineMigratingError(RuntimeError):
    """新执行底座尚未接回 runtime 时，在改变 run 状态前终止 ACG 执行请求。

    该错误码是 API 合同的一部分：调用方可据此提示迁移状态，而不会把一个未真正开始的
    run 标记为运行中或失败。待 runtime 接入新的图、检查点与审核恢复后再删除拦截。
    """

    code = "ACG_EXECUTION_ENGINE_MIGRATING"

    def __init__(self, run_id: str | None = None) -> None:
        self.run_id = run_id
        suffix = f" for run {run_id}" if run_id else ""
        super().__init__("The ACG execution engine is migrating to the AgentOS LangGraph base" + suffix)


__all__ = ["ExecutionEngineMigratingError"]
