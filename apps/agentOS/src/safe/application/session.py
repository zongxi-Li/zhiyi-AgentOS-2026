"""会话创建、步骤事务、回执查询、取消与过期清理。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P3-1)：由认证 owner 创建不可猜测 session ID，绑定 manifest 和会话总 deadline。
TODO(P3-2)：单调时钟执行 idle=60秒、absolute=300秒；查询/重试不无限续期。
TODO(P3-3)：定义锁内的幂等占位、执行中标记、回执提交和终态发布顺序。
TODO(P3-4)：取消仅发出意图；等待 runner 停止或隔离后再释放 KV，不能假设网络断连等于停止。
TODO(P3-5)：回执查询验证 owner/session/request；不同请求摘要使用同一 request ID 明确冲突。

验收：进程重启旧 ID 无效；终态不可复活；每份 KV 仅释放一次。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
