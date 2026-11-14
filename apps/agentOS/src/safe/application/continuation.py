"""云端 suffix 编排；只接收受认证且受 manifest 约束的激活。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P3-1)：注入 suffix runner、会话存储、时钟、审计；禁止 tokenizer 或原文处理入口。
TODO(P3-2)：按会话互斥执行：认证授权→查幂等回执→核验 step/phase/shape→前向→采样→提交。
TODO(P3-3)：prefill step=0；decode 每次只接受一个位置，保持 suffix KV 与 prefix 的位置一致。
TODO(P3-4)：采样成功但回执提交失败时标记 FAILED；不得在已推进 KV 上再次执行。
TODO(P3-5)：EOS、取消、deadline、TTL 和异常都交由生命周期释放或隔离 KV。

验收：重复相同请求只执行一次；乱序、跨 owner、digest 错配均在前向前拒绝。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
