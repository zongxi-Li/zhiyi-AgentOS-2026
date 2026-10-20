# PR-S03-02C1-FIX：交付物授权与纵向闭环缺陷修复

日期：2026-10-19。状态：**SELF-TESTED，等待第二轮独立代码级验收**。不是独立ACCEPT，也不是生产装配或部署验收。

## 1. 入场与修改边界

HEAD为已冻结B2 `9921a75cf6cfff46388f923795c3878b9aa072cc`，暂存区为空。已完整阅读C1实施记录、独立验收报告和对应源码；入场摘要严格匹配独立验收：

- src/tests：437个Python文件，`c6315f1d14195aaf9598c4f482bc54f08a74989ce37138c91929a232b94e1a07`。
- 应用API：`3d5d528637610ef75a992193d225734434fdb225660c743fc5fff75d35f292be`。
- freeze_gate：`f64a4ca65b30b5ceb5e5a2173edb183a226c448f89cbf8ecd8460a5554cd44ab`。

原C1的API、planning_loop、门禁脚本修改，以及样例、纵向测试和两份报告均保留，未恢复/清理/覆盖其他用户工作。独立验收报告保留当时REJECT与失败证据，不将其改写为修复后ACCEPT。

相对本轮入场，实际修改范围：

| 文件 | 本轮变化 |
|---|---|
| apps/agent/app/api/agentos_v2.py | 提取当前Mission读取授权；保护Artifact、Manifest与原始output正文；修正下载解析 |
| apps/agentOS/src/examples/contract_review.py | Store构造前检查目录、8个数据库及必要Schema；只读隔离副本包含WAL |
| apps/agentOS/tests/runtime/test_contract_review_delivery.py | 新增36个永久回归节点，使用真实Native任务、临时SQLite、正式router与认证中间件 |
| scripts/freeze_gate.py | 仅扩充既有API/样例映射，加入新回归模块；预算、选择算法、marker及超时不变 |
| 本报告 | 根因、失败证据、实现边界及最终结果 |

按入场逐文件清单比较，原437个内核Python文件中仅样例入口发生变化，另新增1个测试文件，其余436个文件逐字节不变。应用API与脚本另行记录，不能仅用内核聚合替代跨层验证。未修改Planning Commit、Safe-Cut、Materialization、Activation、Handoff、Permit、ResourceBinder、NodeRunner、Identity、Receipt、Checkpoint或PermitRecovery实现。

## 2. P1：复用唯一的当前Mission读取授权

根因是查询路径只检查Run输入中的owner/tenant和对象归属，没有调用当前正式Mission读取授权。可信旧owner身份因此仍可读取正文，而Workspace已经拒绝。

`agentos_v2.py:744 require_current_mission_read`复用原`MissionSemanticService.get_effective_snapshot`；服务内部每次先调用`authorize(principal, missionId, "read")`，只接受显式True。主体来自原`current_semantic_principal()`认证上下文，不接受请求中的授权标志、Receipt或Binding替代。该函数返回已授权的snapshot/Mission，Workspace继续使用原Resolver进行投影，没有第二套权限数据库、状态或授权算法。

`load_content_run`先调用原只读`load_run`，保留owner/tenant及软删除检查，再核验当前正式读权限。正式冻结Run具有不可变`missionIntentBasis`，缺失服务不能降级成legacy放行，返回503；已装配服务拒绝授权返回403、资源不存在/软删除返回404、已知来源不可用返回503。跨owner/tenant仍在原检查处按404隐藏对象。原认证中间件及非正式legacy宿主兼容合同保留。

实际覆盖入口：

- Artifact列表、Artifact/Manifest元数据、fragments、download均经过当前授权；两种ID仅用于定位同一对象。
- Identity Artifact还检查sealed/kind及Manifest的owner是否对应真实origin Run，并校验来源Run的当前读取权限；目标Run仍须存在合法Binding。没有通过新映射改变Artifact归属。
- `require_manifest_access`对Run归属的直接Manifest引用同样检查当前权限，不能经materials元数据路径绕过。
- ValueStore原始output可能包含相同Artifact正文，也必须检查当前权限。读取通过现有只读缓存核对Workflow Run，保留ValueStore的同Run/kind检查和legacy当前ref限制。

自查额外固定了同一缺陷的滞后投影反例：通过正式WorkflowStore软删除Run，但Identity投影尚未更新，`/runs/{id}/outputs/{ref}`仍200。失败日志为`tmp/c1_audit/c1_fix_deleted_output_before_reproduced.log`（1 failed，pytest10.24s）；永久断言纳入`test_invalid_artifact_cannot_be_restored_by_direct_reference[deleted_run]`，修复后404。该修复只影响读取，未增加执行权限或改变删除/Identity协议。

