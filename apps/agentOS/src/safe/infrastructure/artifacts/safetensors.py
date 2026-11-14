"""只读 safetensors 角色权重；不反序列化任意可执行对象。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P2-1)：显式加载时才导入 safetensors；先校验文件哈希、header尺寸与总内存限额。
TODO(P2-2)：比较参数名白名单、shape/dtype及缺失/额外键；禁止隐式补全完整模型权重。
TODO(P2-3)：记录 tied weights 的角色拷贝约定，验证 CPU FP32 基线。
TODO(P2-4)：加载失败关闭映射和句柄，不将半初始化runner发布为可用。

验收：恶意header、未知tensor、缺失参数与角色互换全部失败。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
