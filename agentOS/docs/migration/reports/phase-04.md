# Phase 4 — Legal Contract Review 黄金纵切

## Phase

Phase 4：在唯一 wkn `WorkflowRuntime` 上恢复 Legal Contract Review 的真实非线性执行链。

## Baseline SHA

`2675c5f46fbbaac39607d4a180a7256b4a02392f`

## Result SHA

`9e0a22d7eaff05361ac8f4fa8c7594bc5d69487d`

## Changed

- 为 Legal Pack 增加 `build_contract_review_blueprint`，以 wkn `ACGBlueprint` 表达解析、并行条款分析/工具检索、风险、证据、建议、条件审核与报告链。
- 完整声明 Legal 节点输出 JSON Schema，避免 wkn 合同投影丢弃下游所需字段。
- Legal Agent 改从 `ContextPack.data` 读取白名单字段；业务风险与执行治理风险分离。
- 修复 Blueprint 显式审核节点的记忆隔离：批准前只保留 `outputRef` 和待写意图，批准后再解引用写入。
- 修复 SQLite 持久运行在审核批准后遗留 `WAITING_REVIEW` step 的状态冲突。
- 审核 Trace 保留 reviewer/comment 元数据，供最终报告和后续授权投影使用。
- Application shutdown 同时关闭 `WorkflowStore`，确保同一路径 Runtime 可在进程重建测试中安全重新打开。

## Capability Impact

- `MIGRATED`：Legal Contract Review 产品纵切、应用 Runtime wiring。
- `REPLACED`：wkn 并行 superstep、条件路由/skip、stable commit、checkpoint CAS、引用式 State、持久 Review/Memory/Provenance。
- `MIGRATE`：通用动态图、GraphPatch、alternate binding、contract repair、联网生产 provider 仍进入 Phase 5。

## Tests（命令与结果）

```powershell
python -m pytest agentOS/tests agent/tests/test_wkn_application_wiring.py agent/tests/test_legal_wkn_vertical_slice.py -q
```

结果：`139 passed, 3 warnings in 6.97s`。随后将 Legal 本地检索移入 worker thread，消除事件循环内调用同步 RAG 的未等待协程告警；最终结果将在提交前复跑记录。

黄金测试验证了：

- `WAITING_REVIEW → Runtime 重建 → approve → completed`；
- 重启前后 `commit:runId:human_review:0` 记录完全一致；
- 已提交 Agent 不重跑，恢复后只调用 `report_generate`；
- 重复启动等待审核 run 不新增 checkpoint 版本；
- State/checkpoint 不含固定合同正文标记；
- 审核前无 `human_review` 正式记忆，批准后只写一次；
- 并行批次同时调度 `classify_clauses` 和 `statute_retrieve`；
- 高风险分支命中人工审核，`auto_review` 被标记 skipped；
- 工具事件、Trace 与 Provenance 在重启恢复后不重复。

## Known Gaps

- C4 旧 `test_legal_contract_review_acg.py` 仍断言 `run.output.artifacts`、`RuntimeGraph` 和动态图 DTO；这些测试将在 Phase 5/7 按能力重新编写，不通过兼容层恢复。
- 当前黄金测试使用注入的确定性模型与只读工具 fixture；真实联网 provider 的授权、离线降级和引用完整性属于 Phase 5。
- 通用 workflow promoter 仍按线性模板升级；Legal 的非线性业务图由 Pack builder 显式提供，后续 API 只负责传递 Blueprint，不复制调度逻辑。

## Architecture Deviations

计划把 Legal 描述为一个静态 workflow，但 wkn 的 `WorkflowDefinition` 不保存 C4 `conditionalRoutes` 扩展字段。真实落点因此是 Legal Pack 内的 ACG Blueprint builder；条件求值、并行调度、skip、checkpoint 和恢复仍全部由 wkn components/runtime 执行。

## Next Phase

Phase 5：只处理矩阵中的 `MIGRATE` 能力，优先建立通用 graph revision/GraphPatch、恢复 recipe、alternate binding、contract repair 与联网工具回归。
