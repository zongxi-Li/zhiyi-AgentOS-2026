# PR-S03-02B1-GATE：合法 DAG 性能基准与冻结复核

**结论：GATE 通过，建议将 B1 升级为受限合同下的 ACCEPT 并冻结。** 合法 DAG 性能证据已补齐，定向、扩大和全量回归均通过，未发现新的 P0/P1。跨库竞态和生产性能边界按第 6 节明确保留。本轮不修改既有独立报告的历史 CONDITIONAL 结论，冻结复核应同时引用本报告及原独立报告。

## 1. 入场基线与改动范围

入场及当前 HEAD 为 `48b7fc950837e1bdcec07abfd181f4d8fa95b6db`，分支 `master`，暂存区为空。B1 原有 1 项 tracked 修改、5 个 Python 新文件和两份阶段文档均保留。用户 EX-00 文档保持未跟踪、未暂存，SHA-256 为 `2bbea373edeaefcfe9e6caca072f15c8f249c1f81dfd21380bcd8c7a0c39bf35`。

运行期间检测到并行任务修改 `README.md`、生成 `docs/assets/` 图形资产，并在 `docs/架构设计/架构图/` 生成 `知弈AgentOS-ACG架构图.png` 和 `知弈AgentOS_ACG总体架构.png`。这些范围外文件曾在中途核验时撤出、最终核验时再次出现，HEAD 始终未变化。本轮没有对它们执行覆盖、恢复、删除或暂存；最终保留这些用户并行工作。它们不参与 src/tests 源码摘要，也不作为本次架构或测试结论的证据。

入场的 425 个 `src/tests` Python 文件聚合为 `0b17d8ebd0f8706b027f87c93831a4e4209eadb51595225fcf38857f40d1f84b`，与独立验收匹配。本轮仅新增一个 Python 测试文件 `apps/agentOS/tests/components/planner/test_graph_handoff_gate.py`；排除该新文件后，原有 425 文件的聚合仍与入场完全相同。生产源码、B1 两项 P1 修复和原有测试字节均未变动。

最终 426 个 Python 文件的冻结验证快照：

`7fd909bb7defa769f1b400364ae2faeef3e1c8052ae75b208edbf873d523b7ba`

算法沿用独立报告：按仓库相对路径排序，每行 `path + 空格 + SHA-256(raw bytes)`，LF 连接、不添加尾 LF，再计算 SHA-256。完整清单由每组门禁前后逐项核对。两份本轮新增文档为本报告和 `PR-S03-02B1-GATE-性能原始样本.json`，不计入 Python 摘要；原独立报告保持原样。

## 2. 合法 DAG 的构造及权威链

新测试通过确定性的 `SemanticPlanner.plan_template` 显式声明任务数量，经原 `validate_task_plan_for_execution` / Topology Compiler、`build_template_lowering_input`、`ACGLowerer` 及 `SemanticRevisionService._validate_bindings` 构造初始执行包。只在测试 Runtime 的 `_build_acg_blueprint` 构造缝隙中选择声明好的 template；没有调用不确定 LLM，没有改 Planner 默认数量、节点预算、Compiler 或生产配置。

每个形状是单一能力的无控制依赖链。候选图规模为 4、8、16、32、64、128；初始图为 N−1 个节点，真实 Native Runtime 执行依赖闭合前缀后，在正常 Planner wait 边界暂停；随后正式接受新增 D 和“原最后节点→D”的关系。只提交新增关系，原关系由正式 patch 语义保留。每份候选都通过实际 Planning Commit、Graph Revision、Materialization、Activation，再进入 GraphHandoffAuthority；没有手工写入收据、Attempt、输出或 accepted Journal。

各规模均做 3 份全新独立临时数据库样本，完成前缀为 1；另在 32 节点图上分别做完成前缀为 4 和 8 的各 3 份样本。加上 4/32/128 节点的 3 份跨 Mission 试验，共 27 份有效数据库夹具，实际执行 57 个 Native 节点。每个完整 API 均成功返回 `STATE_PREPARED`。全部包节点数等于指定 N、边数 N−1，没有悬空边。

