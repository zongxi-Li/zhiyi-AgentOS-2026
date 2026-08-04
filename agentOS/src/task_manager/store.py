"""工作流注册表，负责保存、加载和推荐行业 Pack 提供的工作流定义。"""
# TODO 当前注册表只加载声明式模板；后期需要拓展为加载动态生成的拓扑图和工作流。

import json
from pathlib import Path
from typing import Dict, Iterable, Optional

from contracts.workflow import WorkflowDefinition


class WorkflowRegistry:
    """保存并推荐行业 Pack 提供的工作流定义。"""

    """初始化类的设计"""
    def __init__(self):
        self._workflows: Dict[str, WorkflowDefinition] = {}
        self._aliases: Dict[str, str] = {}

    def register(self, workflow: WorkflowDefinition) -> None:
        """注册工作流及其别名。

        非引导型工作流必须含步骤；已作为别名占用的工作流标识保持既有兼容行为直接忽略，
        成功时修改进程内注册表。
        """
        if not workflow.workflow_id:
            raise ValueError("workflow_id is required")
        if not workflow.steps and not workflow.is_native_bootstrap:
            raise ValueError(f"workflow {workflow.workflow_id} must define at least one step")
        if workflow.workflow_id in self._aliases:
            return
        self._workflows[workflow.workflow_id] = workflow
        for alias in workflow.aliases:
            alias = (alias or "").strip()
            if alias and alias != workflow.workflow_id:
                self._aliases[alias] = workflow.workflow_id

    def get(
        self,
        workflow_id: str,
        *,
        allowed_workflow_ids: Iterable[str] | None = None,
    ) -> WorkflowDefinition:
        """按标识或别名获取工作流，并在给定作用域外时以 ``KeyError`` 拒绝访问。"""
        canonical_id = self._aliases.get(workflow_id, workflow_id)
        try:
            workflow = self._workflows[canonical_id]
        except KeyError as exc:
            raise KeyError(f"workflow not registered: {workflow_id}") from exc
        if (
            allowed_workflow_ids is not None
            and workflow.workflow_id not in set(allowed_workflow_ids)
        ):
            raise KeyError(
                f"WORKFLOW_NOT_AVAILABLE_IN_PLUGIN_SCOPE: {workflow.workflow_id}"
            )
        return workflow

    def all(self) -> tuple[str, ...]:
        """按注册顺序返回全部工作流的只读元组，复杂度 ``O(W)``。"""
        return tuple(self._workflows.values())

    def recommend(
        self,
        domain: str,
        intent: str,
        *,
        allowed_workflow_ids: Iterable[str] | None = None,
    ) -> Optional[WorkflowDefinition]:
        """推荐作用域内工作流：优先精确领域/意图的原生引导项，再取首个精确或同领域项。

        遍历保持注册顺序，复杂度 ``O(W)``，不改变注册表。
        """
        normalized_domain = (domain or "").strip().lower()
        normalized_intent = (intent or "").strip().lower()

        allowed = set(allowed_workflow_ids) if allowed_workflow_ids is not None else None
        exact_matches = [
            workflow
            for workflow in self._workflows.values()
            if (allowed is None or workflow.workflow_id in allowed)
            if workflow.domain.lower() == normalized_domain
            and workflow.intent.lower() == normalized_intent
        ]
        native_bootstrap = next(
            (workflow for workflow in exact_matches if workflow.is_native_bootstrap),
            None,
        )
        if native_bootstrap is not None:
            return native_bootstrap
        if exact_matches:
            return exact_matches[0]

        for workflow in self._workflows.values():
            if allowed is not None and workflow.workflow_id not in allowed:
                continue
            if workflow.domain.lower() == normalized_domain:
                return workflow
        return None

    def scoped(self, workflow_ids: Iterable[str]) -> "ScopedWorkflowRegistry":
        """创建仅可见指定工作流标识的只读视图，不复制或修改底层定义。"""
        return ScopedWorkflowRegistry(self, tuple(workflow_ids))

    def load_file(self, path: Path) -> WorkflowDefinition:
        """从 YAML（或无 YAML 依赖时 JSON）文件解析、注册并返回工作流；会修改注册表。"""
        text = path.read_text(encoding="utf-8")
        try:
            import yaml  # type: ignore

            data = yaml.safe_load(text)
        except ModuleNotFoundError:
            data = json.loads(text)
        workflow = WorkflowDefinition.model_validate(data)
        self.register(workflow)
        return workflow

    def load_directory(self, directory: Path) -> None:
        """按文件名排序加载目录下 ``*.yaml``；目录缺失时无副作用地返回。"""
        if not directory.exists():
            return
        for path in sorted(directory.glob("*.yaml")):
            self.load_file(path)


