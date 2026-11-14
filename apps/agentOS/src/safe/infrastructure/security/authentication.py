"""云端认证、撤销、作用域与nonce消费边界。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P1-1)：从注入凭据源取得主体，禁止信任body.owner；先验签再访问会话。
TODO(P1-2)：核实±60秒窗口与nonce格式，原子consume防并发重放并设置有界TTL。
TODO(P1-3)：认证method/path/body digest/manifest/request ID等协议字段，规范编码避免歧义。
TODO(P1-4)：绑定owner与session，权限不足和未知凭据使用固定错误，日志不回显签名。

验收：重放、时间窗边界、撤销、跨owner与签名后body篡改全部拒绝。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
