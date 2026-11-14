"""Qwen2 系列首个受控前后段适配；参考源码见资料目录。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P2-1)：核验 Qwen2.5-0.5B-Instruct 模型许可并锁定40位 revision；K=2 仅为候选。
TODO(P2-2)：prefix=embedding+layers[:K]；suffix=layers[K:]+final norm+lm head。
TODO(P2-3)：保持原 decoder layer_idx、RoPE、causal mask、cache_position 与 position_ids 语义。
TODO(P2-4)：prefix/suffix 分别持有自己的 KV；不能把完整 DynamicCache 发送到另一端。
TODO(P2-5)：固定 Transformers 版本；只参考 v4.46.3 流程，不照搬新版内部 API。
TODO(P2-6)：验证 tied embedding/lm_head 的角色导出和独立加载，不依赖云端完整词嵌入。

验收：完整/拆分模型 prefill 与连续decode logits/token 对齐，切点前后 norm 只执行一次。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
