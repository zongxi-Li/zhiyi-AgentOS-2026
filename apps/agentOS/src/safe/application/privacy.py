"""出站发布事务的归属；目前未开放 baseline 或实验 DP 发布用例。

TODO(P4)-1：验证批准的 profile、公开定长形状与完整发布范围。
TODO(P4)-2：以 owner/profile/window/release_id 原子预扣预算，再生成噪声。
TODO(P4)-3：持久绑定 noisy payload 与 release_id；相同重试复用原字节，不能重采样。
TODO(P4)-4：崩溃不自动退款；未知是否出站时保守计费并拒绝重新发布。
TODO(P4)-5：固定机制/会计版本，覆盖多会话并发、重启、预算耗尽和磁盘故障。
验收：所有失败点均不能输出未记账载荷；回执不得声称未证明的 DP 保证。
"""

from safe.contracts.errors import ErrorCode, SafeError
from safe.contracts.privacy import PrivacyReceipt


class PrivacyReleaseService:
    """未完成发布事务前不返回虚假的隐私回执。"""

    def release(self) -> PrivacyReceipt:
        raise SafeError(ErrorCode.PRIVACY_UNAVAILABLE)
