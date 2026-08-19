# 知弈 AgentOS 三线收束正式集成报告

报告分支：`integration/wkn-c4-milan-stable`
基线核验日期：2026-08-19（Asia/Shanghai）

## 1. 最终 integration HEAD

- 分支：`integration/wkn-c4-milan-stable`
- current master 起点：`e42f7b2313145b8cfcb1bbc910ab00c831885229`
- 迁移代码基线（Phase 10 后）：`b7c9a41`
- 最终收口提交：包含本报告、单 Runtime 清理和最终回归基线的 `test(agentos): establish integrated stable regression baseline`
- 精确最终 SHA 由交付时的 `git rev-parse HEAD` 给出。Git commit 无法在自身受哈希保护的内容中嵌入自己的最终 SHA。

远端核验结果与任务中给出的已知 SHA 完全一致：

- `github/master`：`e42f7b2313145b8cfcb1bbc910ab00c831885229`
- `github/migration/c4-to-wkn-acg`：`c66a3e3e7b02d022b5f7202dc888d6ea76eb938d`
- `github/C4-mainline`：`e4a582f453d4db8f1fd6268de8a485d7904a7254`
- 三线共同祖先：`87e6ee39126a49d25fa1c90f2810ea1fb9606a3e`

## 2. Git ancestry

集成分支由最新 `github/master` 直接创建，而不是由 migration 创建。最终收口前的硬证据：

```text
git merge-base github/master HEAD
e42f7b2313145b8cfcb1bbc910ab00c831885229

git rev-parse github/master
e42f7b2313145b8cfcb1bbc910ab00c831885229

git rev-list --left-right --count github/master...HEAD
0  8
```

最终报告提交只会使右侧提交数增加 1，不改变 merge-base。逻辑阶段提交为：

1. `ebedb79 refactor(agent): 迁移应用运行时装配`
2. `1656549 feat(agentos): 恢复 Legal 合同审查黄金纵切`
3. `6f38c6c feat(agentos): 迁移 C4 ACG 能力缺口`
4. `185edd1 refactor(packs): 迁移其余领域 Pack`
5. `7020f3a feat(api): 建立 AgentOS 应用 API`
6. `dbb7ffb refactor(backend): 迁移 Spring AgentOS 网关`
7. `028b535 feat(frontend): adapt Milan workbench to WKN v2`
8. `b7c9a41 refactor(docker): 采用 wkn 运行时与存储布局`
9. 最终回归与架构清理提交

未合并 master，未修改或删除 `C4-mainline` / `migration/c4-to-wkn-acg`，未 force-push，未推送集成分支。

## 3. 从 migration 实际迁入的能力

- WKN 增量：`GraphPatch` / `GraphPatchResult` / patch reference、不可变 `GraphPatchService`、版本 CAS、安全 review barrier patch、pending step alternate rebind、contract repair、Recovery Recipe registry、Evidence Memory。
- current runtime 语义适配：GraphPatch 纳入 current `WorkflowRuntime`，保留 guarded model/tool runtime、Communication Broker、binding freeze、checkpoint CAS、reference ownership、Trace/Provenance；GraphPatch reference 受到 orphan cleaner 保护。
- Application composition：恢复 `agent/app/execution` wiring、coordinator、tool calls、Pack 注册和六 Store 注入；composition root 只构造 current `WorkflowRuntime`。
- Golden vertical slice：Legal 合同审查 WKN 全链路。
- Domain Packs：Legal、Programmer、Education、Writer、General/Native；命名空间统一为 `app.*` 与 `packs.*`，不再调用 `agentos.core`。
- Python AgentOS v2：Run、Graph、Output、Trace、Provenance、Checkpoint、Review，保持 reference-first；Output 通过 `outputRef` 解引用。
- Spring Gateway：公共 `/api/agentos/v2` 映射到 Python `/ai/agentos/v2`，保留 security scope、DTO 边界和 upstream error mapping。
- Milan：ACG Workbench、Chat/Console、Run history、Graph、Trace、Provenance、Checkpoint、Review、Output、progress projection、artifact 解引用、task sidebar、review interaction、结果展示，以及 privacy/web-search 合同。
- Docker/运行布局：完整装入 `agent/`、`agentOS/` 与 `agentOS/service/`，统一 `PYTHONPATH`，六 Store 显式持久化；新增非敏感 `.env.windows.example`。
- 运行兼容与本地能力：历史 `run_degraded` 仅作为审计事件只读兼容；补齐只读、本地、有限文件大小且跳过依赖目录的代码关键字索引器，不执行工作区代码。