读取授权不缓存允许结论。永久测试在同一TestClient、相同旧owner/tenant下依次授权→撤销→恢复授权，验证Workspace与两种ID的元数据/fragments/download分别200→403→200。跨user、跨tenant、无token、无actor、跨Run、未知引用、删除Run、缺失/未封存/归属错误Manifest均有拒绝断言。已有执行授权服务及调用前Guard不变。

## 3. P2：统一下载别名

根因：`get_artifact`已经将Artifact ID解析成真实Manifest，但download仍把原始请求参数交给`stream_assembly`，触发Content Store KeyError。

下载现在与fragments一样使用已授权结果的`manifest["manifestId"]`，不改变Content Store主键语义。两种ID下载均200、原始bytes逐字一致，SHA-256均等于真实Artifact的checksum。未知或跨Run引用在进入StreamingResponse之前404，撤权在读取正文之前403。

## 4. P2：无副作用的恢复预检

原样例在确认必要数据库/Schema前构造SQLiteWorkflowStore，构造器会创建数据库、WAL/SHM与基础Schema。仅有合法marker的目录因此在最终拒绝前被写入。

`contract_review.py:_preflight_resume`位于全部Store构造之前：

1. 验证原样例marker与目录，要求workflow、checkpoint、identity、content、values、memory、provenance、audit八个现存正规数据库文件；拒绝DB符号链接和未结算rollback journal。
2. 原目录只做文件读取。将数据库及现有WAL复制到隔离临时目录，使用`mode=ro`、`query_only`检查副本。副本产生的WAL/SHM仅在临时目录清理，不在恢复源创建文件。
3. 不对源库使用`immutable=1`：它会忽略已提交WAL；直接`mode=ro`打开WAL源库则可能创建SHM。回归专门证明必要表仅存在于committed WAL时仍可通过，源目录清单与哈希不变。
4. 检查必要表、列、版本和会被构造器自动补建的索引。Identity表列/索引从现有canonical SCHEMA_SQL在内存中派生，版本使用既有CURRENT_SCHEMA_VERSION；Graph相关完整定义直接复用原Store只读Schema校验。未增加正式Schema权威或业务状态。
5. 所有检查成功后，才装配原Runtime与Store、重新使用原Authority校验执行状态。不调用源库升级方法，不改变全局SQLiteWorkflowStore构造行为。

初次预检自查发现：只检查表和版本仍会让缺失Identity索引被原构造器自动补建。修复前反例`tmp/c1_audit/c1_fix_missing_index_before.log`为1 failed（pytest6.26s）。现有索引检查及Identity/Workflow/Content缺索引永久反例封闭此路径。

12种非法输入（marker-only及缺文件、空库、缺表、旧Identity版本、旧ValueStore列、错误Permit Schema、错误marker、三类缺索引、未结算journal）均在Store构造前拒绝。测试替换构造器为“调用即失败”，并比较所有相对路径和文件SHA-256，确认拒绝前后无变化。合法恢复继续走真实Native Runtime。

## 5. 先失败、后修复的证据

四个原反例先迁入正式测试目录，生产代码仍为独立验收版本时执行：

`python -m pytest -q tests/runtime/test_contract_review_delivery.py --tb=short`

实测 **4 failed**，pytest9.33s、墙钟15.209s。两种ID撤权后正文200、下载Artifact ID触发KeyError、marker-only目录产生数据库；原始记录`tmp/c1_audit/c1_fix_before.json/.log`。该复现因增加测试而聚合变为`c798a5e48d62683b9b08ad7c80475e4e1ed505d559c122a825d1d0f6ff8a9fff`，API仍是入场3d5d...，没有将迁入测试后的摘要冒充原437文件快照。

四项断言未删除或放宽，均包含在最终36项永久回归中。开发中提取Workspace公共函数时曾遗漏投影所需semantic_record（随后修正），新复制夹具也曾因未显式关闭SQLite连接而被Windows拒绝删除（改为closing）；这些中间失败不作为最终验证。未修改既有测试、deadline或计时精度。

两次中间快照扩大回归在补齐原始output删除检查、预检索引检查前分别停止，没有完整结果，不计为通过或最终证据。最终范围完整重跑，没有跳过原有用例。原始output探针首次有import路径错误，修正临时工具路径后才得到生产路径失败，未将收集错误当成产品缺陷。

## 6. 最终快照与测试

所有最终测试基于以下同一快照：

- src/tests共438个Python文件：`bcdd603ad829d08338a459a91319f22a0fd839681f9f5d45ef7d93e8efba0f97`。
- 应用API：`b78ffdd8d0b1c004f9befdd63c7372070cf9a733c244f86591328897791ccc21`。
- freeze_gate：`bceba8893df4c99f34908d2cb91f7b616922c56d5768b3100f7841cf83783d9c`。

聚合算法与独立验收一致：src/tests .py原始字节逐文件SHA-256，仓库相对POSIX路径排序，用LF连接`路径 空格 摘要`（无尾LF），再对UTF-8清单SHA-256。API和脚本另行验证；最终测试后再次复算，不复用旧C1摘要作为结果。