身份完备性按 B1 冻结合同校验：所有源计划节点均有真实 TaskId、SemanticTask、TaskBinding 和完整 PlanNodeKey/ACG ID 映射；真实完成节点有成功 Identity Attempt、StepExecution、Receipt、ValueStore 与审计决策。候选新增 D 具有计划 key 和 TaskImplementationBinding，并保持 pristine pending；它不提前创建正式 v2 SemanticTask/Attempt。后者属于后续身份交接边界，不能为满足基准而提前实施。此基准不宣称已验证新节点的正式 Identity promotion。

开发中出现的无效夹具均由正式合同拒绝：通信 channel 与正式派生规则不一致时 Safe-Cut 拒绝；patch 重复提交指向已完成节点的旧关系时接受合同拒绝。另曾把 checkpoint 列名误写为 run_id、以及 instrumentation proxy 未转发 row_factory；均为测试侧错误，修正后完整重跑，未修改或放宽生产合同。

## 3. 观测方法、环境及精度

环境：Windows 11 10.0.26100，Python 3.14.5，SQLite 3.50.4，Intel Core i9-14900HX（24 核/32 线程）。使用默认 Windows 定时设置，没有调用或请求 `timeBeginPeriod(1)`，未更改 SQLite busy timeout、synchronous、deadline 或安全校验。数据库全部位于 pytest 临时目录。

测试侧 `TransactionProbe` 包装真实 Connection，原样执行 `BEGIN IMMEDIATE` 与 `commit()`；`observe_cost` 包装实际验证、Compiler、Safe-Cut、stage 调用。SQL trace 同时覆盖临时新连接和既有持久 Identity/Checkpoint/Value/Audit/Memory/Provenance 连接。没有移动事务或删除最后来源重验。

计时采用 `time.perf_counter()`，单位 ms，明确区分：

- API：调用 `prepare_graph_handoff` 到返回的总时间，包含入口、所有验证、两次 Workflow 事务及外部 stage。
- 事务：调用 BEGIN 前到 COMMIT 返回，含 BEGIN 调用时间；不含连接建立与进程 RLock 进入前的等待。
- BEGIN 调用：开始 execute 到成功返回，包含等写锁和 SQLite 自身执行开销。Python 标准绑定无法拆分内部忙等与执行成本，不能把这个数当成纯 busy wait。
- 锁内主体：BEGIN 成功返回至调用 COMMIT 前，整个区间肯定持有写事务。
- 持锁观测：BEGIN 成功返回至 COMMIT 返回。SQLite 在 BEGIN 返回之前已经取得锁、在 COMMIT 返回之前释放锁，因此这是 API 边界观测近似，不是 SQLite C 层物理锁事件的精确纳秒值。原始数据另列 commit_ms、begin_start/acquired/commit_start/released；没有把 API 总时间冒充持锁时间。
- 前缀证据跨度：从实际 `load_ledger` 到最终 Run 重读后、IdentityLink 构造前，覆盖收据/执行事实/输出/记忆/Identity Attempt 等校验。早于它的源 Identity 逐节点计划映射校验包含在完整 validation 时间中，没有伪称该跨度是所有前缀校验的独占时间。

每个 API 固定观测到 3 次完整来源验证、6 次 `compile_package`、3 次 Safe-Cut 和 1 次外部 stage。Compiler/Safe-Cut/前缀计时嵌套于 validation，不能与 validation 相加。SQL 计数是实际 SELECT 语句次数，含元数据查询，不等于读入对象数、返回行数或磁盘 I/O 次数。

以下分档统计均为 **中位数 / 最大值**，每个形状 n=3。样本不足以报告有意义的 p95，更不能据此宣称最坏时延上界。独立数据库避免同 key 缓存重放；OS 文件缓存未人为清空，因而不代表冷启动磁盘基准。

