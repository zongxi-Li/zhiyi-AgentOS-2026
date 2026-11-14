"""批准制品的读取端口；调用方只提交逻辑身份，不能提交任意路径。

TODO(P2)：补充离线导出端口的原子发布与失败清理合同。
TODO(P2)：实现端必须限制resolve路径、文件大小、角色与哈希，并防TOCTOU。
"""

from typing import Protocol

from safe.contracts.manifest import SplitModelManifest


class ArtifactStore(Protocol):
    def verified_manifest(self, manifest_digest: str) -> SplitModelManifest:
        """从批准目录核实实际文件身份后返回；不能仅回传自报manifest。"""
        ...
