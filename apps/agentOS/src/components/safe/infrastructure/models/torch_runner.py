"""Torch 角色执行、设备和 KV 所有权适配器；尚未加载真实模型。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P2-1)：显式构造时局部导入 Torch，冻结 CPU/FP32/eager 参考配置与依赖版本。
TODO(P2-2)：仅加载指定角色权重，eval + inference_mode，禁用梯度与任意远端代码。
TODO(P2-3)：实现 ModelRunner；仅以不透明句柄传递 KV，句柄绑定角色/会话/进程。
TODO(P2-4)：计算 deadline、取消和并发互斥；CUDA 完成/隔离前不能释放在用状态。
TODO(P2-5)：构造失败关闭已分配资源；拒绝缺少前导或后段权重时加载完整模型补救。

验收：import 不要求 Torch；真实模型测试证明两角色无越权权重与 KV 泄露。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
