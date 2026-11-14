"""suffix 端采样实现归属；首版仅 greedy。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P3-1)：greedy 使用固定 logits 语义，核验词表范围、NaN/Inf 和 EOS token 集。
TODO(P3-2)：后续随机采样使用每会话独立 RNG，seed/状态不跨用户共享。
TODO(P3-3)：重复请求返回已存token；不能因网络重试再采样或推进 RNG。
TODO(P3-4)：冻结 ties、temperature、top-k/top-p 的协议版本后再扩展合同。

验收：相同回执的token恒定；最大输出32且总context≤160；无效logits导致失败。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