## 4. 分档数据

| 节点/完成 | API | 首次完整验证 | STAGING事务 | 外部stage | 最终事务 |
| --- | --- | --- | --- | --- | --- |
| 4/1 | 172.43 / 181.48 | 73.04 / 76.59 | 39.76 / 46.46 | 3.33 / 3.68 | 48.47 / 53.49 |
| 8/1 | 197.56 / 215.26 | 86.02 / 89.59 | 47.18 / 57.48 | 3.84 / 4.02 | 55.15 / 58.49 |
| 16/1 | 203.21 / 237.56 | 73.80 / 95.37 | 55.77 / 66.30 | 3.32 / 3.80 | 64.97 / 65.42 |
| 32/1 | 324.97 / 354.37 | 111.25 / 120.25 | 90.60 / 93.74 | 3.91 / 4.10 | 97.61 / 144.12 |
| 64/1 | 523.11 / 535.95 | 173.10 / 177.62 | 160.64 / 164.73 | 3.80 / 4.33 | 172.60 / 204.61 |
| 128/1 | 1492.57 / 1510.61 | 487.74 / 520.40 | 481.95 / 524.37 | 3.67 / 3.79 | 493.94 / 519.21 |
| 32/4 | 403.76 / 414.90 | 114.09 / 132.50 | 110.34 / 157.32 | 3.57 / 4.13 | 118.99 / 160.47 |
| 32/8 | 516.89 / 549.70 | 188.04 / 222.40 | 152.56 / 161.82 | 3.70 / 3.86 | 153.72 / 160.76 |

| 节点/完成 | STAGING BEGIN耗时 | STAGING持锁观测 | 最终BEGIN耗时 | 最终锁内主体 | 最终持锁观测 |
| --- | --- | --- | --- | --- | --- |
| 4/1 | 1.12 / 1.20 | 38.65 / 45.26 | 8.74 / 9.19 | 38.83 / 42.95 | 40.85 / 44.30 |
| 8/1 | 1.18 / 1.84 | 46.00 / 55.64 | 8.83 / 9.58 | 45.88 / 48.39 | 46.32 / 48.91 |
| 16/1 | 1.10 / 1.66 | 54.68 / 64.64 | 8.19 / 8.47 | 55.79 / 60.96 | 56.95 / 62.57 |
| 32/1 | 1.68 / 1.76 | 88.95 / 91.98 | 1.73 / 1.84 | 93.11 / 140.89 | 95.87 / 142.29 |
| 64/1 | 1.64 / 1.91 | 159.00 / 162.83 | 2.15 / 7.36 | 167.88 / 196.70 | 170.86 / 197.25 |
| 128/1 | 1.72 / 1.76 | 480.19 / 522.66 | 1.65 / 1.98 | 489.73 / 515.34 | 492.34 / 517.23 |
| 32/4 | 1.63 / 1.68 | 108.67 / 156.21 | 1.75 / 1.87 | 115.28 / 156.33 | 117.13 / 158.72 |
| 32/8 | 1.90 / 2.47 | 150.72 / 159.35 | 1.92 / 2.02 | 149.04 / 155.79 | 151.69 / 158.84 |

