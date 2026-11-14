"""纯模型兼容规则，不打开制品、不信任客户端声明。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P2-1)：比较 revision/config/tokenizer/template 与前后段权重摘要，核验批准 manifestDigest。
TODO(P2-2)：核对 [0,K)、[K,N) 连续且无重叠，dtype、hidden size、位置与 RoPE 语义相同。
TODO(P2-3)：验证上下文上限160及首期 FP32/eager 配置；tied weights 的两个角色需分别验真。
TODO(P2-4)：返回稳定的 MANIFEST_INCOMPATIBLE；不在异常中回显真实路径或模型内容。

验收：单字段错配全部拒绝；不同序列化字段顺序不改变 canonical digest。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
