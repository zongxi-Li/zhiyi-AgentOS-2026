"""隐私声明合同；profile 名称、裁剪或加噪均不自动构成 DP 证明。

TODO(P4)：冻结固定128位置的公开 mask/padding、prompt replacement 邻接与 transcript 范围。
TODO(P4)：补齐机制版本、会计版本、预算窗口和 release 身份绑定后才能开放实验 profile。
当前只允许 baseline 配置，防止半成品 DP profile 被调用方误用。
"""

from typing import Literal

from safe.contracts.base import Digest, Identifier, SafeContract


class PrivacyProfile(SafeContract):
    profile_id: Literal["split-baseline-v1"] = "split-baseline-v1"
    guarantee: Literal["none"] = "none"


class PrivacyReceipt(SafeContract):
    release_id: Identifier
    payload_digest: Digest
    profile: PrivacyProfile


class BudgetSnapshot(SafeContract):
    """结构预留；正式会计使用可审计、可保守舍入的数值表示。"""

    owner_id: Identifier
    accounting_version: Literal["unavailable"] = "unavailable"