环境：Windows NT 10.0.26100、Python3.14.5、默认计时；未请求1ms、未用xdist、未修改超时。本轮用户明确要求扩大与全量，它们作为单独L3执行，不冒充300秒冻结门禁。本轮不创建冻结Commit，测试选择策略不变，仅把新模块加入已有映射，后续门禁不会因代码提交而遗漏这些永久反例。

| 最终范围 | 命令（cwd=apps/agentOS） | 结果 |
|---|---|---|
| 永久反例/C1/既有应用兼容 | `python -m pytest -q tests/runtime/test_contract_review_delivery.py tests/runtime/test_kernel_vertical_slice.py ../agent/tests/test_agentos_v2_artifact_api.py ../agent/tests/test_agentos_v2_workspace_api.py ../agent/tests/test_agentos_v2_api.py::test_v2_output_uses_identity_access_without_loading_full_runtime_run --tb=short` | **44 passed / 0 failed**；pytest24.70s、墙钟27.126s；UTC11:58:09→11:58:37；`c1_fix_release_targeted.json/.log` |
| Planner/Contracts/Architecture/Runtime | `python -m pytest -q tests/components/planner tests/contracts tests/architecture tests/runtime --tb=short` | **1199 passed / 0 failed**；pytest1694.45s、墙钟1697.846s；UTC11:58:57→12:27:15；`c1_fix_verified_expanded.json/.log` |
| AgentOS全量 | `python -m pytest -q --tb=short` | **1814 passed / 0 failed，3 warnings**；pytest1272.02s、墙钟1275.576s；UTC12:27:19→12:48:35；`c1_fix_verified_full.json/.log` |

本轮日志/JSON位于`tmp/c1_audit/`，运行器保存实际命令、起止时间、墙钟、返回码及运行前后源码摘要。范围之间有重叠，不累加成独立测试总数；AgentOS全量不等于agent应用全部测试或Java/Vue全仓测试。

最终专项、扩大、全量均返回0，运行前后内核及API摘要一致；结束后再独立复算本节三组摘要，全部匹配。HEAD未移动、暂存区为空，`git diff --check`退出0，仅原有LF/CRLF转换提示。未发现本轮范围外新增源码变动，原C1实现/测试/报告保留。核对记录为`tmp/c1_audit/c1_fix_completed_snapshot.json`。全量三项warning分别为PyPDF2、Starlette/httpx、Pydantic弃用提示，未为消除warning修改依赖或旧用例。

真实纵向证据为`tmp/c1_audit/c1_fix_release_vertical_evidence.json`：Mission `mission_c1560d226dbb`、Run `run_215e488058fa`、GraphRevisionCommit `pcommit_05afa02d42f14164b9634acb6db54fd9`、GraphVersion=2、Permit `xpermit_1da47ae7ef69fd9cfb65bb252cdf767e05cc4871`。v1真实A完成，接受/物化/激活/Handoff/ISSUED后，spawn进程执行B并在Checkpoint提交、Run未确认时os._exit；新Runtime对账后只调用C/D，A/B收据与旧Checkpoint不变、canonical唯一，合法用户Workspace/正文200。没有预填完成态、Receipt、Artifact或Agent输出。

## 7. 保留边界

- 当前只证明同机、同一规范化Workflow SQLite、显式装配、受控Native Runtime、首次无控制DAG v1→v2；没有启用默认生产装配或首次initial_plan物化。
- 授权在每次HTTP请求中重验，不宣称已经进入流式响应后的数据可被原子撤回。跨库仍无联合CAS，第三方执行内部副作用不可由本地许可原子撤销。
- 样例预检是结构和版本检查，不是执行许可或可信恢复证明；复制源在并发变更时不是跨文件原子快照，后续原Authority必须重验，不能把预检结果当激活承诺。预检与正式打开之间不支持并发DDL或文件替换，不宣称对任意并发Schema修改仍能保证零写入。它复制本地DB/WAL，成本随文件大小增加，未做新大图/生产容量保证。
- 只支持已明确的Checkpoint确认窗口；receipt-only、未知副作用、控制/循环与任意崩溃切口保持原fail-closed，不清空Attempt或历史证据。
- 原始output新增只读缓存查询以检查Workflow删除及Frozen Basis；未调用完整get_status路径，既有轻量查询兼容测试通过；未做大Run冷缓存查询延迟基准。
- 不新建Artifact撤销状态或删除协议。缺失/未封存/归属错误内容与删除Run的直接引用已验证；sealed内容和canonical Binding继续由原权威保持不可变。
- 未做浏览器、真实供应商模型、远端Adapter或生产部署验证。规则合同审查不是法律完整性鉴定。

全部修复、永久测试和本报告保持未提交、未暂存；没有Push、Merge、部署、业务数据库升级或正式ADR修改。最终仅申请第二轮独立验收，不自行宣布ACCEPT。