class ScopedWorkflowRegistry:
    """进程级工作流定义上的单次运行只读视图；可见集合在创建时冻结。"""

    def __init__(self, registry: WorkflowRegistry, workflow_ids: tuple[str, ...]) -> None:
        self._registry = registry
        self._workflow_ids = frozenset(workflow_ids)

    def get(self, workflow_id: str) -> WorkflowDefinition:
        """在固定作用域内按标识或别名获取工作流；越界与缺失均抛出 ``KeyError``。"""
        return self._registry.get(
            workflow_id, allowed_workflow_ids=self._workflow_ids
        )

    def all(self) -> tuple[WorkflowDefinition, ...]:
        """按底层注册顺序返回本作用域可见工作流，复杂度 ``O(W)``。"""
        return tuple(
            workflow
            for workflow in self._registry.all()
            if workflow.workflow_id in self._workflow_ids
        )

    def recommend(self, domain: str, intent: str) -> Optional[WorkflowDefinition]:
        """在固定作用域中复用底层推荐规则，不修改底层注册表。"""
        return self._registry.recommend(
            domain, intent, allowed_workflow_ids=self._workflow_ids
        )
"""工作流注册表，负责保存、加载和推荐行业 Pack 提供的工作流定义。"""
# TODO 当前注册表只加载声明式模板；后期需要拓展为加载动态生成的拓扑图和工作流。

import json
from pathlib import Path
from typing import Dict, Iterable, Optional

from contracts.workflow import WorkflowDefinition


