"""记忆部件的公共 Facade。"""

from copy import deepcopy
from datetime import datetime, timezone

from contracts.memory import MemoryPolicy, MemoryQuery, MemoryRecord, MemoryType
from components.communicator.contracts import estimate_tokens

from .admission import admitted
from .algorithms import rerank_memories
from .retrieval import retrieve
from .models import WorkingMemory
from .store import MemoryStore


class MemoryService:
    """提供经策略准入的内存写入、确定性检索和工作记忆构造。

    默认使用进程内 ``MemoryStore``，不提供事务、持久化或并发锁；调用者若需
    跨线程/进程一致性，应注入具备相应语义的存储实现。
    """

    def __init__(self, store: MemoryStore | None = None) -> None:
        self._store = store or MemoryStore()

    def remember(self, record: MemoryRecord, policy: MemoryPolicy | None = None) -> bool:
        """在 ``record`` 符合可选策略时写入并返回 ``True``。

        拒绝时返回 ``False`` 且不修改存储；接受时覆盖规则由底层存储定义。该
        方法不检查容量或过期，存储错误直接上抛，复杂度由注入存储决定。
        """
        if not admitted(record, policy):
            return False
        self._store.put(record)
        return True

    def search(self, query: MemoryQuery) -> list[MemoryRecord]:
        """执行本地元数据过滤后按重要度稳定重排并返回结果副本。

        检索不使用向量模型或外部索引，输入查询不会被修改；复杂度包含线性过滤
        和排序，即 O(n log n)，底层存储读取异常会直接上抛。
        """
        return rerank_memories(retrieve(self._store.values(), query))

    def recall_for_step(
        self,
        *,
        run_id: str,
        step_id: str,
        query: str,
        memory_types: list[MemoryType] | None = None,
        limit: int = 10,
        token_budget: int | None = None,
    ) -> list[MemoryRecord]:
        """为一个执行步骤召回仅属于当前 run 且尚未过期的记忆。

        ``run_id`` 被固定为查询 scope，因而调用者不能以“无 scope”的检索间接得到
        其它运行内容。``step_id`` 是明确的调用边界；类别、数量和 Token 预算都由
        节点已冻结的记忆策略传入。预算只会丢弃放不下的完整记录，绝不截断正文或
        放宽限制；负数预算属于无效策略并立即拒绝。
        """
        records = self.search(
            MemoryQuery(
                query=query,
                scope=run_id,
                memoryTypes=memory_types or [],
                limit=limit,
            )
        )
        now = datetime.now(timezone.utc)
        live_records = [
            record
            for record in records
            if record.expires_at is None or record.expires_at > now
        ]
        if token_budget is None:
            return live_records
        if token_budget < 0:
            raise ValueError("memory token_budget must be non-negative")
        selected: list[MemoryRecord] = []
        used_tokens = 0
        for record in live_records:
            record_tokens = estimate_tokens(record.content)
            if used_tokens + record_tokens > token_budget:
                continue
            selected.append(record)
            used_tokens += record_tokens
        return selected

    def remember_step_output(
        self,
        *,
        run_id: str,
        step_id: str,
        output: dict[str, object],
        policy: MemoryPolicy | None = None,
    ) -> MemoryRecord | None:
        """把已通过输出合同的受控字段写为当前 run 的情节记忆。

        调用方必须在调用前完成输出 schema 校验与字段白名单裁剪；该服务只接收
        ``controlled`` 结果，绝不从 Agent 原始响应或 WorkflowRun 回填正文。若准入
        策略拒绝情节记忆，则返回 ``None``，让运行器不生成虚假的 memoryRef。
        """
        record = MemoryRecord(
            memoryId=f"memory:{run_id}:{step_id}",
            memoryType=MemoryType.EPISODIC,
            content=deepcopy(dict(output)),
            scope=run_id,
            tags=["execution", step_id],
        )
        return record if self.remember(record, policy) else None

    def working_from_run(self, run: object) -> WorkingMemory:
        """从运行投影创建一份仅含已完成观察的 ``WorkingMemory``。

        返回新对象，不改变运行或访问旧 core；步骤解释规则由
        :meth:`WorkingMemory.from_run` 定义，处理复杂度随步骤数线性增长。
        """
        return WorkingMemory.from_run(run)
