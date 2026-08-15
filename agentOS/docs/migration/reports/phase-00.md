# Phase 0 — 共同祖先能力审计

## Phase

Phase 0：共同祖先能力审计。

## Baseline SHA

`e4a582f453d4db8f1fd6268de8a485d7904a7254`（分支起点），共同祖先 `87e6ee39126a49d25fa1c90f2810ea1fb9606a3e`，目标内核 `3f6c5365c7ca4358613001ab6529657ba56d36cf`。

## Result SHA

`d17a7d081b15819628209cbda31c1e9488b3b7db`（`01 audit(migration): 冻结 ACG 迁移能力矩阵`）。

## Changed

- 从共同祖先分别审计 C4-mainline 和 wkn-master 的 AgentOS 演化。
- 建立覆盖 Planning、Execution、Binding、Recovery、Tool、Memory、Governance、Product 的 disposition matrix。
- 将动态图、GraphPatch、alternate binding、contract repair、联网工具和产品接线列为 `MIGRATE`。
- 明确旧数据库兼容和旧 RuntimeGraph DTO 为 `DROP`，Runtime Hardening 为 `DEFER`。

## Capability Impact

所有已识别的 C4 ACG 核心能力均已得到 `REPLACED`、`MIGRATE`、`DEFER` 或 `DROP` 结论；尚未迁移代码。

## Tests（命令与结果）

```powershell
git merge-base C4-mainline wkn-master
git log --oneline 87e6ee3..C4-mainline -- agentOS
git log --oneline 87e6ee3..wkn-master -- agentOS
git ls-tree -r --name-only <ref> agentOS agent backend frontend
git grep <capability-pattern> <ref> -- agentOS agent backend frontend
```

结果：三个锁定 SHA 与计划一致；矩阵中的代码、测试和提交证据均存在于对应锁定 tree。

## Known Gaps

所有 `MIGRATE` 项仍待实现；`REPLACED` 项仍待迁移分支上的回归证明。

## Architecture Deviations

无。审计采用真实路径；未把 README 中的逻辑目录当作物理目录。

## Next Phase

Phase 1：在独立 worktree 冻结 wkn 原生测试、导入边界、Runtime 构造依赖和存储变量。
