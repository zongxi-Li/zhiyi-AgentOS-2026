# 工程卫生第四至六阶段实施记录（2026-11-21）

范围：依赖与配置统一、仓库瘦身、CI 与回归收尾。延续前三阶段提交 `ba2799ba`，保留 `backend` 名称与现有执行架构。本记录不修改原始只读审查报告。

## 第四阶段：依赖与配置

- 六个第一方 npm 工程统一 Node `>=24.9.0 <25`，根 `.node-version` 固定本次验收版本 `24.22.1`；TypeScript 统一为 `5.9.3`。保留各工程现有测试框架主版本。
- npm 保留各工程 `package-lock.json`；删除没有 package.json 的旧桌面锁与 Hands 重复的 pnpm 锁。
- 应用依赖统一为 `apps/agent/requirements.in` → `requirements.lock`，合并原工具层依赖并删除两个叠加工具锁及维护脚本。新增受运行锁约束的 `requirements.dev.in` / `.lock`，包含 pytest、asyncio、cov、xdist。
- Python 3.14.10 / Windows x64 新建隔离环境，运行与开发锁完整哈希安装、`pip check` 通过。此锁不代表 Linux、CUDA 或 Safe 历史 Python 3.10 环境已经验收。
- 端口与流默认值以 `apps/backend/src/shared/runtime-defaults.json` 为唯一共享来源，Backend、前端与 Python 启动配置读取；便携发行包验证 Backend dist 中的同一合同。保留已有 `ZHIYI_BACKEND_TS_*` 环境变量兼容接口。
- `apps/agentOS/requirements.txt` 明确为独立 Safe / 本地工具历史实验平台锁，不能作为全应用安装入口。

## 第五阶段：仓库瘦身

- `papers/ARTIFACTS.csv` 记录 512 个退出跟踪文件的路径、清理时本地字节数与原 Git blob，总计 530,065,138 字节。研究笔记、索引、Python / JS / CJS 脚本和可编辑源图保留。
- `.build`、PDF、提取全文、页面快照与生成导出退出 Git 索引，本任务工作区原件保留；主工作区合并后按清单恢复为 ignored 本地文件。新克隆可按 `papers/README.md` 从 `ba2799ba` 导出历史原件。
- 此操作只缩小当前跟踪树，不重写历史，也不使既有 `.git` 历史对象自动变小。
- 仓库外归档：`E:/Project/Kinlin_AI-archive/2026-11-21-hygiene`。其中完整保留研究目录、10 个旧 worktree / 孤儿目录、旧 worktree 元数据与 HEAD 清单、旧临时目录和恢复说明。512 个清单路径的归档与主工作区原件已逐文件核对 SHA-256 一致。
- 当前仅保留主工作区与本任务工作区的 Git 注册。运行 `data/`、数据库和凭据未移动。

## 第六阶段：CI 与测试迁移

- 新 `application-ci.yml` 覆盖 Python 内核 / 应用 / 原生脚本、Frontend Web 与 Electron 构建及 Vitest、Electron / Terminal / Hands / Compact 的类型检查与测试。Python job 安装运行与开发 hash lock，以及 Hands / Compact npm 锁依赖。
- Backend 既有 CI 继续执行 PostgreSQL 集成测试；两个工作流读取根 Node / Python 版本文件。不排除失败套件，不使用 `continue-on-error`；前端重试设为 0，并限制并行 worker。
- 仓库卫生脚本校验活动路径、包与锁一致性、Python pins / hashes、运行版本和研究产物回流；新增负向测试。
- 已删除示例的离线回归夹具迁入 `TEST/fixtures`，保留其测试用途；修复跨测试导入、合同 JSON 夹具、事件发布器注入与现行计划合同预期。
- 并发测试使用真实 Agent 容量，验证宿主与 Agent 实例两份租约均在 runner 结束后释放。C2 就绪夹具使用具体注册的 Agent，不再制造无执行实例的虚假本地宿主；异步 fixture 使用异步资源关闭。
- schema 准备工具接受官方历史 ADD COLUMN 布局及其精确对应触发器；篡改触发器仍拒绝，负向测试验证无数据库写入。
- 旧联邦模型演示不再导入已删除的加密 singleton。数字聚合逻辑保留，参数解码须显式注入；默认未配置时返回 503，模型、待处理更新和历史保持原样。旧算法测试改为现行解码边界和失败无副作用测试，未恢复旧加密 / 旧 DP。

## 本地验证

平台：Windows x64，Python 3.14.10，Node 24.22.1。下表为实际完整命令的结果，未以定向测试替代全量计数。

| 项目 | 结果 |
| --- | --- |
| Python 内核 `TEST/tests` | 4053 passed，1 skipped |
| Python 应用 `apps/agent/tests` | 775 passed，5 skipped |
| 原生基础设施与卫生测试 | 97 passed |
| Backend 类型检查 / 构建 / 测试 | 137 passed |
| Frontend Vitest | 1769 passed，0 failed，retry=0 |
| Frontend Web / Electron 构建 | 均通过 |
| Electron 类型检查 / 测试 | 60 passed |
| Terminal | 4 passed |
| Hands 类型检查 / 测试 | 102 passed |
| Compact 类型检查 / 测试 | 51 passed |
| 依赖安装与 `pip check` | 通过 |
| 仓库卫生与 diff 空白检查 | 通过 |
| 语义验收脚本 `verify_mission_semantics.py api` | 58 passed |
| master 合并后基础设施 / 人工审批 / 解码边界回归 | 112 passed |

Python 回归命令均从仓库根运行：

```powershell
python -m pytest --rootdir=. -c apps/agentOS/pytest.ini TEST/tests -n 4 --dist loadscope -q
python -m pytest --rootdir=. -c apps/agentOS/pytest.ini apps/agent/tests -n 4 --dist loadscope -q
python -m pytest --rootdir=. -c apps/agentOS/pytest.ini ops/scripts/infra/tests -q
python ops/scripts/infra/check_repository_hygiene.py
```

本地测试与构建不等于 GitHub 托管 runner、完整便携安装包或真实外部模型端到端验收；这些未在本次宣称通过。原始测试日志保存在本任务 ignored `.tmp-logs` 与前端 `.tmp-logs`，不将运行产物加入仓库。

## 合并与本地文件保护

已分主题提交，并在主工作区将 `codex/cleanup-docs-ui` 正常快进合并到本地 `master`，包含此前三个阶段的 `ba2799ba`：

- `0423f158`：运行 / 开发锁与 backend 共享配置。
- `b1d63051`：研究产物退出跟踪与源文件保留。
- `f47bc1dd`：CI 扩容、测试迁移和回归修复。

合并后从主工作区运行基础设施、人工审批和解码边界测试，112 项通过；卫生与空白门禁通过。用户 README 的三行空白调整与预期合并文本一致，原审查报告 SHA-256 和原始换行字节保持一致。512 个研究文件从归档恢复后逐文件 SHA-256 核对一致，全部为 ignored 文件，均未重新进入跟踪。

本轮完成记录另作文档提交。保留任务分支和当前工作区，不推送远程，不重写历史。