| 节点/完成 | 最终完整验证 | 全API Compiler合计 | 全API Safe-Cut合计 | 全API前缀证据跨度合计 | Identity/Values/Checkpoint/Audit SELECT |
| --- | --- | --- | --- | --- | --- |
| 4/1 | 35.76 / 39.93 | 3.10 / 3.20 | 10.38 / 11.45 | 25.97 / 31.25 | 84/45/16/3 |
| 8/1 | 42.77 / 45.25 | 5.25 / 5.37 | 12.41 / 12.44 | 25.73 / 26.85 | 120/45/16/3 |
| 16/1 | 52.57 / 58.27 | 8.57 / 8.91 | 12.83 / 13.15 | 27.00 / 36.63 | 192/45/16/3 |
| 32/1 | 90.36 / 137.91 | 17.36 / 18.30 | 17.23 / 18.18 | 32.26 / 78.01 | 336/45/16/3 |
| 64/1 | 164.48 / 193.73 | 36.80 / 39.73 | 26.07 / 26.44 | 39.53 / 39.65 | 624/45/16/3 |
| 128/1 | 487.03 / 512.04 | 86.82 / 87.01 | 41.18 / 42.58 | 55.18 / 110.13 | 1200/45/16/3 |
| 32/4 | 111.52 / 153.42 | 16.94 / 17.62 | 20.73 / 20.85 | 71.33 / 75.24 | 435/135/16/12 |
| 32/8 | 145.80 / 152.16 | 20.36 / 72.31 | 28.61 / 30.12 | 147.23 / 155.82 | 567/255/16/24 |

| 节点/完成 | Run正文B | v1 Checkpoint JSON B | Package JSON B | Stage JSON B | Identity逻辑页B / SQL dump B |
| --- | --- | --- | --- | --- | --- |
| 4/1 | 35193 | 1084 | 2829 | 1177 | 393216 / 76220 |
| 8/1 | 50825 | 1084 | 5417 | 1177 | 430080 / 110596 |
| 16/1 | 82094 | 1084 | 10593 | 1177 | 491520 / 179363 |
| 32/1 | 136558 | 1084 | 20945 | 1177 | 638976 / 316867 |
| 64/1 | 243182 | 1084 | 41649 | 1177 | 913408 / 591875 |
| 128/1 | 456435 | 1084 | 83057 | 1177 | 1519616 / 1141901 |
| 32/4 | 164675 | 2019 | 20945 | 2057 | 1273856 / 931824 |
| 32/8 | 203189 | 3275 | 20945 | 3237 | 2248704 / 1880185 |

| 节点数 | A最终持锁观测 | B事务外保存API | B事务外BEGIN | B争用保存API | B争用BEGIN | B同内容重试API | 结果 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 4 | 46.49 | 7.51 | 0.02 | 64.35 | 57.70 | 4.37 | 全部SAVED |
| 32 | 113.81 | 8.32 | 0.02 | 120.03 | 103.34 | 5.42 | 全部SAVED |
| 128 | 519.49 | 8.61 | 0.02 | 623.72 | 607.93 | 5.20 | 全部SAVED |

持久化大小表取各形状的第一份代表样本，不是文件大小上限。JSON 大小与 SQLite 主文件大小分开；Identity 使用当前快照的 page_count×page_size 和完整 SQL dump 字节数，包含 schema、源 Mission 和单节点 writer Mission。WAL 模式下单看主文件 4096 B 会严重低估实际数据；配套原始样本逐一保留主文件、WAL、SHM 大小。

## 5. 跨 Mission 写锁与安全不变量

Mission B 使用独立 `SQLiteWorkflowStore`、独立连接，对自己的普通 Run 做合法 updated_at 保存。A 在第一次事务外验证回调中同步调用一次 B 保存，之后继续真实验证；A 最终事务 BEGIN 成功后，通过 Event 让另一个线程的 B 连接实际尝试 BEGIN。A 不等待 B 写入完成，保持原生产事务顺序。线程 Event 只用于建立重叠事实，可能给争用样本增加少量调度成本；纯分档样本没有这项握手。

3 个争用样本均满足 B 的 BEGIN 调用发生在 A 已持有最终事务期间，且 B 获得写锁在 A 的 COMMIT 开始之后。B 在 A 事务外能够正常写入；最终事务期间发生可观测阻塞，128 节点例中 B 的 BEGIN 调用耗时 607.93 ms、保存 API 623.72 ms。SQLite busy/backoff 和线程调度使等待时间可能长于 A 当时剩余的持锁时间，不能直接把二者相减当作数据库执行成本。所有写入成功，实际 busy timeout 均为原值 5000 ms，没有触发 timeout。