## 4. 未迁入的 migration 内容

- donor 中较旧的 WKN runtime/adapters/communicator 整体版本：current master 已有更新的 Broker、guards、binding/failover、health/version/key/streaming，实现更完整，因此没有目录覆盖。
- migration 的早期 WKN baseline/hotfix commits：目标问题已由 current master 后续实现覆盖，迁入会倒退。
- C4 `RuntimeGraph`、可变 WorkflowStep 真源、旧 ACGExecutor、旧动态绑定 DTO、planning fake projection：属于禁止恢复的 legacy 架构。
- `/core`、`/core/workflows`、`/core/plugins`、`/core/materials` 与 TaskMaterial API：与单一 AgentOS v2 边界冲突。
- arbitrary checkpoint resume、old run delete、把 input/output/ContextPack/内部状态塞回 Run DTO：违反 reference-first 与恢复安全边界。
- migration Phase 11 文档提交：固定了旧 WKN SHA、旧测试数字，并把 current master 已具备的 guards、commitId、orphan GC 错列为未来工作；不适合作为本分支事实来源。
- donor 提议的新 volume `agentos_wkn_data_v1`：未采用。集成分支从 current WKN master 出生，改名会让现有安装挂载空卷；保留 `agentos_data_v11` 才能维持数据连续性。
- C4-only 的 7 个前端文件：`DynamicRunSummaryCard`、`RuntimeChangeTimeline`、`runtimePresentation` 各自实现/测试，以及旧 `AcgVisualizationView.spec.ts`。前三组依赖旧 runtime/fake projection；最后一项是旧合同测试，不是缺失的页面或视觉能力。

## 5. current master 最新能力的保留情况

以下能力均以 current master 文件为真源并完成组合回归，没有被 donor 旧实现覆盖：

- Communication Broker 与 topology/field/entropy enforcement；显式 `COMMUNICATION` edge 也进入 channel manifest，parallel superstep 可取得通信生产者。
- model/tool runtime guards、错误净化和 retry；重试保持同一 `commitId`。
- AgentProfile model binding、冻结执行 binding 与受作用域约束的 alternate rebind。
- primary/backup model failover；Gateway/OpenAI 路径继续透传 `commitId` 为 `Idempotency-Key`。
- asynchronous health refresh、model version negotiation、key rotation。
- current streaming runtime foundation 与 current adapters。
- checkpoint CAS、conditional routing、skip state、Execution Value/Memory/Provenance/Decision stores、reference ownership 与 orphan cleanup。

相关测试仍位于并通过：`test_broker.py`、`test_runtime_guards.py`、`test_model_binding.py`、`test_guarded_runtime.py`、`test_model_runtime.py`、`test_model_audit_metadata.py`、`test_graph_patch.py`、`test_orphan_cleaner.py`、`test_acg_checkpoint_store.py`。

## 6. Milan 前端完整度

- 对 migration 最终态：当前 `frontend/src` 的 `.vue` / `.ts` 文件为 185 个；migration 同为 185 个，文件集合缺失 0、额外 0。migration 是完整产品层 donor，已全部落入集成分支。
- 对 C4-mainline：C4 为 191 个。C4-only 的 7 个文件已逐项审查，均是旧 RuntimeGraph/动态投影表达或旧合同测试，不是产品外壳缺口，因此未搬回。
- 当前 UI 保留 Milan 的 Workbench、Chat、Console、侧栏、历史、图、审计、恢复与结果呈现，但运行数据只使用 AgentOS v2 reference-first DTO。
- 前端完整单测为 24 files / 115 tests，通过；production build 成功，处理 3134 modules。

结论：与 migration 的 Milan 产品层完整一致；相对 C4 的差异是有意删除旧运行时语义，并非视觉退化。

## 7. API 最终形态

