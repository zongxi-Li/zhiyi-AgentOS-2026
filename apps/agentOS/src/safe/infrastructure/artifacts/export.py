"""离线、显式的 prefix/suffix 制品导出。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P2-1)：只从批准完整模型和固定revision导出；先核对代码/权重许可证。
TODO(P2-2)：按角色筛选权重并单独处理 tied weights，记录参数名、shape、dtype和摘要。
TODO(P2-3)：分词器及模板仅进入本机角色；云端只保留续算必需配置及suffix权重。
TODO(P2-4)：写入临时目录、验证重新加载和层覆盖，再原子发布manifest；失败可清理。

验收：两个角色分别加载后对照完整模型；manifest 无未声明权重，导出可复现。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
