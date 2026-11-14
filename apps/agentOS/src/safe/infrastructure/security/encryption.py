"""现代加密适配器归属；不得从legacy复用固定密钥或XOR。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P1-1)：先定义用途：TLS由HTTP栈负责，静态载荷若加密则使用审核AEAD库。
TODO(P1-2)：每次唯一nonce、显式AAD绑定owner/release/manifest，密钥外置与版本化轮转。
TODO(P1-3)：禁止手工CBC、可预测nonce、硬编码密钥以及加密失败后的明文fallback。
TODO(P1-4)：仅在调用时加载可选库，导入不生成密钥；认证失败直接拒绝。

验收：标准测试向量、AAD篡改、nonce复用防护和缺依赖均覆盖。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
