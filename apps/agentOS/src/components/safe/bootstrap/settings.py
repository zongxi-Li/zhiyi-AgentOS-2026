"""显式配置模型；导入时不读取环境变量、文件或全局缓存。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P0-1)：定义local/cloud角色、批准目录、HTTPS origin、凭据引用和feature flags。
TODO(P0-2)：首期固定batch1、prompt128、output32、total160、FP32、idle60s、absolute300s。
TODO(P0-3)：配置body12MiB/raw8MiB/metadata16KiB、会话上限与端到端deadline。
TODO(P0-4)：拒绝相对越界路径、任意下载URL、trust_remote_code与未经批准DP profile。
TODO(P0-5)：依赖版本由requirements.safe输入/锁控制，角色工厂检查能力而非静默降级。

验收：显式传参可离线测试，配置错误在创建任何外部资源前拒绝。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
