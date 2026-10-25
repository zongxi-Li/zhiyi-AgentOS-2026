# INT-2A-FREEZE：阶段冻结记录

日期：2026-10-25（Asia/Shanghai）。状态：**ACCEPT WITH LIMITATIONS**。

## 冻结依据与范围

INT-2A 的生产 Authority 受限装配合同及 P1-01 取消清理修复已完成。最新独立源码验收结果由用户的 `INT-2A-FREEZE` 指令明确确认为 **ACCEPT WITH LIMITATIONS**；本轮仅核验和固化既有结果，不新增功能实现或另行声称完成生产验收。

保留历史证据链：初次独立验收 REJECT → P1-01 修复与永久回归 → 原门禁超时 → 性能诊断与最终门禁 PASSED → 用户确认独立源码验收 ACCEPT WITH LIMITATIONS。历史 REJECT 和超时记录没有被覆盖为通过。

## Git 基线与提交分类

| 分类 | Commit |
| --- | --- |
| 入场基线 | `ff06464edb68d77bac1e0df38dc772a140032f24` |
| Runtime 修复与永久回归 | `1f32483822b50d5704d0903d43382c1f156d3571` |
| 门禁固定摘要与正式证据摘要 | `72ba25571e8d2e22ee1994642bc521c37f2e26f9` |
| 阶段报告归档及冻结记录 | 包含本记录的归档提交；提交完成后的 HEAD 即本次最终冻结 Commit |

归档提交的完整 SHA 可用 `git log -1 --format=%H -- apps/agentOS/docs/开发记录/C2B-INTEGRATION-INT-2A-FREEZE-阶段冻结记录.md` 解析；最终交付回复另行列出其完整值，避免在提交内容中嵌入自身 SHA 的循环引用。

三个修复文件的限定 diff 与已验收 `final-source.patch` 逐字节一致；补丁 SHA-256 为 `b99cdb865d552d54044926eecfbf0098ea5407515fb8948a3449879d13f62e09`。本轮功能源码没有改动。

| 修复文件 | 已验收原始字节 SHA-256 |
| --- | --- |
| `apps/agent/app/execution/wiring.py` | `f4bf4a611b5939a880bf7819b1665264ad3319d0b452f3ad2a1ef08e4b4f4d23` |
| `apps/agentOS/tests/storage/test_runtime_assembly_failure_cleanup.py` | `5170123fe8b9a14ac6c180b94e95b15ba2bdc994fa7ef88372aaf0f2075a7818` |
| `scripts/freeze_gate.py` | `af9ff6d92d4e85f723e749db091a71d01565baaea06ad569ef416c09b8657f69` |

INT-1 manifest、Schema、HTTP、前端、compose、生产开关和真实业务数据库均未修改。未创建冻结 tag，未推送或部署。

## 测试证据与适用环境

- P1-01 两个真实取消反例由红转绿；定向回归 **101 passed，退出 0**。
- 正式门禁 `20261025T100534Z`：**PASSED，300 passed，墙钟 279.106 秒，硬预算 300 秒，门禁/pytest 退出均为 0**；pytest 自身 270.15 秒，未超时。
- 19 条路径、300 个唯一节点与 manifest 一致；逐节点 collection/start/call 顺序相等，900 个 setup/call/teardown 阶段通过，5 个新增永久回归均在正式门禁中通过。
- AgentOS src/tests 共 454 文件，聚合 `cb4a3124a214e8793f2ea018836ac1d963a5cf753946d6d0f9afbc4e9a42bc26`；运行前后源码及外部快照不变。冻结时重新核对相同源码与证据，不重复执行测试或门禁。
- 门禁使用明确隔离代理的离线测试子进程、真实 HTTPX 客户端和证书校验、临时 SQLite。只读观察插件仅记录节点事件，不改变选择或断言。该环境不代表生产网络或任意机器条件下的时间保证。
- 历史缓存完整保留，仅由门禁正常 max 更新；原实际超时及更早的缓存预算误阻断仍作为历史证据保留。未通过清空缓存、增加预算或删减安全测试取得本次通过。

完整节点摘要、源码摘要与运行边界见 [冻结门禁摘要](C2B-INTEGRATION-INT-2A-冻结门禁摘要.md)。

## 正式报告归档

文档目录在冻结期间另有阶段整理，三份原报告已合并移除。本轮未恢复已删除原件，使用现有 [INT-2A-2 阶段合并记录](C2B-INTEGRATION-INT-2A-2-阶段合并记录.md) 归档，并仅修正其来源说明。以下三个正文段落经提取、按原 LF 文本还原后，SHA-256 与原报告完全一致：

| 原报告来源标识 | 归档正文 SHA-256 |
| --- | --- |
| `C2B-INTEGRATION-INT-2A-2-生产装配最终独立验收.md` | `b45bd176325b41aff46419f8d029d0598f826ccfb9c43b491dd868280051a014` |
| `C2B-INTEGRATION-INT-2A-2-FIX-异步取消清理修复记录.md` | `1e9e9681e4843a16b26e46a045e7aedd234b84ac0895acf1d9cd6b078fb2a109` |
| `C2B-INTEGRATION-INT-2A-2-GATE-CLOSEOUT-最终冻结门禁收束.md` | `6bbd1c7d77ad001066a594d03aed1829db50e4958826e5c85216c8156d8f78e5` |

本轮只归档 INT-2A-2 相关合并记录，不纳入其他阶段的合并文件或删除操作。tmp 诊断缓存、临时数据库、原始测试日志、执行账本和机器环境文件均不提交；仓库内保留摘要、来源与校验值。

## 保留的 P2 / P3 与生产限制

1. 历史耗时按每节点最大值累计可能误阻断；本次更新后所选历史和为 287.600 秒，不是实跑时间，也不能保证未来预检或运行一定在预算内。
2. 生产 `app/execution/coordinator.py` 尚未纳入门禁外部源码快照与差异映射；当前人工验收不能替代未来变更的自动保护。
3. CA 证书装载时间波动，以及两个既有生产装配慢测试的剩余耗时原因尚未完全确认；留作观测事项，不扩展本次 Runtime 修复。历史报告的测试数、耗时和摘要应按各自时间点理解。
4. 被取消的异步客户端可能未完成关闭；Runtime 明确记录、保留 owned 引用并传播取消，需要显式重试关闭，不宣称所有中断客户端都已成功回收。
5. Workflow、Checkpoint、Identity 之间不存在跨数据库联合原子事务；恢复依赖既有 saga 和原幂等键，不能宣称三库原子性。
6. 本地撤权不能自动撤销远端已开始的副作用；多主机执行一致性尚未验收。
7. 真实生产 Schema 升级、业务数据库 READY、维护窗口与部署开关尚未确认或获本次授权。临时库测试与受限源码验收不能代替这些条件。

## 收尾核对与停止点

每笔提交按明确路径暂存并核对暂存清单、`git diff --cached --check` 和提交范围；收尾核对 `git diff --check`、最终 Commit、索引和工作区。其他阶段的文档整理留在工作区，不把“本次提交范围干净”表述为“整个工作区干净”。

冻结完成即停止。INT-2B 需要新的任务和授权，不自动实施。