真实链路只有一条：

```text
Milan frontend
  -> Spring Security /api/agentos/v2
  -> Python FastAPI /ai/agentos/v2
  -> Application coordinator
  -> current WKN WorkflowRuntime
```

v2 暴露 Run create/list/detail、Graph、Output dereference、Trace、Provenance、Checkpoint list、Review list/decision。Spring 对外维持单一公共 v2 API；Python Run DTO 不内嵌 output body、ContextPack、模型内部状态或 RuntimeGraph。

真实认证 smoke 已验证：未认证 `GET /api/agentos/v2/runs` 返回 401；使用本地短时签名、未输出的五分钟 JWT 经 `frontend -> Spring -> Python` 返回 200，响应 `page=1`、`pageSize=20`、`total=0`。

## 8. Runtime 最终结构

- 生产源码扫描到且只扫描到 1 个 `class WorkflowRuntime`：`agentOS/src/runtime/workflow_runtime.py`。
- Application wiring 直接构造该 runtime，没有复制 current runtime，也没有第二 composition root。
- `ACGNodeRunner` 是唯一节点执行路径；不存在可执行的旧 `ACGExecutor` / 第二 Executor。
- 删除了 task-manager 中 677 行重复模型实现，progress projection 统一由 `scheduler.py` 的单一实现提供。
- 删除 WorkflowRun 的 `runtimeGraph` 字段和由其生成的旧统计；旧持久化 payload 中该未知字段由合同边界安全忽略，不重新成为状态真源。
- GraphPatch 修改 ACG blueprint/version/reference，WorkflowStep 仅是执行状态；执行真源仍为 current WKN runtime。

## 9. Persistence

生产容器内六类 SQLite Store 明确分离：

| Store | 实际路径 |
|---|---|
| Workflow Store | `/app/data/agentos/workflows.sqlite3` |
| Checkpoint Store | `/app/data/agentos/langgraph_checkpoints.sqlite3` |
| Execution Value Store | `/app/data/agentos/execution_values.sqlite3` |
| Evidence Memory Store | `/app/data/agentos/execution_memory.sqlite3` |
| Provenance Store | `/app/data/agentos/provenance.sqlite3` |
| Decision/Audit Store | `/app/data/agentos/audit_decisions.sqlite3` |

实际 volume 身份保持 `${KINLIN_DEPLOYMENT_ID}_agentos_data_v11`。本轮没有删除、迁移或清空用户数据。当前运行容器内已确认六文件全部存在。

backup manifest 格式为 1.2，内核标识 `wkn-master-e42f7b2`；restore 拒绝格式不匹配的旧备份。checkpoint reopen/latest/CAS/idempotent、execution reference ownership、review/recovery 均有自动化覆盖。

## 10. 测试矩阵

以下均为本 integration 分支上的真实执行结果：

| 层 | 命令/范围 | 结果 |
|---|---|---|
| current master 基线 Kernel | `py -3.14 -m pytest tests -q`（迁移前） | 177 passed |
| 最终 AgentOS Kernel | `py -3.14 -m pytest tests -q` | **187 passed**，4.40s |
| Python Application / Packs / v2 API | `py -3.14 -m pytest tests -q` | **102 passed, 1 skipped**，46.85s |
| Spring Gateway | `mvn -q test` | **132 tests**，0 failures/errors/skips，35 suites |
| Frontend unit | Vitest 全量 | **24 files, 115 tests passed** |
| Frontend production build | Vite production build | **成功**，3134 modules |
| infra/release | pytest 两套脚本测试 | **49 passed** |
| Docker dev compose | Windows dev 组合 `config --quiet` | 通过 |
| Docker prod compose | Windows prod 组合 `config --quiet` | 通过 |
| Docker dev images | ai-service/backend/frontend 当前源码构建 | 全部成功，约 407s |
| 五服务健康 | frontend/backend/ai-service/postgres/redis | 当前全部 `healthy` |
| ai-service readiness | 容器内 `/health/ready` | `UP`；三项 checks 均 true |
| authenticated E2E | frontend -> Spring -> Python | 401 未认证；200 已认证 |
| architecture scan | 五类禁用生产模式、Runtime 数量、Store 路径 | 通过 |

