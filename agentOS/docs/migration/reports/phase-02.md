# Phase 2 — AgentOS 树断层替换

## Phase

Phase 2：以 wkn-master 完整替换 C4 AgentOS tracked tree。

## Baseline SHA

`559edc5497b5be901e053c4873887c9c2d3e7036`。

## Result SHA

`c81f8babc55e6518d6ae306187fcb5ccc77a6a1a`（`02 refactor(agentos): replace C4 kernel with wkn master`）。

## Changed

- 删除 C4 `agentOS/**` tracked tree。
- 从 `wkn-master@3f6c536` 恢复完整 `agentOS/**`。
- 唯一例外是保留 `agentOS/docs/migration/**` 审计材料。
- 未复制 C4 RuntimeGraph、Executor、`agentos.core` 或兼容包装器。

## Capability Impact

- `REPLACED`：wkn 的规划、执行、资源、恢复、工具、记忆、审计和血缘内核成为唯一实现。
- `MIGRATE`：矩阵列出的 C4-only 能力尚未补齐，保持显式缺口。
- `DROP`：C4 tracked `agentos.core` 与旧 AgentOS DTO/存储实现已从生产 tree 移除。

## Tests（命令与结果）

```powershell
git diff --name-only wkn-master -- agentOS
git ls-files 'agentOS/src/agentos/**'
```

结果：与 wkn tracked tree 的差异仅为 3 个迁移审计文档；tracked legacy `agentos` 文件数为 0。

## Known Gaps

- 工作目录中可能残留被 `.gitignore` 忽略的历史 `__pycache__`，不属于 tracked/生产 tree；Python 不会把缺少源文件的 `__pycache__` 当成可导入的旧包。交付清洁环境不会包含这些缓存。
- 根目录 pytest 的 cwd-sensitive 测试修复尚未进入本提交。
- Application、API、Spring、前端和 Docker 仍引用旧合同，符合断层切换阶段预期。

## Architecture Deviations

wkn tree 之外只保留迁移审计文档；这是计划要求的证据目录，不是内核偏差。

## Next Phase

Phase 3 前置基线修复：使根目录标准 pytest 命令稳定通过并显式加入 `agentOS/` import root。
