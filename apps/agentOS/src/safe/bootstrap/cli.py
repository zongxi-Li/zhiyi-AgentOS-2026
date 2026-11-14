"""CLI显式装配，不在import时执行命令或初始化模型。

状态：离线export显式装配已实现；verify/benchmark工具装配仍待扩展。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P2-1)：按子命令选择依赖；--help只走stdlib解析。
TODO(P2-2)：装配验证和benchmark用例后传给interfaces.cli。
TODO(P2-3)：模型/DP可选依赖缺失返回明确非零退出；不能下载补齐或生成虚假报告。
TODO(P2-4)：使用finally/lifecycle保证工具异常退出时关闭资源。

验收：help、参数错误、能力缺失与成功报告的退出码可自动验证。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """显式装配离线导出；尚无下载、运行服务或默认模型路径。"""
    from safe.infrastructure.artifacts.export import export_qwen_artifacts
    from safe.interfaces.cli import run_export_cli
    from safe.application.manifest import ManifestService

    service = ManifestService(exporter=export_qwen_artifacts)
    return run_export_cli(service.export, argv)
