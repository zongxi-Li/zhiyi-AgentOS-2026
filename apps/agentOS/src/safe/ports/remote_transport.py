"""专用远端协议端口；不提供发送prompt或通用聊天API的方法。

已定义经批准manifest的create_session与close_session；owner由传输上下文绑定。
TODO(P1)：步骤超时后先query；查不到结果并不意味着模型未执行。
TODO(P1)：每次HTTP请求重新签名和nonce，业务request ID与载荷字节保持不变。
"""

from typing import Protocol

from safe.contracts.inference import Capabilities
from safe.contracts.session import SessionView, StepReceipt, StepRequest


class RemoteTransport(Protocol):
    def create_session(self, manifest_digest: str) -> SessionView:
        """只传制品身份；会话创建响应不确定时由远端TTL回收。"""
        ...

    def capabilities(self) -> Capabilities:
        """验证响应版本与限额，不因远端available而跳过本地校验。"""
        ...

    def step(self, request: StepRequest) -> StepReceipt:
        """有界、认证传输；异常不得触发盲目重试。"""
        ...

    def query(self, session_id: str, request_id: str) -> StepReceipt | None:
        """查询已提交结果，身份由传输上下文绑定。"""
        ...

    def close(self) -> None:
        """显式释放连接池，不等同于云端会话取消。"""
        ...

    def close_session(self, session_id: str) -> SessionView:
        """幂等关闭本身份的会话；已终止时返回终态视图。"""
        ...
