"""服务端模型供应商档案：支持不重启容器热切换激活供应商。

档案持久化在数据卷（APP_DATA_DIR/agentos/llm_profiles.json）。API Key 不落在
档案里：通过 api_key_env 引用既有密钥环境变量（含 _FILE 密钥文件约定），仅在
用户新增自定义供应商时允许内联 api_key（保存在本地数据卷）。

解析顺序约定：激活档案可用（key/base_url/model 齐全）时优先于环境变量；
档案缺失或不可用时回落到原有 TEXT_ENGINE 环境变量逻辑，行为与升级前一致。
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.paths import APP_DATA_DIR

PROFILES_FILE_OVERRIDE_ENV = "AGENTOS_LLM_PROFILES_FILE"
# APP_DATA_DIR 在容器内即 /app/data/agentos，档案与其他 AgentOS 数据同级
_DEFAULT_PROFILE_REL_PATH = Path("llm_profiles.json")
_STORE_VERSION = 1

# key_source 枚举（对前端可见，永不回传密钥本体）
KEY_SOURCE_SECRET = "secret"
KEY_SOURCE_INLINE = "inline"
KEY_SOURCE_MISSING = "missing"


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    provider: str
    base_url: str
    model: str
    api_key_env: str = ""
    api_key: str = ""
    # 只存在于内存/落盘结构中的展示与扩展位，预留将来 UI 文案
    note: str = ""

    def resolved_api_key(self) -> str:
        if self.api_key_env.strip():
            value = _read_secret_setting(self.api_key_env.strip())
            if value:
                return value
        return self.api_key.strip()

    @property
    def key_source(self) -> str:
        if self.api_key_env.strip() and _read_secret_setting(self.api_key_env.strip()):
            return KEY_SOURCE_SECRET
        if self.api_key.strip():
            return KEY_SOURCE_INLINE
        return KEY_SOURCE_MISSING

    def is_usable(self) -> bool:
        return bool(self.resolved_api_key() and self.base_url.strip() and self.model.strip())

    def to_public_dict(self, *, active: bool = False) -> Dict[str, Any]:
        return {
            "name": self.name,
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "key_source": self.key_source,
            "usable": self.is_usable(),
            "active": active,
        }

    def to_storage_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "api_key": self.api_key,
            **({"note": self.note} if self.note else {}),
        }

    @classmethod
    def from_storage_dict(cls, raw: Dict[str, Any]) -> "ProviderProfile":
        return cls(
            name=str(raw.get("name") or "").strip(),
            provider=str(raw.get("provider") or "").strip().lower(),
            base_url=str(raw.get("base_url") or "").strip(),
            model=str(raw.get("model") or "").strip(),
            api_key_env=str(raw.get("api_key_env") or "").strip(),
            api_key=str(raw.get("api_key") or "").strip(),
            note=str(raw.get("note") or "").strip(),
        )


@dataclass
class _StoreCache:
    mtime_ns: int = -1
    size: int = -1
    data: Dict[str, Any] = field(default_factory=dict)


class ProfileStore:
    """档案文件读写，带 mtime 缓存；单进程内线程安全。"""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._cache = _StoreCache()

    # ---- 读取 ----

    def load(self, *, refresh: bool = False) -> Dict[str, Any]:
        with self._lock:
            if not refresh and self._cache.mtime_ns >= 0:
                stat = self._stat()
                if stat is not None and (stat.st_mtime_ns, stat.st_size) == (self._cache.mtime_ns, self._cache.size):
                    return self._cache.data
            data = self._read_and_bootstrap()
            stat = self._stat()
            if stat is not None:
                self._cache = _StoreCache(stat.st_mtime_ns, stat.st_size, data)
            return data

    def _stat(self) -> Optional[os.stat_result]:
        try:
            return self.path.stat()
        except OSError:
            return None

    def _read_and_bootstrap(self) -> Dict[str, Any]:
        """读档案；文件缺失或损坏时按当前环境变量种子初始化。"""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("profiles"), list):
                return self._normalize(raw)
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
        data = _bootstrap_store_from_env()
        self._write(data)
        return data

    @staticmethod
    def _normalize(raw: Dict[str, Any]) -> Dict[str, Any]:
        """存储层永远只持有纯 dict（可 JSON 序列化），对象化留给访问层。"""
        profiles: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw.get("profiles") or []:
            if not isinstance(item, dict):
                continue
            profile = ProviderProfile.from_storage_dict(item)
            if profile.name and profile.name.lower() not in seen:
                seen.add(profile.name.lower())
                profiles.append(profile.to_storage_dict())
        active = str(raw.get("active") or "").strip()
        if active.lower() not in seen:
            active = ""
        return {"version": _STORE_VERSION, "active": active, "profiles": profiles}

    # ---- 写入 ----

    def save(self, data: Dict[str, Any]) -> None:
        with self._lock:
            normalized = self._normalize(data)
            self._write(normalized)
            stat = self._stat()
            if stat is not None:
                self._cache = _StoreCache(stat.st_mtime_ns, stat.st_size, normalized)

    def _write(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, self.path)

    # ---- 业务操作 ----

    def list_profiles(self) -> List[ProviderProfile]:
        return [ProviderProfile.from_storage_dict(item) for item in self.load().get("profiles") or []]

    def active_name(self) -> str:
        return str(self.load().get("active") or "")

    def active_profile(self) -> Optional[ProviderProfile]:
        active = self.active_name()
        if not active:
            return None
        for profile in self.list_profiles():
            if profile.name.lower() == active.lower():
                return profile
        return None

    def set_active(self, name: str) -> ProviderProfile:
        target = name.strip()
        matched = next(
            (p for p in self.list_profiles() if p.name.lower() == target.lower()),
            None,
        )
        if matched is None:
            raise KeyError(f"供应商档案不存在: {target}")
        data = self.load()
        data["active"] = matched.name
        self.save(data)
        return matched

    def upsert(self, profile: ProviderProfile) -> ProviderProfile:
        data = self.load()
        profiles: List[Dict[str, Any]] = list(data.get("profiles") or [])
        replaced = False
        for index, item in enumerate(profiles):
            if str(item.get("name") or "").strip().lower() == profile.name.lower():
                profiles[index] = profile.to_storage_dict()
                replaced = True
                break
        if not replaced:
            profiles.append(profile.to_storage_dict())
        data["profiles"] = profiles
        if not data.get("active") and profile.is_usable():
            data["active"] = profile.name
        self.save(data)
        return profile

    def delete(self, name: str) -> None:
        data = self.load()
        target = name.strip().lower()
        profiles = [
            item for item in (data.get("profiles") or [])
            if str(item.get("name") or "").strip().lower() != target
        ]
        if len(profiles) == len(data.get("profiles") or []):
            raise KeyError(f"供应商档案不存在: {name}")
        data["profiles"] = profiles
        if str(data.get("active") or "").strip().lower() == target:
            data["active"] = ""
        self.save(data)


def _read_secret_setting(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if value:
        return value
    file_path = (os.getenv(f"{name}_FILE") or "").strip()
    if not file_path:
        return ""
    try:
        return Path(file_path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""


def _bootstrap_store_from_env() -> Dict[str, Any]:
    """首次使用时按当前环境变量生成初始档案，保证升级后行为不变。"""
    from app.llm.config import _resolve_provider_fallback, _provider_settings

    profiles: List[Dict[str, Any]] = []
    for provider in ("deepseek", "glm", "qwen"):
        settings = _provider_settings(provider)
        profiles.append(ProviderProfile(
            name=provider,
            provider=provider,
            base_url=str(settings["base_url"]),
            model=str(settings["model"]),
            api_key_env={"deepseek": "DEEPSEEK_API_KEY", "glm": "GLM_API_KEY", "qwen": "DASHSCOPE_API_KEY"}[provider],
        ).to_storage_dict())
    # GLM 通用按量端点单独建档，套餐端点与通用端点可一键互切。
    glm_settings = _provider_settings("glm")
    payg_base = "https://open.bigmodel.cn/api/paas/v4"
    if str(glm_settings["base_url"]).rstrip("/") != payg_base:
        profiles.append(ProviderProfile(
            name="glm-payg",
            provider="glm",
            base_url=payg_base,
            model=str(glm_settings["model"]),
            api_key_env="GLM_API_KEY",
        ).to_storage_dict())

    active = ""
    resolved = _resolve_provider_fallback()
    if resolved:
        active = resolved[0]
    return {"version": _STORE_VERSION, "active": active, "profiles": profiles}


_default_store: Optional[ProfileStore] = None
_default_store_lock = threading.Lock()


def get_profile_store() -> ProfileStore:
    global _default_store
    with _default_store_lock:
        if _default_store is None:
            override = (os.getenv(PROFILES_FILE_OVERRIDE_ENV) or "").strip()
            path = Path(override) if override else APP_DATA_DIR / _DEFAULT_PROFILE_REL_PATH
            _default_store = ProfileStore(path)
        return _default_store


def set_profile_store_for_tests(store: Optional[ProfileStore]) -> None:
    global _default_store
    with _default_store_lock:
        _default_store = store


def resolve_active_profile() -> Optional[ProviderProfile]:
    """当前激活档案；不可用（缺 key/base_url/model）时返回 None 走环境变量回落。"""
    profile = get_profile_store().active_profile()
    if profile and profile.is_usable():
        return profile
    return None


__all__ = [
    "ProviderProfile",
    "ProfileStore",
    "get_profile_store",
    "resolve_active_profile",
    "set_profile_store_for_tests",
    "PROFILES_FILE_OVERRIDE_ENV",
    "KEY_SOURCE_SECRET",
    "KEY_SOURCE_INLINE",
    "KEY_SOURCE_MISSING",
]