组合行为由 Kernel/Application 全量套件覆盖，其中包括 GraphPatch + review barrier/CAS/rebind、guards + commitId、failover、tool retry、orphan cleanup + graphPatchRef、Broker topology/parallel execution、Provenance、restart checkpoint、Legal vertical slice。Milan + real v2 backend 已做认证列表链路 smoke。

## 11. 失败测试 / 未完成能力

- 最终已执行测试没有代码回归失败。
- Application 有 1 个明确 skip；没有把它伪报为通过。
- Application 有 3 个非失败 warning：Pydantic class config、Starlette TestClient/httpx、Chroma asyncio API 的上游弃用提示。
- 前端 build 有 Sass legacy API、两处测试环境 `el-icon` unresolved、chunk 超过 500 kB 的 warning；构建本身成功。
- production compose 仅完成配置验证；本轮重建的是 dev 三镜像，未重建 production images。
- 未对真实付费模型/联网工具发起 live 调用；代码、守卫、重试和 failover 由自动化测试覆盖。
- 未完成浏览器级 `WAITING_REVIEW -> approve -> resume` 真实链路验收；review/recovery/GraphPatch 后端有自动化覆盖，Milan review UI 有前端测试。
- 未在现有用户 volume 上实际执行 backup/restore 演练，避免在正式数据上做破坏性验证；manifest/路径/拒绝旧格式逻辑已验证。

## 12. Architecture scan

扫描范围：`agentOS/src`、`agent/app`、`backend/src/main`、`frontend/src`。

| 禁止项 | 生产命中数 | 结论 |
|---|---:|---|
| `agentos.core` | 0 | 已清除 |
| 旧 `/core` AgentOS URL | 0 | 已清除 |
| `RuntimeGraph` / `runtimeGraph` | 0 | 已清除 |
| `dynamicPatch` | 0 | 已清除 |
| `bindingSwitchCount` | 0 | 已清除 |
| 旧 `ACGExecutor` / 第二 Executor | 0 | 不存在 |
| 第二 `WorkflowRuntime` 定义 | 0 | 仅 1 个定义 |
| legacy production imports | 0 | 命名空间已统一 |

Trace Store 与 Provenance Store 仍各有一个实现，但职责不同：Trace 记录运行审计事件，Provenance 记录生产/消费血缘，不是重复状态真源。`run_degraded` 只为既有 WKN 数据提供 audit-only 反序列化，不参与状态迁移；不存在双主线兼容层或 adapter-on-adapter 大型过渡层。

## 13. 风险列表

### P0

无已知 P0。没有数据删除、不可逆迁移、双 Runtime、双执行真源或公开旧 AgentOS API。

### P1

- 发布前重建并启动 production images，重复 compose health/readiness/authenticated E2E。
- 在隔离副本而非用户正式卷上执行一次 backup -> restore -> restart recovery 演练。
- 使用受控凭据完成真实模型、真实只读联网工具以及浏览器级 `WAITING_REVIEW -> approve -> resume` 验收，确认 commitId、failover 与 Evidence Memory 在真实外部系统下成立。

### P2

- 清理 Pydantic/Starlette/Chroma/Sass 弃用 warning。
- 拆分前端大 chunk，并修正测试环境的 `el-icon` resolution warning。
- 单独执行并治理生产依赖安全审计；本报告不沿用旧报告中的 vulnerability 数字。
- 为 architecture scan 固化 CI gate，防止 `RuntimeGraph`、旧 `/core` 或第二 Runtime 回流。

## 14. 下一步建议与稳定性结论

本分支已经达到**代码级稳定候选版本**：它满足一个 WKN 内核、一个 `WorkflowRuntime`、一个 AgentOS v2 API、一套 Milan 产品外壳、一套六 Store 持久化语义以及一条 current-master Git 主线；所有已执行回归通过，当前五服务健康。

但建议**暂不直接合并为新的稳定 master**。先把第 13 节的三个 P1 发布门禁完成并留存证据；全部通过后，再走受保护 PR 将本 integration 回并 master。当前没有需要重新设计架构的阻断项，P1 是生产发布验证缺口，不是已知代码回归。
