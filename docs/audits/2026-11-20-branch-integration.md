# 2026-11-20 分支整合记录

## 整合范围

以 `master@2c6d8547` 的 AgentOS 分层架构为基础，合入以下实现：

| 来源 | 源提交 | 内容 |
| --- | --- | --- |
| `feat/companion-experience-20261115` | `52687ba2` | 桌面伙伴对话、语音、运行事件、外观与位置状态；包含原工作区未提交的有效实现 |
| `feat/evolution-safe-layers-20261118` | `5ce5e823` | 演化层实现、回归测试及该分支已有文档和调研资料 |
| `dev-lzx-20261122` | `640425be` | 核心运行、规划与恢复、工具审批、图历史及对应界面 |

整合提交 `d2b982d5` 保留 master 的模块边界，将运行实现迁入对应的 adapters、runtime/orchestration、runtime/projections 和 support 模块；保留显式组合根、兼容门面和事件发布注入。整合提交 `bfca22f0` 接入伙伴实现，同时保留运行状态核对和伙伴事件桥。

额外修复两处整合兼容问题：图规模测试改用 `TEST.tests` 包导入；长结论展示使用 Markdown 空行分段，兼容新的软换行解析规则。

## 验证

以下为独立测试执行结果，各组存在覆盖重叠，不应直接相加：

- 架构及演化检查：103 通过。
- 模型及工具适配器：629 + 37 通过，覆盖全部 adapters 测试文件。
- 新增非适配器核心测试：514 通过，含大图物化、图交接、证据、恢复、资源隔离及存储。
- Agent API 与运行恢复专项：99 通过。
- 后端完整测试：指定项目 Python 后，137 项全部通过，后端构建亦通过。
- 桌面伙伴 IPC、托盘与权限测试：16 通过。
- Markdown 与长结论展示回归：26 通过。
- 前端完整测试：1,762 通过、9 失败；失败用例对应下述原分支问题。Vue TypeScript 检查及 Vite 生产构建通过。完整报告为本地备份目录的 `final-frontend-tests.json`，构建日志为 `final-frontend-build.log`。

已知问题：前端原 master 上的 App 历史面板、WorkspaceContinuity、GlassConstellation、MissionEditor 用例存在失败；两个生命周期集成用例在 `dev-lzx-20261122` 独立快照上同样失败，涉及缺失能力快照后的历史状态展示及历史 Copilot 对话。此次未降低能力校验以规避这些失败。

历史 Python 全套测试还存在缺失 `examples.contract_review`、`contracts/agentos-v2` 夹具和可选运行环境问题；上下文预算旧断言在整合前 master 上亦可复现。以上限制意味着本记录不宣称仓库全套测试通过。

## 清理与恢复

按用户选择关闭本地及两端远程的 `C4`、`refactor/agentos-architecture-20261115`、`feat/safe-unified-env-20261116`、`integrate/all-committed-20261116`；远程原本不存在的名称无需删除。关闭过时的 `C4-mainline`。保留三个实现来源分支。

原工作区及其忽略数据保留；已关闭分支对应的工作区使用 detached HEAD。伙伴工作区的自动生成声明、截图和临时 QA 页面保留在原处，不作为有效实现提交。

本机恢复材料位于 `.git/integration-backups/20261120/`：

- `before-integration.bundle`：已验证的完整 Git 历史和原分支引用。
- `companion-working.patch`、`companion-untracked/`：原伙伴未提交改动及未跟踪文件副本。
- 模块迁移映射、冲突处理脚本、测试日志和原第 7 分支快照压缩包。

目标为将整合结果快进至本地 master，并同步 Gitee、GitHub 的 master；以最终远程引用核对结果为准。
