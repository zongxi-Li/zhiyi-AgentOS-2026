# INT-2B 受限验收冻结记录

2026-10-25，独立源码验收结论为 `ACCEPT WITH LIMITATIONS`。

入场本地 HEAD 与 GitHub master 均为 `28623c1b634b33d9edb289a7b641294db296cf00`，暂存区、工作区和未跟踪文件为空。当前分支 master 包含：

- `b0ea6c88c80754588a98679f6fc813646d3b4b4a`：Initial HTTP 闭环。
- `ab6adb4042f4dd26a3358f8b254dc0c53893aa1f`：Handoff / Permit HTTP 与状态投影。
- `01a9ac574fce7b3aeb49b63972ba9a63ab417977`：INT-2B-2 审计归档。
- `28623c1b634b33d9edb289a7b641294db296cf00`：用户文档删除，保持现状，不恢复。

已核对生产实现：Handoff 与 Permit 写入复用原 Authority；`permitIssued` 表示历史许可，`dispatchEligible` 复用正式派发门禁；两个 HTTP 控制入口不调用 Coordinator 或隐式启动 Scheduler。Coordinator 原 `submit()` 仍只接受未开始 pending 或明确 retrying，不适用于已许可 planning Run。

继承的已完成验证证据见 `PR-C2B-INT-2B-2.md`：API **102 passed in 103.67s**、核心 **145 passed in 495.23s**，退出码均为 0，前后源码 SHA256 一致。这是上一阶段的实测证据，不冒充本阶段新鲜回归；INT-2C 将单独记录新鲜测试。

保留的限制：尚无正式 HTTP Dispatch 命令；许可签发与明确执行命令分离；不得自动执行未 Dispatch 的 Run；未知外部副作用不能自动重放；跨数据库恢复不提供任意远端 exactly-once 保证。后续 INT-2C 必须保留现有 Native Scheduler、Permit 和 Recovery 权威。

本次冻结只提交本记录，不修改已验收生产实现、Schema、前端或生产配置。
