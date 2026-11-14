"""云端角色唯一工厂；当前没有可发布的云端服务。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P1/P3-1)：仅装配suffix、认证/nonce、memory sessions、审计和专用cloud API。
TODO(P1/P3-2)：不装配prefix、原文tokenizer链路或本机预算库；清单需本地批准。
TODO(P1/P3-3)：先完成限额和凭据核验再监听，明确TLS终止与代理可信头规则。
TODO(P1/P3-4)：shutdown停止接单、处理取消、等待/隔离计算，再清理KV与连接。

验收：独立进程不导入Agent应用；启动失败关闭资源，错误角色权重被拒绝。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
