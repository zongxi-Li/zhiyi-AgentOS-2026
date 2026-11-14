"""manifest身份和兼容核验；当前不读取磁盘或证明权重文件真实。

approved_digest必须来自受信配置/安装结果，不能直接取请求自报的值。
TODO(P2)：经ArtifactStore校验实际权重/配置/tokenizer/template后再发布runner。
TODO(P2)：离线导出原子发布与失败清理由制品适配器实现；不自动下载补齐。
"""

from safe.contracts.manifest import SplitModelManifest
from safe.contracts.errors import ErrorCode, SafeError
from safe.domain.compatibility import manifest_digest, require_manifest_digest
from safe.ports.artifact_store import ArtifactExporter
from pathlib import Path


class ManifestService:
    """纯身份核验入口；同一摘要表示整个已声明manifest一致。"""

    digest = staticmethod(manifest_digest)
    verify = staticmethod(require_manifest_digest)

    def __init__(self, *, exporter: ArtifactExporter | None = None):
        self._exporter = exporter

    def export(self, source: Path, destination: Path, *, model_id: str, revision: str,
               cut_layer: int, license_id: str) -> str:
        """显式调用注入的离线导出；不从请求推导路径或批准来源。"""
        if self._exporter is None:
            raise SafeError(ErrorCode.MODEL_PARTITION_UNAVAILABLE)
        return self._exporter(source, destination, model_id=model_id, revision=revision,
                              cut_layer=cut_layer, license_id=license_id)

    @staticmethod
    def require_compatible(local: SplitModelManifest, remote: SplitModelManifest) -> None:
        require_manifest_digest(remote, manifest_digest(local))
