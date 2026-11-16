"""纯manifest身份规则，不打开文件，不将摘要比较当作制品认证。

manifest-v1规范：严格校验→包含所有默认字段的JSON对象→键排序、UTF-8、
ensure_ascii=False、无空白、禁止NaN→SHA256。不是通用RFC8785实现。
config_digest必须绑定完整配置（包括RoPE）；digest字段不属于manifest本体。
TODO(P2)：制品存储实测每个文件哈希、角色权重及tied weights；批准摘要由配置注入。
"""

import hashlib
import hmac
import json

from pydantic import ValidationError

from components.safe.contracts.errors import ErrorCode, SafeError
from components.safe.contracts.manifest import SplitModelManifest


def validated_manifest(manifest: SplitModelManifest) -> SplitModelManifest:
    """重新校验不可变合同，拒绝model_copy/model_construct绕过验证的对象。"""
    try:
        return SplitModelManifest.model_validate(manifest.model_dump())
    except (ValidationError, AttributeError):
        raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE) from None


def manifest_digest(manifest: SplitModelManifest) -> str:
    value = validated_manifest(manifest)
    canonical = json.dumps(value.model_dump(mode="json"), sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def require_manifest_digest(manifest: SplitModelManifest, approved_digest: str) -> SplitModelManifest:
    actual = manifest_digest(manifest)
    if (not isinstance(approved_digest, str) or len(approved_digest) != 64
            or not approved_digest.isascii() or not hmac.compare_digest(actual, approved_digest)):
        raise SafeError(ErrorCode.MANIFEST_INCOMPATIBLE)
    return validated_manifest(manifest)
