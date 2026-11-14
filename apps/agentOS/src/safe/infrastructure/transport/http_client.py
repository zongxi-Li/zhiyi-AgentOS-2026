"""专用激活协议客户端；目前不创建httpx连接或请求。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P1-1)：显式构造时导入HTTP依赖，限制批准HTTPS origin、证书验证及重定向。
TODO(P1-2)：实现 capabilities / sessions / steps / requests/{id} / DELETE session。
TODO(P1-3)：每次传输使用新nonce和签名，request ID及已扰动载荷保持不变。
TODO(P1-4)：超时后先查回执；不能自动重试可能已推进KV的步骤；无法确认时终止会话。
TODO(P1-5)：限制响应体、连接池、读写和端到端deadline；禁止把激活/凭据放URL或日志。

验收：模拟超时、TLS失败、恶意重定向、截断和重复响应；绝不发原始文本。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
