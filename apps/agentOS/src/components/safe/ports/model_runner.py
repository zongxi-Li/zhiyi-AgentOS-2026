"""角色runner与KV生命周期端口；端口不暴露Torch tensor或Cache对象。

TODO(P2)：分别扩展prefix/suffix输入，冻结位置/mask语义；仅传本角色所需数据。
TODO(P3)：前向的异常必须声明状态可能已推进；取消完成前禁止释放或复用KV。
TODO(P6)：加入有界内存与资源能力查询；不要在接口中增加框架类型。
"""

from typing import NewType, Protocol

from components.safe.contracts.manifest import SplitModelManifest

KVHandle = NewType("KVHandle", str)


class ModelRunner(Protocol):
    """两角色共有的资源生命周期。"""

    def create_kv(self, session_id: str) -> KVHandle:
        """创建绑定会话和进程的句柄，不包含可跨进程序列化的KV。"""
        ...

    def release_kv(self, handle: KVHandle) -> None:
        """等待计算结束或隔离后幂等释放；失败可重试，句柄不得复用。"""
        ...

    def close(self) -> None:
        """关闭本角色所有资源，禁止隐式创建另一角色。"""
        ...


class SuffixRunner(ModelRunner, Protocol):
    """云端后段执行端口：只接受激活，参数类型不含Torch或用户原文。"""

    @property
    def manifest(self) -> SplitModelManifest:
        """已由角色制品验证的manifest。"""
        ...

    def prefill(self, activation: tuple[float, ...], shape: tuple[int, int, int], *,
                kv_handle: KVHandle, session_id: str) -> tuple[float, ...]:
        """空KV上的首步，返回最后位置的完整词表logits。"""
        ...

    def decode(self, kv_handle: KVHandle, session_id: str,
               activation: tuple[float, ...], shape: tuple[int, int, int]) -> tuple[float, ...]:
        """在已有KV上推进一个位置，错误时状态不可再用。"""
        ...


class TokenSampler(Protocol):
    def sample(self, logits: tuple[float, ...]) -> tuple[int, bool]:
        """校验词表/有限值后返回token和EOS标记；重试不再次采样。"""
        ...


class PrefixRunner(ModelRunner, Protocol):
    @property
    def manifest(self) -> SplitModelManifest:
        ...

    def prefill(self, token_ids: tuple[int, ...], *, kv_handle: KVHandle,
                session_id: str) -> tuple[tuple[float, ...], tuple[int, int, int]]:
        """原始token只在本机使用；返回切口激活。"""
        ...

    def decode(self, kv_handle: KVHandle, session_id: str,
               token_id: int) -> tuple[tuple[float, ...], tuple[int, int, int]]:
        ...


class LocalTokenizer(Protocol):
    @property
    def manifest(self) -> SplitModelManifest:
        ...

    @property
    def vocab_size(self) -> int:
        ...

    @property
    def eos_token_ids(self) -> frozenset[int]:
        ...

    def encode_prompt(self, prompt: str) -> tuple[int, ...]:
        """应用固定chat template并验证长度，不能记录原文。"""
        ...

    def decode(self, token_ids: tuple[int, ...]) -> str:
        """本机完整序列解码并隐藏特殊token；当前非流式。"""
        ...
