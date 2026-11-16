"""本机角色唯一工厂；当前不装配或加载模型。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P2-1)：按顺序校验settings/manifest→prefix与tokenizer→预算→transport→应用→本机接口。
TODO(P2-2)：只加载prefix；预算和凭据位于应用数据目录，不写入源码树。
TODO(P2-3)：工厂显式调用才导入重依赖；已创建资源立刻登记到生命周期以便失败回收。
TODO(P2-4)：缺少runner、凭据或持久预算时明确拒绝所需能力，不能退回旧DP。

验收：构造各阶段注入故障，无文件/模型/连接泄露且从不创建suffix。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