每次争用后重试相同 B Run 快照，普通保存成功、lifecycle outbox 行数不增加；按 A 原 key 重放得到 `IDEMPOTENT_REPLAY`，Journal 身份仍唯一。所有样本均验证：

1. 正式 graph_activation_heads 仍只有该 Run 的唯一版本头（v2），Handoff 不创建新 GraphVersion。
2. A 的 Run、TaskPlan/正式图、formal Checkpoint 全表及旧 v1 最新恢复头完全不变；staged checkpoint 不能通过普通 Checkpoint Store load 找到。
3. Identity、ValueStore、Audit、Memory、Provenance、Content 数据库的逻辑 dump 前后相等，所有完成收据与 Audit Decision 引用一致。
4. 完成前缀保持依赖闭合，候选其余节点无 attempt/retry/output/resolved_input/时间戳；没有重执行任何已完成节点。
5. `STATE_PREPARED` 没有 executionPermit。显式尝试执行仍因缺少 Permit 被拒绝，拒绝前后正式存储不变、Agent calls 不增加。

## 6. 风险分类与受限运行建议

本轮没有发现新的 P0/P1；旧两项独立 P1 修复原字节保留，原有 67 项定向测试均通过。本轮没有性能优化，也没有弱化最终 Fence。

已量化的 P2：Workflow SQLite 是库级写锁。纯样本最终持锁观测约 39.59–517.23 ms，STAGING 事务也会持锁；128 节点例 STAGING 持锁最大 522.66 ms。其他 Mission 的普通保存确实会受到影响，不能称为“完全不阻塞”。图节点从 4 增至 128 时 API 中位数由 172.43 ms 增至 1492.57 ms，约 8.66 倍；Identity SELECT 由 84 增至 1200。固定 32 节点、完成数由 1 增至 8，API 中位数从 324.97 ms 增至 516.89 ms，前缀证据跨度合计中位数从 32.26 ms 增至 147.23 ms。节点数和证据量都带来实际成本。

128 节点、1 个完成节点是本轮验证的最大规模，不是生产合同的硬上限；既有 256 节点/2 MB 限制未改。32 节点、8 个完成节点是本轮证据量最大样本；没有证明“128 节点×8 个完成节点”的组合上界。当前只建议在显式启用的单主机、低频规划交接中受限冻结；同一 Workflow DB 的 Handoff 应按运维策略单飞处理，启用范围限制在已测形状/规模，不把该建议误写成已经实现的自动限流。

未验证最坏情况包括：密集 DAG、高扇出/共享前置、大输出/记忆/来源正文、更多完成收据、256 节点上限、冷磁盘/网络盘、多个 Handoff 同时争用、长期 writer 饥饿和 busy timeout 恢复压力。暂时只有依赖链 n=3 样本，不建立全局复杂度或生产 SLA。三次完整验证、逐节点 Identity 读取、重复集合构建/序列化是保留的性能热点；若未来优化，必须独立证明没有削弱最终当前状态校验。

跨数据库没有联合 CAS 的事实保留。Workflow、Checkpoint、Identity、Value/Audit/Memory/Provenance 和权限来源不能共同原子提交；本次计时通过不能消除最终外部来源读取后的竞态。STATE_PREPARED 是历史准备事实；本地文件 fence 也不代表已证明多主机分布式互斥。STAGING/orphan stage 的生命周期清理边界维持既有约束。

## 7. 最终回归与源码门禁

工作目录 `apps/agentOS`。定向命令使用 `-s` 保留机器可读的基准原始数据；扩大和全量使用用户给定原命令。各组串行执行，Luna 只承担固定快照的机械回归与结果收集。

