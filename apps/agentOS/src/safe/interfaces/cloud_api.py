"""独立专用激活API；不接受文本聊天请求。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P1-1)：GET capabilities、POST sessions、POST steps、GET requests/{id}、DELETE session。
TODO(P1-2)：解析JSON之前限制body≤12MiB，元数据≤16KiB；限流并限制并发和会话数。
TODO(P1-3)：先认证主体/nonce再交用例；拒绝prompt、tokenIDs、任意metadata与未知版本。
TODO(P1-4)：streaming/chunked同样计入上限；使用严格JSON解析并拒绝重复键。
TODO(P1-5)：关闭不直接销毁在执行中的KV；交由用例/生命周期完成清理。

验收：真实TCP边界测试覆盖超限、慢请求、重放、未知session及跨owner。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
