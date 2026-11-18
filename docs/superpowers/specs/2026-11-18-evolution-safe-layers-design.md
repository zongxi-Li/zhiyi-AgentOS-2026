# 进化器按 SAFE 分层实施

授权依据：2026-11-17 用户要求“开始执行分析和实现”，沿用上一轮确认的分层、事务与离线图演化方向。

## 现状与选择

当前 EvolutionService 混合 Run 投影、评分、提案、审核，store 同时定义协议和实现。
审核创建版本与修改提案是两次提交；失败可能留下已生效但仍待审的提案。
GraphEvolutionService 和 SkillEvolutionService 仍明确拒绝执行。

采用兼容迁移：共享 DTO 保持 contracts/evolution.py 单一定义，进化器内部增加
application、domain、ports、infrastructure、integration、bootstrap。
相比只移动文件，这同时消除发布的部分提交；相比直接实现任意图自动重写，显式依赖注入
让候选算法、真实离线评测、正式发布授权各自有独立边界。

## 用例及依赖

- domain：评分、证据去重、变更校验、提案迁移和版本发布一致性；纯规则。
- application：接收 Trajectory，编排持久化、评分、提案、审核和回滚，只依赖合同、domain、ports。
- ports：版本/证据存储、图候选生成、图校验、离线对照评测、审核后图发布。
- infrastructure：内存和 SQLite；审核后的提案、版本、活动指针、发布回执在同一事务提交。
- integration：RuntimeRunRecord 到 Trajectory 的确定性投影；不进入领域层。
- bootstrap：默认内存装配；应用显式装配 SQLite；无导入期目录、连接或全局实例。
- service.py/store.py 保留历史导入，作为兼容入口；新 policy.py 是轻量公开入口。

审核返回版本，额外提供 get_receipt(proposal_id) 查询发布回执。
同提案、同审核人、同内容重试返回原发布结果；更换审核人或内容冲突必须拒绝。
回执跨 SQLite 重启保留；后续新策略和回滚不改写已有回执。
回滚保持追加新版本。旧 Run 的策略快照、768 记忆预算示例与 API 路由保持兼容。

## 图演化边界

GraphEvolutionService 通过注入的生成器、校验器、评测器和发布器编排离线图提案。
生成后校验证据绑定、图身份与版本、非空变更，再调用专业图校验器。
发布要求离线对照结果绑定提案完整指纹，具有非空配对样本，质量不退化、成本不超限；
审核人非空，再交给发布 port。真实拓扑/能力/预算校验和版本 CAS 由正式发布适配器负责，
不能由演化器直接写 RuntimeGraph 或绕开 TaskPlan/规划提交权威。
未配置的能力显式拒绝；不提供随机评测、不声明缺失算法已经实现。
本轮不新建第二套图版本仓库，不把现有运行中修订接口伪装成离线模板发布。
Skills 抽象、自动候选搜索和生产图发布适配器继续清楚列为未接通能力。

## 验收

覆盖 SQLite 故障注入、并发竞争、重启后重试，证据重复/冲突、非法审核人、非有限预算；
覆盖图提案证据和评测绑定、未配置能力拒绝、退化拒绝及注入发布器委派。
AST 检查 application/domain/ports 的依赖方向；运行现有演化、应用装配和 General 黄金链路回归。
