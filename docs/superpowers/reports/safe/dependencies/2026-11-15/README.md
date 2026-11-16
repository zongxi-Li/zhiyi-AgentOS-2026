# 历史实验依赖证据

这里归档 2026-11-14/15 实验使用的三个平台锁，原始字节不变。原位置为
`apps/agentOS/`，HTTP 报告中的 `http_lock_sha256` 对应这里的 HTTP 锁。
历史报告、测量数据和哈希保持原样；其中旧安装命令只描述当时环境。

当前唯一安装入口是 `apps/agentOS/requirements.txt`，已经包含基础运行、
本地工具、Safe 模型、HTTP/TLS、测试和绘图依赖。这里的文件仅用于复核
历史环境，不作为日常安装配置；旧锁之间的相对包含关系按原样保留。

| 原文件 | 原始字节 SHA256 |
| --- | --- |
| `requirements.safe.lock` | `69c643818812b2cfccbce14b00ba05251a27b27a5be37f67cc401f8fded48801` |
| `requirements.safe.http.lock` | `93e94477a657f29a595d69f50989937a4c5d416108fea6912b064d389a77daa6` |
| `requirements.safe.plotting.lock` | `91c42156859217658cd5b2b844db560bf4d869c2e2a46e79dec93227f674a39f` |
