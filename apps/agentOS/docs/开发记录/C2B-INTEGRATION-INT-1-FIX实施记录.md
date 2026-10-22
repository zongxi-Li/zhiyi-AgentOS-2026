# C2B-INTEGRATION-INT-1-FIX：证据完整性与冻结映射

状态：SELF-TESTED，等待独立验收。仅修复只读预检及测试映射，不进入 INT-2。

## 基线与范围

2026-10-22，HEAD/master、origin/master 跟踪关系及 GitHub `git ls-remote mirror refs/heads/master` 均为 `bca40b96136d0616b82b61acb3f8b1ae29d7b416`。入场工作区和暂存区为空，无切分、重置或覆盖用户工作。

入场 449 个 src/tests Python 文件聚合 `503ffa0a8565256ad7cd927a93f7843f4d7a7683812fca2c944f1d190b452367`。保留原 INT-1 基线清单，文件 SHA-256 仍为 `54ccc02a3d0ba550fffff8dd23f259460977ae0a75f3d8eea4d7c1848ce1a591`，没有重新生成基线、移动比较提交或隐藏资源变更。

本轮仅五文件：修改 `src/support/stores/c2_schema_upgrade.py`、根目录 `scripts/freeze_gate.py`；新增 `tests/storage/test_c2_schema_integrity.py`、`tests/storage/test_freeze_gate_integrity.py` 及本记录。原 `test_c2_schema_upgrade.py`、业务 Schema、Contract、CLI、资源实现、Scheduler、Binder、NodeRunner、默认生产装配和正式 Head/Permit 授权语义均未修改。

## P1：原因、真实反例与最小修复

原 `_inspect_one()` 只验证单库结构，且 GROUPS 未表达无独立版本表的 Handoff 前置关系；`inspect_databases()` 汇总结构后直接允许升级。因此 Permit Schema/记录已存在但 Handoff 表丢失时，原 Handoff 升级器可能合法建回空表；Workflow 确认事实依赖的独立 staged 表/正文丢失时，也没有跨库检查。

从真实 `GraphHandoffAuthority.prepare`、`ExecutionPermitAuthority._new_record/_reconcile`、两个 Store 及正式 Contract 重建的依赖如下：

- Permit 升级器要求 Handoff Store 已可构造，因此下游 Permit Schema/表已安装，Handoff 表却不存在，并不是原升级器正常中断的结果。
- Handoff Authority 构造前必须已安装 staged 表。STAGING 是已提交的 Workflow 意图，其正文可以尚未 COMMIT；STATE_PREPARED 则必须已有相同 staged 正文。
- 每一个 PREPARING/ISSUED/REVOKED Permit 都保留正式 handoffId、Handoff 指纹、staged checkpointId、staged 指纹、Run/Activation/GraphVersion/sourceKind/packageChecksum。PREPARING 的恢复也不能抛弃这些证据。
- Run 的既有 executionPermit 投影能证明某个 Permit 已被使用；不能因连 Permit 版本表也丢失就把授权账本视为未安装。

先保存失败反例 `tmp/c2b-int1-fix-before.log`：真实 Runtime 生成已接受、物化、激活、STATE_PREPARED 的图修订，实际执行过 A；需要 Permit 的场景通过原 Authority 签发 ISSUED，然后只在独立临时库中破坏目标表/行。原实现 **6 failed / 2 passed，7.19 秒**：4 个缺表场景误判 UPGRADE_REQUIRED，缺 Handoff 行和已确认 staged 行误判 READY。没有用无关字符串伪造成功 Permit 或执行收据。

新增 `_inspect_evidence()`，在原逐库检查之后、任何目标升级调用之前执行，只读检查：

1. 已安装 Permit Schema/表不能缺 Handoff 表；正式 Run Permit 投影不能引用缺失 Permit。
2. 复用原 Handoff/Permit Store 的反序列化、Contract、索引及 checksum 检验，核对 Permit 与已确认 Handoff 的身份/指纹/编译包绑定。
3. Workflow 已有 Handoff 时，缺 staged 表判 Checkpoint INVALID。STATE_PREPARED 必须有等同于候选的完整正文；原 staged Store 验证正文索引与 checksum。
4. STAGING 可以缺正文行，不能据此假造确认；表存在时保持原 Saga 恢复语义。尚无 Workflow 依赖事实时，Workflow 完成安装而 Checkpoint staged 尚未安装是正常的中断窗口，可以继续升级。

