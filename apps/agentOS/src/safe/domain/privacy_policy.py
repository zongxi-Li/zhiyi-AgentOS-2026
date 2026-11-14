"""纯隐私策略：区分 baseline 与实验 DP，不产生噪声。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P4-1)：baseline 明确 guarantee=none；实验 DP profile 需要独立版本和批准标志。
TODO(P4-2)：固定 prompt replacement 邻接和整份张量 L2 裁剪 C，敏感度按2C处理。
TODO(P4-3)：列出激活、步数、长度、位置、mask、时间和生成 token 的公开/保护范围。
TODO(P4-4)：拒绝根据用户内容调整预算、阈值或填充长度；自适应 decode 发布逐次入账。

验收：未经批准的 profile 不可配置；无噪声发布绝不生成 DP 回执。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
