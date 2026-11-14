"""canonical request 与签名适配器归属，不发明自定义加密。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P1-1)：先参考仓库 resource_signing，再冻结safe独立的domain separator与canonical字段顺序。
TODO(P1-2)：签名覆盖HTTP method、规范path、timestamp、nonce、body SHA256及协议版本。
TODO(P1-3)：JSON先编码成最终字节再签名，拒绝重复键/歧义路径/不支持的query。
TODO(P1-4)：标准HMAC-SHA256+constant-time验签，密钥由Credentials注入并支持轮转。

验收：发布跨语言已知答案向量；单字段变化必失败；签名不替代TLS或nonce存储。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