报错定位库、缺失表、Handoff/Permit/Checkpoint/Run ID。INVALID 由原 `upgrade_databases()` 的全库预检阻断，未进入任何目标库升级器。只做事实依赖检查，不判断当前是否有执行权限，不新建 Authority、迁移账本、证据记录或跨库事务。

永久对抗扩展到 9 类损坏：缺 Handoff 表（有 ISSUED 及仅下游空 Schema 两种）、缺 staged 表（STATE_PREPARED、ISSUED、STAGING 三种）、缺 Handoff 行、缺已确认 staged 行、staged checksum 损坏、Permit 表及标记同时丢失但 Run 投影仍在。每例都验证 inspect INVALID、upgrade 拒绝，且三个库完整 SQL dump（建表、索引、触发器与原有行）前后一致。

另有两个正例：真实安装只完成到 Activation 时可续跑；Workflow 完成但尚无 Handoff/Permit 事实时可以安装缺失 staged 表。合法 STAGING 意图与缺正文的外部提交窗口仍可保持 READY，Schema 操作不改变意图、正式图、既有 A 收据或执行状态。正常 Saga 对账仍交原 Authority 完成。

## P2：映射修复与门禁防误报

原基线以来实际差异包含资源公开入口/errors/health_store/node_health/node_store/service/sqlite_support/store、资源 Contract、Scheduler binder/leases/models、Runtime acg_execution，以及 INT-1 模块和相应测试。原解析有 9 个 uncovered source；没有移动基线。

| 源区域 | 实际相关测试 |
|---|---|
| resource/__init__、errors | 节点持久化/健康/时间异常及远端观测、认证入口 |
| resource/node_store、node_health | test_node_store：重启、跨实例健康、过期 nonce、时间异常、连续失败 |
| resource/health_store | test_health_store：共享心跳/健康指标、forced health 持久化 |
| resource/store、sqlite_support | test_store_contract：创建/CAS/nonce/凭据/原子注册/回滚；加健康/节点 SQLite 消费端 |
| resource/service | remote_observation + resource_auth + node_store：可信远端观测/序列/原子更新、注册/凭据/签名 |
| contracts/resource.py | edge_cloud_contracts + binder：画像/观测模型、资源硬约束及模型要求 |
| scheduler/binder、models | test_binder：能力/容量/模型过滤、只读 assess、真实 lease 容量 |
| scheduler/leases | test_redis_leases：原子分配、重放、到期、owner/version 续租与不可用拒绝 |
| C2 运维模块/CLI | 原升级测试 + 新证据丢失反例；原 Identity Schema 合同 |

映射测试还发现旧 `tests/runtime/test_scheduler_handoff.py` 已不存在。Scheduler 前缀映射改为真实 Binder/Redis Lease 用例；ValueStore/Run Fence 的旧悬空映射改为已有 Permit 原生执行用例，当前 Runtime/acg_execution 仍使用原 Permit 核心集合。这是替换无效路径，不是删除或跳过既有测试。

新增 19 个门禁测试：14 个路径各自验证相关测试与真实文件存在；核对整个原始基线 delta、固定基线文件摘要和去重；测试源码变化、Schema 测试失败、超时均不能报告 PASSED；模拟墙钟 301 秒时成功状态必须改为预算未完成。后三类通过受控子进程边界单测真实 `main()/write_report()` 控制流，不用真实长时间等待；SQLite 拒绝本身由前述真实库反例验证。

## 最终快照与已完成测试

最终 451 个 src/tests Python 文件聚合：`b89e62e26d26c3eca968fd2eeaa9af87d475b4f0f90a947e4be58668f287bbc1`。算法保持原 `source_snapshot()`：相对 POSIX 路径排序，原始字节单文件 SHA-256，`路径 空格 摘要` 用换行连接，再对 UTF-8 清单计算 SHA-256；不做换行归一化。

独立文件 SHA-256：门禁脚本 `05d80a198e8045bb90cf1875306ae32bebcaf89b07615ebdcbf25a6ca29f254f`；未修改的升级 CLI `72b55f01379900c658391cb110d142fa7de126f4d9dbea0c3d076b82c3cb08cd`；未修改的应用 API `2127e6e7065db1ca7179b6c5a805bb4c73d2868d5adba12431c2d76d3abe14e3`。环境为 Windows 11 build 26100、Python 3.14.5，默认计时配置。