class WorkflowRegistry:
    """保存并推荐行业 Pack 提供的工作流定义。"""

    """初始化类的设计"""
    def __init__(self):
        self._workflows: Dict[str, WorkflowDefinition] = {}
        self._aliases: Dict[str, str] = {}

    def register(self, workflow: WorkflowDefinition) -> None:
        """注册工作流及其别名。

        非引导型工作流必须含步骤；已作为别名占用的工作流标识保持既有兼容行为直接忽略，
        成功时修改进程内注册表。
        """
        if not workflow.workflow_id:
            raise ValueError("workflow_id is required")
        if not workflow.steps and not workflow.is_native_bootstrap:
            raise ValueError(f"workflow {workflow.workflow_id} must define at least one step")
        if workflow.workflow_id in self._aliases:
            return
        self._workflows[workflow.workflow_id] = workflow
        for alias in workflow.aliases:
            alias = (alias or "").strip()
            if alias and alias != workflow.workflow_id:
                self._aliases[alias] = workflow.workflow_id

    def get(
        self,
        workflow_id: str,
        *,
        allowed_workflow_ids: Iterable[str] | None = None,
    ) -> WorkflowDefinition:
        """按标识或别名获取工作流，并在给定作用域外时以 ``KeyError`` 拒绝访问。"""
        canonical_id = self._aliases.get(workflow_id, workflow_id)
        try:
            workflow = self._workflows[canonical_id]
        except KeyError as exc:
            raise KeyError(f"workflow not registered: {workflow_id}") from exc
        if (
            allowed_workflow_ids is not None
            and workflow.workflow_id not in set(allowed_workflow_ids)
        ):
            raise KeyError(
                f"WORKFLOW_NOT_AVAILABLE_IN_PLUGIN_SCOPE: {workflow.workflow_id}"
            )
        return workflow

    def all(self) -> tuple[str, ...]:
        """按注册顺序返回全部工作流的只读元组，复杂度 ``O(W)``。"""
        return tuple(self._workflows.values())

    def recommend(
        self,
        domain: str,
        intent: str,
        *,
        allowed_workflow_ids: Iterable[str] | None = None,
    ) -> Optional[WorkflowDefinition]:
        """推荐作用域内工作流：优先精确领域/意图的原生引导项，再取首个精确或同领域项。

        遍历保持注册顺序，复杂度 ``O(W)``，不改变注册表。
        """
        normalized_domain = (domain or "").strip().lower()
        normalized_intent = (intent or "").strip().lower()

        allowed = set(allowed_workflow_ids) if allowed_workflow_ids is not None else None
        exact_matches = [
            workflow
            for workflow in self._workflows.values()
            if (allowed is None or workflow.workflow_id in allowed)
            if workflow.domain.lower() == normalized_domain
            and workflow.intent.lower() == normalized_intent
        ]
        native_bootstrap = next(
            (workflow for workflow in exact_matches if workflow.is_native_bootstrap),
            None,
        )
        if native_bootstrap is not None:
            return native_bootstrap
        if exact_matches:
            return exact_matches[0]

        for workflow in self._workflows.values():
            if allowed is not None and workflow.workflow_id not in allowed:
                continue
            if workflow.domain.lower() == normalized_domain:
                return workflow
        return None

    def scoped(self, workflow_ids: Iterable[str]) -> "ScopedWorkflowRegistry":
        """创建仅可见指定工作流标识的只读视图，不复制或修改底层定义。"""
        return ScopedWorkflowRegistry(self, tuple(workflow_ids))

    def load_file(self, path: Path) -> WorkflowDefinition:
        """从 YAML（或无 YAML 依赖时 JSON）文件解析、注册并返回工作流；会修改注册表。"""
        text = path.read_text(encoding="utf-8")
        try:
            import yaml  # type: ignore

            data = yaml.safe_load(text)
        except ModuleNotFoundError:
            data = json.loads(text)
        workflow = WorkflowDefinition.model_validate(data)
        self.register(workflow)
        return workflow

    def load_directory(self, directory: Path) -> None:
        """按文件名排序加载目录下 ``*.yaml``；目录缺失时无副作用地返回。"""
        if not directory.exists():
            return
        for path in sorted(directory.glob("*.yaml")):
            self.load_file(path)


class ScopedWorkflowRegistry:
    """进程级工作流定义上的单次运行只读视图；可见集合在创建时冻结。"""

    def __init__(self, registry: WorkflowRegistry, workflow_ids: tuple[str, ...]) -> None:
        self._registry = registry
        self._workflow_ids = frozenset(workflow_ids)

    def get(self, workflow_id: str) -> WorkflowDefinition:
        """在固定作用域内按标识或别名获取工作流；越界与缺失均抛出 ``KeyError``。"""
        return self._registry.get(
            workflow_id, allowed_workflow_ids=self._workflow_ids
        )

    def all(self) -> tuple[WorkflowDefinition, ...]:
        """按底层注册顺序返回本作用域可见工作流，复杂度 ``O(W)``。"""
        return tuple(
            workflow
            for workflow in self._registry.all()
            if workflow.workflow_id in self._workflow_ids
        )

    def recommend(self, domain: str, intent: str) -> Optional[WorkflowDefinition]:
        """在固定作用域中复用底层推荐规则，不修改底层注册表。"""
        """在固定作用域中复用底层推荐规则，不修改底层注册表。"""
        return self._registry.recommend(
            domain, intent, allowed_workflow_ids=self._workflow_ids
        )
