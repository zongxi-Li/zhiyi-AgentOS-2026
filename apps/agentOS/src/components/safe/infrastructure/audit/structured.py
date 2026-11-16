"""无内容、白名单结构化审计适配器。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P1-1)：只接受AuditEvent，不接受任意dict、异常repr、prompt、激活、KV、凭据或文件路径。
TODO(P1-2)：定义合成关联ID的保留期限；内容hash也可能可关联，不默认全量记录。
TODO(P1-3)：sink由bootstrap注入，明确背压、队列上限、关闭与输出失败策略。
TODO(P1-4)：不在导入时配置全局logging或启动线程；审计失败不触发原文fallback。

验收：捕获所有日志，插入敏感标记后确认不可检索；队列满和sink异常可控。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
