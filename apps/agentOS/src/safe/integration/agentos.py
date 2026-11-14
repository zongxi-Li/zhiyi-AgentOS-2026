"""AgentOS分区/资源能力到safe合同的唯一转换边界。

状态：职责与验收骨架，尚未实现此文件承担的运行能力。
依赖：遵守 README 的分层表；外部业务对象仅 integration 可引用。

TODO(P2-1)：复用现有contracts.model_partition和ModelPartitionService，不复制它们的类型。
TODO(P2-2)：将批准分区计划转换为manifest描述，核验层区间、资源授权与实际制品。
TODO(P2-3)：Mission/Run/授权对象仅在此层读取，不能进入safe.domain或runner DTO。
TODO(P2-4)：没有真实后端维持MODEL_PARTITION_UNAVAILABLE；资源登记不等于可执行。

验收：已有分区测试保持通过；未授权/非连续/身份不符计划不能启动runner。
阶段定义、实施顺序及参考资料见 README 与配套 TODO 方案。
"""

__all__: list[str] = []
