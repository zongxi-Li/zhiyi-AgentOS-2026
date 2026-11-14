"""CLI显式装配，不在import时执行命令或初始化模型。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P2-1)：按子命令选择依赖；--help只走stdlib解析。
TODO(P2-2)：装配制品导出、验证和benchmark用例后传给interfaces.cli。
TODO(P2-3)：模型/DP可选依赖缺失返回明确非零退出；不能下载补齐或生成虚假报告。
TODO(P2-4)：使用finally/lifecycle保证工具异常退出时关闭资源。

验收：help、参数错误、能力缺失与成功报告的退出码可自动验证。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
