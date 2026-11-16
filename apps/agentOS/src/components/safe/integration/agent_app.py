"""Agent应用的可信身份、配置、事件和启动关闭适配边界。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P5-1)：应用启动显式调用bootstrap.local并注入本机身份，关闭时等待safe清理。
TODO(P5-2)：应用API只薄封装safe.interfaces.local_api，不保留第二套split实现。
TODO(P5-3)：流事件转换不得把本机prompt送进云端API或通用日志。
TODO(P5-4)：迁移旧safe/encryptionservice导入时统一包名并验证无双实例。

验收：应用禁用safe时不加载模型；启动失败可恢复且不回退普通远程聊天。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