| 门禁 | 实际命令 | 最终结果 |
| --- | --- | --- |
| 新增性能/正确性 + 原 B1 | `python -m pytest -q -s tests/components/planner/test_graph_handoff_gate.py tests/components/planner/test_graph_handoff.py tests/components/planner/test_graph_handoff_recovery.py --tb=short` | 78 passed，0 failed，441.77s；完整源码清单前后一致 |
| 扩大 | `python -m pytest -q tests/components/planner tests/contracts tests/architecture tests/runtime --tb=short` | 1115 passed，0 failed，907.08s，退出码 0；完整源码清单与 HEAD 前后一致 |
| 全量 | `python -m pytest -q --tb=short` | 1730 passed，0 failed，1 warning，1433.61s，退出码 0；完整源码清单与 HEAD 前后一致 |

扩大门禁第一次启动后，发现另一个用户任务已于 22:36:01 启动 `py -3.14 -m pytest tests -q`，其 launcher 和 Python child 代表同一个外部测试任务。为避免并行测试干扰，停止并保留本轮尚未完成的扩大试跑，不把部分进度当作通过；日志为 `tmp/S03-02B1-GATE-final-broad.interrupted-external.log`。未终止外来进程。待其结束后重新核对 HEAD、完整清单及无并发 pytest，才从头执行扩大门禁；性能原始样本在该外来任务启动前已经完成，不受这次后启动的任务影响。

扩大和全量的 wall clock 分别为 910.541s、1436.725s；表格采用 pytest 自报耗时，不混用两种口径。全量唯一 warning 是既有 `test_pdf_and_docx_extractors` 的 PyPDF2 弃用提示。没有跳过或放宽用例，没有请求 1ms 定时精度。最后再次核对完整 426 项文件清单和 HEAD，均与第 1 节快照一致；`git diff --check` 通过，新测试及本轮报告无尾随空白。

机器可读计时原文在同目录 `PR-S03-02B1-GATE-性能原始样本.json`，包括 24 个独立分档样本及 3 个争用样本。可重跑测试从 stdout 的 `HANDOFF_GATE_RESULT` / `HANDOFF_GATE_CONTENTION` 提取相同结构的数据。临时日志与逐组快照记录保留于 ignored `tmp/S03-02B1-GATE-final-*`，不是正式运行状态或数据库。

## 8. 冻结建议与 B2 前置条件

本轮数据足以关闭原 CONDITIONAL 中“没有有效大于最小 DAG 性能证据”的缺口：最大已验证图为 128 节点，全部正式校验与准备成功；重复样本给出了来源验证、两段事务、外部 stage、锁内主体及跨 Mission 阻塞的实际范围；完整原有安全测试和最终全量均通过。

因此建议 B1 在单主机、显式启用、低频且接受上述阻塞与规模限制的合同下冻结，并由最终独立冻结复核确认 ACCEPT。该建议不要求或授权任何性能优化、生产装配或提交操作。当前 HEAD、暂存区和 EX-00 均保持入场状态；本轮新增测试与两份证据文档、此前 B1 实现及修复仍留在未提交工作区。

即使升级 B1 验收，也只确认可信 staged Handoff 在当前受限合同内成立，绝不代表 Execution Permit、Checkpoint Promotion、Native Scheduler Handoff 或生产性能已经验收。

S03-02B2 必须保留当前 Activation/GraphVersion/accepted Revision 的来源链和 CAS；在发放 Permit 前重新检查 Run、取消信号、审核和操作员输入、全部完成收据与正式 Checkpoint head、权限/scope/Identity 及绑定；重验 stage 全文、摘要和编译策略。正式 Permit 至少绑定 Run、Activation、GraphVersion、staged checkpoint identity 与 attempt generation，并定义跨库部分成功、ACK 丢失及幂等 Promotion 的恢复机制。普通审核批准、历史 PREPARED 回执、旧 v1 Attempt 或迟到 Receipt 不得取得新图执行权。B2 仍需自己的独立验收，本轮未实现这些能力。
