"""Mutable capability registration over shared descriptor contracts."""
from collections import OrderedDict
from typing import Iterable
from contracts.acg.capabilities import (CapabilityPromptProfile, ContextConsumptionPolicy, PlanningCapabilityDescriptor, PlanningRiskLevel, highest_planning_risk_level)

class CapabilityCatalog:
    """经校验且顺序确定的可执行规划能力注册表。"""

    def __init__(self, descriptors: Iterable[PlanningCapabilityDescriptor] = ()) -> None:
        self._descriptors: OrderedDict[str, PlanningCapabilityDescriptor] = OrderedDict()
        self._aliases: dict[str, str] = {}
        for descriptor in descriptors:
            self.register(descriptor)

    def register(self, descriptor: PlanningCapabilityDescriptor) -> None:
        """注册一个能力描述符并规范化标识与别名。

        保持插入顺序；重复能力或与其他能力冲突的别名会抛出 ``ValueError``，失败前不写入。
        """
        capability_id = self._normalize(descriptor.capability_id)
        if not capability_id:
            raise ValueError("capabilityId is required")
        if capability_id in self._descriptors:
            raise ValueError(f"duplicate capabilityId: {descriptor.capability_id}")

        normalized = descriptor.model_copy(
            update={
                "capability_id": capability_id,
                "depends_on": [self._normalize(item) for item in descriptor.depends_on],
                "optional_dependencies": [
                    self._normalize(item) for item in descriptor.optional_dependencies
                ],
                "domain_hints": [self._normalize(item) for item in descriptor.domain_hints],
            }
        )
        alias_values = [capability_id, *normalized.aliases]
        for value in alias_values:
            alias = self._normalize(value)
            existing = self._aliases.get(alias)
            if existing is not None and existing != capability_id:
                raise ValueError(f"duplicate capability alias: {value}")

        self._descriptors[capability_id] = normalized
        for value in alias_values:
            self._aliases[self._normalize(value)] = capability_id

    def get(self, capability_id: str) -> PlanningCapabilityDescriptor:
        """按规范化能力标识获取描述符；未注册时抛出 ``KeyError``。"""
        normalized = self._normalize(capability_id)
        try:
            return self._descriptors[normalized]
        except KeyError as exc:
            raise KeyError(f"planning capability not registered: {capability_id}") from exc

    def resolve(self, value: str) -> PlanningCapabilityDescriptor:
        """按能力标识或别名解析描述符；别名冲突已在注册阶段禁止。"""
        normalized = self._normalize(value)
        capability_id = self._aliases.get(normalized)
        if capability_id is None:
            raise KeyError(f"planning capability not registered: {value}")
        return self._descriptors[capability_id]

    def available(self, domain_hint: str | None = None) -> tuple[PlanningCapabilityDescriptor, ...]:
        """返回领域可见描述符的不可变序列，按 ``(priority, capability_id)`` 稳定排序。"""
        domain = self._normalize(domain_hint or "")
        descriptors = [
            descriptor
            for descriptor in self._descriptors.values()
            if not domain
            or not descriptor.domain_hints
            or domain in descriptor.domain_hints
            or "general" in descriptor.domain_hints
        ]
        return tuple(sorted(descriptors, key=lambda item: (item.priority, item.capability_id)))

    def scoped(self, capability_ids: Iterable[str]) -> "CapabilityCatalog":
        """构建隔离能力目录视图，不修改全局目录；返回项深拷贝并重新校验依赖。"""

        allowed = {self._normalize(item) for item in capability_ids}
        scoped = CapabilityCatalog(
            descriptor.model_copy(deep=True, update={
                "optional_dependencies": [dependency for dependency in descriptor.optional_dependencies
                                          if dependency in allowed],
            })
            for capability_id, descriptor in self._descriptors.items()
            if capability_id in allowed
        )
        scoped.validate()
        return scoped

    def validate(self) -> None:
        """验证依赖均已注册且不存在环；深度优先遍历，复杂度 ``O(V+E)``。"""
        for descriptor in self._descriptors.values():
            for dependency in [*descriptor.depends_on, *descriptor.optional_dependencies]:
                if dependency not in self._descriptors:
                    raise ValueError(
                        f"capability {descriptor.capability_id} has dangling dependency: {dependency}"
                    )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(capability_id: str) -> None:
            if capability_id in visiting:
                raise ValueError(f"capability dependency cycle detected at: {capability_id}")
            if capability_id in visited:
                return
            visiting.add(capability_id)
            descriptor = self._descriptors[capability_id]
            for dependency in [*descriptor.depends_on, *descriptor.optional_dependencies]:
                visit(dependency)
            visiting.remove(capability_id)
            visited.add(capability_id)

        for capability_id in self._descriptors:
            visit(capability_id)

    def expand_dependencies(self, capability_ids: Iterable[str]) -> list[str]:
        """展开必需依赖并返回依赖先于依赖者的去重顺序，复杂度 ``O(V+E)``。"""
        selected: list[str] = []
        visited: set[str] = set()

        def include(value: str) -> None:
            descriptor = self.resolve(value)
            if descriptor.capability_id in visited:
                return
            for dependency in descriptor.depends_on:
                include(dependency)
            visited.add(descriptor.capability_id)
            selected.append(descriptor.capability_id)

        for capability_id in capability_ids:
            include(capability_id)
        return selected

    @staticmethod
    def _normalize(value: str) -> str:
        return (value or "").strip().lower()
