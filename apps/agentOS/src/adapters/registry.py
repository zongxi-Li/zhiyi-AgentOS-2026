"""统一能力注册表共用的校验、冲突与健康状态逻辑。"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from threading import RLock
from typing import Generic, Iterable, TypeVar

from contracts.capability import CapabilityKind, CapabilityManifest


AdapterT = TypeVar("AdapterT")


class CapabilityRegistrationError(ValueError):
    """表示能力登记请求违反了身份或类别约束。"""


class CapabilityResolutionError(LookupError):
    """表示能力不存在、不可用或无法安全解析。"""


@dataclass(frozen=True)
class RegistryEntry(Generic[AdapterT]):
    """保存已验证的适配器及其登记时的不可变声明快照。"""

    adapter: AdapterT
    manifest: CapabilityManifest
    fingerprint: str


class CapabilityRegistry(Generic[AdapterT]):
    """提供线程安全的能力 ID 注册、冲突检测和健康状态投影。

    注册表只保存应用层已创建的适配器，不创建网络客户端、不保存密钥，也不持有
    供应商 SDK 对象。相同 ID 的相同声明是幂等操作；任何声明差异都会被拒绝，
    防止启动顺序改变时产生静默覆盖。
    """

    def __init__(self, *, allowed_kinds: Iterable[CapabilityKind]) -> None:
        self._allowed_kinds = frozenset(allowed_kinds)
        self._entries: dict[str, RegistryEntry[AdapterT]] = {}
        self._lock = RLock()

    def register(self, adapter: AdapterT) -> RegistryEntry[AdapterT]:
        """校验并登记适配器，返回实际保留的条目。

        适配器必须公开 ``manifest`` 属性。该属性中的能力类别必须属于当前注册表；
        首次登记保留其声明快照，后续相同声明保持原条目不变，不同声明抛出稳定
        的 ``CAPABILITY_ID_CONFLICT`` 错误。
        """
        manifest = self._manifest_of(adapter)
        capability_id = manifest.capability_id.strip()
        if not capability_id or capability_id != manifest.capability_id:
            raise CapabilityRegistrationError(
                "CAPABILITY_ID_INVALID: capabilityId must not contain leading or trailing whitespace"
            )
        if manifest.kind not in self._allowed_kinds:
            expected = ",".join(sorted(item.value for item in self._allowed_kinds))
            raise CapabilityRegistrationError(
                f"CAPABILITY_KIND_INVALID: expected one of {expected}, got {manifest.kind.value}"
            )

        fingerprint = self._fingerprint(manifest)
        entry = RegistryEntry(adapter=adapter, manifest=manifest, fingerprint=fingerprint)
        with self._lock:
            current = self._entries.get(capability_id)
            if current is None:
                self._entries[capability_id] = entry
                return entry
            if current.fingerprint != fingerprint:
                raise CapabilityRegistrationError(
                    f"CAPABILITY_ID_CONFLICT: {capability_id} is already registered with a different manifest"
                )
            return current

    def resolve(self, capability_id: str) -> AdapterT:
        """按能力 ID 解析健康适配器，不健康实现不会被返回。"""
        normalized_id = capability_id.strip()
        if not normalized_id:
            raise CapabilityResolutionError("CAPABILITY_NOT_FOUND: empty capabilityId")
        with self._lock:
            entry = self._entries.get(normalized_id)
        if entry is None:
            raise CapabilityResolutionError(
                f"CAPABILITY_NOT_FOUND: {normalized_id} is not registered"
            )
        if not self._is_available(entry.adapter):
            raise CapabilityResolutionError(
                f"CAPABILITY_UNAVAILABLE: {normalized_id} is not healthy"
            )
        return entry.adapter

    @staticmethod
    def _manifest_of(adapter: AdapterT) -> CapabilityManifest:
        """提取并验证适配器声明，拒绝未遵循稳定合同的实现。"""
        manifest = getattr(adapter, "manifest", None)
        if not isinstance(manifest, CapabilityManifest):
            raise CapabilityRegistrationError(
                "CAPABILITY_MANIFEST_INVALID: adapter.manifest must be CapabilityManifest"
            )
        return manifest

    @staticmethod
    def _fingerprint(manifest: CapabilityManifest) -> str:
        """将 Pydantic 声明转为确定性 JSON，避免可变字典影响冲突判断。"""
        return json.dumps(
            manifest.model_dump(by_alias=True, mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _is_available(adapter: AdapterT) -> bool:
        """读取可选的同步健康检查；未声明检查即视为可用。

        注册表是同步查找层，异步健康检查需要由应用层在注册前完成，避免每次路由
        隐式产生网络 I/O。错误或协程返回均按不健康处理，确保不会误调外部能力。
        """
        checker = getattr(adapter, "is_available", None)
        if checker is None:
            return True
        if not callable(checker):
            return False
        try:
            available = checker()
        except Exception:
            return False
        if inspect.isawaitable(available):
            if inspect.iscoroutine(available):
                available.close()
            return False
        return available is True


__all__ = [
    "CapabilityRegistrationError",
    "CapabilityRegistry",
    "CapabilityResolutionError",
    "RegistryEntry",
]
