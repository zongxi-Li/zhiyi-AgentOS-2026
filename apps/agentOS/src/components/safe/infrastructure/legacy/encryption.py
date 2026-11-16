"""遗留加密迁移占位；现阶段仍以根encryptionservice.py为唯一实现。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P0-1)：先为旧调用方建立行为回归，再整体迁入此文件并将旧入口变成单向重导出。
TODO(P0-2)：核查 NumPy/cryptography/diffprivlib 的可选依赖与import时singleton副作用。
TODO(P0-3)：登记固定密钥、XOR/CBC fallback、模拟同态和旧DP噪声的已知限制。
TODO(P0-4)：统一旧import路径防止双singleton；safe新推理/隐私链路禁止导入本模块。

验收：当前不导入旧服务、不复制旧算法；后续迁移不能悄悄改变现有调用行为。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
