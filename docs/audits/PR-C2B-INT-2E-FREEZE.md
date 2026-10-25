# INT-2E 入场冻结：INT-2C / INT-2D

日期：2026-10-25。裁决：**ACCEPT WITH LIMITATIONS**，仅冻结已归档的受限成果，不代表 V1 全链或生产验收。

入场本地 HEAD、GitHub master 均为 `cfe67a1e69711abf00deede0d53ed14dbfaa7928`；工作区、暂存区和未跟踪文件为空。核实 `cc35fa291990148825116935594cd793c2eac4c8` Native 修复和 `00a96678853f4c422964a6da48ed15df032956e2` Workbench 接线在当前历史中。未恢复用户已删除的文档。

本轮源码审阅确认 `_claim_acg_execution` 在正式 Run lock / OS fence 内验证原 Permit 和持久 Dispatch；原 Store 完整性、来源和可信主体检查仍在。永久反例保留：Permit-only 直接执行、Checkpoint / Review 首次派发绕过、损坏 / 错误 Command、关闭模式兼容。Workbench 仍逐步调用正式控制，Permit 不自动 Dispatch，稳定 operationId 与版本重试、原审核 / 取消 / Artifact 组件保留。

继承证据（本次独立入场审查**没有重新执行全部测试**）：

| 阶段 | 已归档证据 | 来源 |
| --- | --- | --- |
| INT-2C Closeout | API 133、核心恢复 165、门禁完整性 / 装配 109，退出码均 0；真实红态三个节点执行，修复后拒绝 | `PR-C2B-INT-2C-CLOSEOUT.md` |
| INT-2D | HTTP 59、Vue 150、Java 34，退出码均 0 | `PR-C2B-INT-2D.md` |
| 构建 | Web / desktop 含 vue-tsc，通过；Windows 并发写声明失败后关闭预览串行通过 | 同上 |
| 浏览器 | 原 Workbench + 测试身份桥 + 真实 Runtime / 临时 SQLite；Permit 零执行、双击单 Dispatch、ABC 各一次、supporting Artifact 打开 / 下载及刷新 | 同上 |

已知限制必须保留：此前浏览器不是正常 IAM 登录链，未跑真实 Provider，测试桥不转发 SSE；示例只有 supporting_artifact，没有 canonical run_deliverable。单实例、显式 Schema 升级、跨库非原子、未知远端副作用阻断仍适用。历史 SELF-TESTED 不作为本次真实全栈验收通过的依据。

本提交仅新增冻结记录，不修改已验收控制链或其基线。后续证据和最终三层裁决独立归档于 `PR-C2B-INT-2E-V1-FINAL.md`；未获生产部署授权。
