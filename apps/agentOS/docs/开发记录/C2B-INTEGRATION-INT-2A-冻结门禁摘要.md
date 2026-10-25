# INT-2A 冻结门禁摘要

冻结状态：**ACCEPT WITH LIMITATIONS**。本摘要归档已验收测试证据，不代表生产部署或真实数据库 READY。

## 已核验的源码基线

入场 Git HEAD：`ff06464edb68d77bac1e0df38dc772a140032f24`。最终修复由以下三个文件组成，与已验收 `final-source.patch` 的限定 diff 逐字节一致；补丁 SHA-256 为 `b99cdb865d552d54044926eecfbf0098ea5407515fb8948a3449879d13f62e09`。

| 文件 | 验收时原始字节 SHA-256 |
| --- | --- |
| `apps/agent/app/execution/wiring.py` | `f4bf4a611b5939a880bf7819b1665264ad3319d0b452f3ad2a1ef08e4b4f4d23` |
| `apps/agentOS/tests/storage/test_runtime_assembly_failure_cleanup.py` | `5170123fe8b9a14ac6c180b94e95b15ba2bdc994fa7ef88372aaf0f2075a7818` |
| `scripts/freeze_gate.py` | `af9ff6d92d4e85f723e749db091a71d01565baaea06ad569ef416c09b8657f69` |

AgentOS src/tests：454 个 Python 文件，聚合 `cb4a3124a214e8793f2ea018836ac1d963a5cf753946d6d0f9afbc4e9a42bc26`。

INT-1 manifest 未修改：`scripts/freeze_gate_baselines/c2b-int1-entry.json`，SHA-256 `54ccc02a3d0ba550fffff8dd23f259460977ae0a75f3d8eea4d7c1848ce1a591`。本轮 gate 变化仅为 wiring 固定摘要与修复任务注释，不改变映射、安全标记、排除规则或 300 秒预算。

## 测试证据

- P1-01 两个真实 Task.cancel 反例已由红转绿；永久模块覆盖正常关闭取消、启动失败取消、连续取消、普通关闭错误、锁释放失败及重复关闭/重新装配。定向回归 **101 passed**，退出 0。
- 曾有一次正式 300 节点运行超时：`20261025T080259Z`，`INCOMPLETE_TIMEOUT`，墙钟 300.657 秒，退出 1。该历史结果保留，不改写为通过。
- 最终正式门禁：`20261025T100534Z`，**PASSED，300 passed，墙钟 279.106 秒，门禁/pytest 退出码均为 0，未超时**；pytest 自身耗时 270.15 秒。
- 19 条选择路径、300 个唯一节点、manifest 300 行；collection/start/call 顺序逐项相等，900 个 setup/call/teardown 阶段全部通过。5 个新增永久回归均在正式门禁内通过。
- node manifest SHA-256：`840e5434fa6d228c99c7c84e5ad48468d6dab5af04db694e8d430efa5f45e709`。源码及外部快照运行前后未变化；uncovered/missing_test/missing_external 为空。

证据原始位置为 `tmp/freeze_gate/20261025T100534Z.{json,log,nodeids}` 与 `tmp/int2a2-gate-closeout/`。原始日志、执行账本、缓存、临时库和机器环境材料仅保留在本机，不纳入 Git；本摘要和阶段合并记录为仓库内的证据归档。

## 运行边界

正式命令为 `python scripts/freeze_gate.py`，300 秒硬预算不变。验收环境仅在离线测试子进程移除 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY（含大小写变体），保留真实 HTTPX 客户端和证书校验，通信库及其余 SQLite 全部使用临时路径。只读观察插件记录执行事件，不改变选择、断言或退出码。

性能对照为同样 8 项 **117.57 秒 → 62.06 秒**，均通过；主要已证实开销为代理导致重复 CA 装载。永久测试和生产实现均未为通过门禁而改写。历史缓存未清空、删除或替换；正常 max 更新后所选节点历史和为 287.600 秒，这不是实跑时间或未来预算保证。

冻结动作只重新核验源码、补丁、清单与既有测试证据，不重复执行 pytest 或门禁。完整报告归档于 [INT-2A-2 阶段合并记录](C2B-INTEGRATION-INT-2A-2-阶段合并记录.md)；保留限制及提交基线见 [INT-2A 冻结记录](C2B-INTEGRATION-INT-2A-FREEZE-阶段冻结记录.md)。
