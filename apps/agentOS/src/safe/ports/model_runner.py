"""角色runner与KV生命周期端口；端口不暴露Torch tensor或Cache对象。

TODO(P2)：分别扩展prefix/suffix输入，冻结位置/mask语义；仅传本角色所需数据。
TODO(P3)：前向的异常必须声明状态可能已推进；取消完成前禁止释放或复用KV。
TODO(P6)：加入有界内存与资源能力查询；不要在接口中增加框架类型。
"""

from typing import NewType, Protocol

KVHandle = NewType("KVHandle", str)


class ModelRunner(Protocol):
    """当前仅冻结生命周期；执行签名待模型对齐实验后在此端口扩展。"""

    def create_kv(self, session_id: str) -> KVHandle:
        """创建绑定会话和进程的句柄，不包含可跨进程序列化的KV。"""
        ...

    def release_kv(self, handle: KVHandle) -> None:
        """等待计算结束或隔离后幂等释放；句柄不能再用于执行。"""
        ...

    def close(self) -> None:
        """关闭本角色所有资源，禁止隐式创建另一角色。"""
        ...
