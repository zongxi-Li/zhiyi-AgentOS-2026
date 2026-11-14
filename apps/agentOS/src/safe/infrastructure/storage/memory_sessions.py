"""进程内短时会话存储；尚未实现并发事务。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P3-1)：实现 SessionStore，每个会话独立锁并限制总数、内存、待处理请求数和回执数。
TODO(P3-2)：存储owner/manifest/next_step/phase/TTL/KV句柄及幂等回执，不存原始prompt。
TODO(P3-3)：原子占用request ID，不能在锁外检查后并行前向；摘要冲突直接拒绝。
TODO(P3-4)：清理器通过显式生命周期启动；固定绝对TTL，关闭等待正在执行的计算。
TODO(P3-5)：进程重启不恢复KV；session ID包含新进程隔离域或不可猜测随机身份。

验收：双线程同step只执行一次；跨owner、过期、OOM与取消竞态可重复验证。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