- 定向实际命令（apps/agentOS）：`python -m pytest -q tests/storage/test_c2_schema_upgrade.py tests/storage/test_c2_schema_integrity.py tests/storage/test_freeze_gate_integrity.py --tb=short --durations=0`。**67 passed / 0 failed**，pytest 20.49 秒，含启动墙钟 **22.739 秒**，exit 0，源码未变。证据 `tmp/c1_audit/c2b_int1_fix_target.log/.json`。
- `python scripts/freeze_gate.py --dry-run`：exit 0，uncovered_source_paths=[]、missing_test_paths=[]，diff check=0；仍比较原 INT-1 基线。机器选集 `tmp/c2b-int1-fix-dry.json`。
- `python scripts/freeze_gate.py`：**174 passed / 0 failed / 0 skipped**，总墙钟 **32.614 秒 / 300 秒**，exit 0，PASSED，源码起止相同。证据 `tmp/freeze_gate/20261022T033129Z.json/.log`。没有增大预算、删减慢测试规则或改 deadline。
- 扩大回归（apps/agentOS）：`python -m pytest -q tests/components/resource tests/components/scheduler tests/storage tests/contracts tests/architecture --tb=short --durations=10`。**245 passed / 0 failed**，pytest 22.91 秒，总墙钟 **25.035 秒**，exit 0，源码未变。证据 `tmp/c1_audit/c2b_int1_fix_expanded.log/.json`。
- 外部 API：`python scripts/verify_mission_semantics.py apps/agent/tests/test_agentos_v2_api.py`，**52 passed / 0 failed**，pytest 11.75 秒，总墙钟 **13.856 秒**，exit 0，源码未变。证据 `tmp/c2b-int1-fix-api.log/.json`。复用现有脚本隔离 cwd、环境与临时库，未扫描/清理用户旧临时目录，也未把 API 结果混算进 174 项冻结门禁。
- 完整 AgentOS 回归（本轮用户明确授权，apps/agentOS）：`python -m pytest -q --tb=short`。**1992 passed / 0 failed / 0 skipped**，3 warnings，pytest 1037.91 秒，总墙钟 **1040.474 秒**，exit 0。UTC 2026-10-22 03:36:23.812461 至 03:53:44.286922（北京时间 11:36:23.812461 至 11:53:44.286922），451 文件及外部 API/CLI 摘要起止完全一致。证据 `tmp/c1_audit/c2b_int1_fix_full.log/.json`。未传 marker 过滤、未请求 1ms、未修改原 timeout，按完整默认选集执行。该 17 分钟深度回归独立于 32.614 秒冻结门禁，不冒充五分钟内完成全量。

本轮无因预算或环境遗漏而待补的已要求测试批次；没有 INCOMPLETE 批次。各批次存在重叠，不相加声称独立用例总数。全部最终结果对应同一最终源码快照；只在测试完成后补报告文字。

开发期间曾有新增门禁测试夹具漏提供 subprocess.STDOUT 的错误，补全替身后控制流测试通过；原不存在的 Scheduler 测试路径由永久映射测试识别并修正。没有为了通过反例而弱化数据库或执行断言。全部最终结果只归属于上述最终快照，中间失败日志不充当最终通过证据。

## 外部 API 工作流与剩余边界

AgentOS pytest.ini 的默认 testpaths=tests 不包含 `apps/agent/tests/test_agentos_v2_api.py`，本次冻结门禁也不覆盖它。已有 `scripts/verify_mission_semantics.py` 的 **audit** 集合显式包含该文件；默认 api 集合不包含它。GitHub 当前只有 backend-ci.yml 的 Maven 门禁，不等于自动执行 Python API 验证。本轮使用既有隔离脚本仅运行该文件，结果另记，不扩大冻结门禁职责。

本预检仍需要停服维护窗口。不同数据库、不同只读连接不具备联合 CAS/联合快照；不能抵御在线业务或管理员在检查后删除证据。没有声称 READY 能授权激活、派发或恢复，也没有检查/修复所有业务数据的语义真实性；当前检验的是已存在授权账本所需的结构及持久证据依赖。历史证据的 GC/归档协议不在本轮，不能自行清理以绕过拒绝。

最终 `git diff --check` exit 0（仅 Git LF/CRLF 提示）；HEAD 保持入场提交，暂存区为空，五个阶段文件均未暂存/未提交。未修改基线清单、用户既有文件、业务数据库或默认生产接线，未 Commit、Push、Merge、部署。可申请本阶段独立验收；本报告不宣布 ACCEPT，不授权进入 INT-2 的生产装配。
