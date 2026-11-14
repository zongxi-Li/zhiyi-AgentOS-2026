"""safe 自有预算 schema 与显式版本升级入口。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P4-1)：定义schema_version、accounts、releases的字段和唯一键，不复用Agent业务数据库表。
TODO(P4-2)：release绑定owner/profile/window/请求摘要/机制版本/消费/状态，定义必要索引。
TODO(P4-3)：升级需显式命令、备份及事务；不支持版本不可以删除数据库修复。
TODO(P4-4)：约束迁移后的预算不减少；损坏、回滚副本和多设备预算的威胁范围须说明。

验收：新建/重复升级/中途失败/未知版本都有离线测试且不丢消费历史。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
