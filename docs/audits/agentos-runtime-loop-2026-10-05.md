# AgentOS Planner 主导的长程 Runtime Loop

日期：2026-10-05。审计基线：`5b683e2eeecf812da4a9798beabe8caff1452122`。本轮直接实现并验证，没有创建 Git commit。原有 `RuntimeInspector.vue` 工作区修改未触碰。

第 1–8 节记录第一阶段；第 9 节记录随后完成的受限证据读取与产物检查，当前能力以第 9 节补充为准。

## 1. 原来的控制环缺在哪里

实际生产链是应用执行协调器 → `ExecutionRuntime` → `PlanningEngine` → TaskPlan → topology / binding / lowering → canonical `CompiledACGPackage V4` → `ACGExecutionService` → Pregel ACG → READY 调度、资源租约和 NodeRunner。`runtime/v2` 承担身份与查询投影，不是第二个执行器。

Planner 原来主要生成初始语义计划与实现绑定。执行开始后，图和 Scheduler 决定可运行节点；NodeRunner 做有界局部重试；Runtime 做资源 failover、审查暂停和最终收敛。图内 verification loop 本来就有自己的有界修订权。这些确定性能力应保留。

真正缺失的是：新的执行事实没有回到 Planner 形成下一轮战略决策。Recovery 会分类并留下恢复建议，通常随后终结 Run；Semantic Revision 可以在持久化审查屏障上产生 replacement Run，但主要依靠外部调用，与失败后的 Planner 没有共同控制链。Artifact、审计、Checkpoint、事件各自存在，却没有统一的运行期 observation 和决策应用入口。

服务重启也暴露这个缺口：旧行为保留审查态，将其他遗留活动 Run 收敛为失败，并没有恢复 Planner 的决策过程。

参考 [LongHorizon-Harness 论文](https://arxiv.org/html/2608.01964v1) 与[实现仓库](https://github.com/AMAP-ML/LongHorizon-Harness)。本轮吸收外置任务状态与重新观察的思想，使用知弈已有组件落实，没有移植其角色组合或执行系统。

## 2. 架构选择与修改范围

加入三个窄边界，并接入现有执行链：

- `contracts/runtime_planning.py`：当前 observation、结构化 decision、持久化 round 与跨 Run 的预算/血缘。允许 `continue / recover / revise / wait / complete / abort`；仅 `revise` 可以携带语义 `TaskPlanPatch`。
- `runtime/planning_loop.py`：选择安全唤醒点，校验和读取持久化事实，以新状态调用 Planner，持久化决策，并检查决策是否仍适用。它不执行图、不分配租约、不实现恢复算法。
- `runtime/planning_application.py`：在短 Run 锁内，通过原有 authority 落实提案。模型调用在锁外；状态发生并发变化时重新观察，取消或终态使旧提案失效。

Planner 的运行期决策复用 `PlanningEngine` 和现有模型调用适配器。`ACGExecutionService` 只获得一个窄的边界回调，没有引入 Planner 或语义修订依赖。`ExecutionRuntime` 保留装配、执行槽和生命周期职责；新的应用服务避免继续把逻辑堆进 facade。

为使链路真实可执行，同时修复了两处被新增执行测试揭示的旧一致性问题：Semantic Revision 最终写入 patch 血缘元数据后重新编译 canonical package，避免 replacement 包 hash 不一致；原地重试写入明确的 `run.retry_prepared` outbox 事件，防止身份投影丢失 FAILED → RETRYING 转移。审计 deny 也获得明确的 policy failure 类型，禁止经重规划绕过。

## 3. 修改后的完整运行链

```text
Mission 进入
  → Planner 初始 TaskPlan
  → 现有 topology / binding / lowering / V4 编译与准入
  → Runtime、Scheduler、资源租约、Executor 执行当前授权片段
  → 输出合同/审计 → immutable node commit、outputRef、Artifact manifest
  → 安全边界：判断是否需要战略唤醒
  → 校验当前持久化状态 → 保存 observation → Planner 新一轮 decision
  → 保存 decision → 确定性检查与 authority 应用
      continue：沿现有图继续
      recover：Recovery 预验证 → 原地单步重试 → 沿现有图继续
      revise：真实 Checkpoint + planning barrier
              → Semantic Revision + topology/binding/编译
              → replacement Run → 同一执行入口继续
      wait：真实 Checkpoint + WAITING_REVIEW，等待外部处理
      complete：检查无剩余工作/完成阻碍 → 现有完成生命周期
      abort：现有失败收敛
```

Recovery 先执行自身完整预验证，确认提案可行后才将来源 Run 转为失败并准备重试。Semantic Revision 仍要求持久化屏障、Checkpoint、冻结 scope、合法 TaskPlan 版本与 capability/topology/binding。Planner 不能提交 executable node、Agent 分配或资源选择。

恢复与 replacement 由原 `_execute_acg` 执行入口迭代推进，并沿用执行槽、取消和身份投影机制。没有新增后台图引擎或第二套恢复系统。

## 4. Planner 何时重新获得控制权

| 条件 | 行为 |
| --- | --- |
| 普通节点完成 | 不调用 Planner，ACG/Scheduler 自主继续 |
| 新 verification 输出 | 无活动 worker、无未解决审查，且不处于图内 control frame 时唤醒 |
| 当前计划执行耗尽 | 完成前唤醒；最后 superstep 不额外重复验证唤醒 |
| 执行失败 | 先由原有局部重试与资源 failover 处理，用尽后交给 Planner |
| Checkpoint / 审查恢复 | 先由原有 resume command 解决审查，再形成当前状态 observation |
| 服务重启 | loop Run 标记 RETRYING/restartPending，通过现有应用协调器恢复，在安全边界重新观察 |

Planner 不审批节点审查，不替代图内 verification loop，也不参与每次排队或租约分配。当前资源健康作为 observation 输入；尚未将资源健康变化接成等待态的自动唤醒订阅。

## 5. 信任边界与职责

| 组件 | 当前职责 |
| --- | --- |
| Planner | 初始语义计划；基于新状态做稀疏战略决策；只提出语义修改 |
| Runtime Planning Coordinator | 安全唤醒、可信引用检查、决策持久化、预算与旧状态保护 |
| Runtime / ACG | 执行控制、事件投影、生命周期、执行互斥和取消 |
| Executor / Agent | 当前授权节点；输出合同、局部有界重试与提交；不掌握任务长期控制权 |
| Scheduler / Resource | READY 判断后的准入、健康/容量约束、租约和分配 |
| Recovery | 失败分类、恢复建议、重试合法性、重用已提交输出及恢复一致性 |
| Semantic Revision / topology / binding | 语义 patch 转成受验证的 replacement package 与 Run |
| Auditor | 独立持久化审计决定与现有合同/风险门禁 |
| Checkpoint / Value / Manifest / Provenance / Event | 提供可恢复状态、引用归属、内容完整性、血缘和决策证据 |

可以进入 observation 的事实包括：任务/计划/图版本、持久化步骤状态、输出引用、唯一已提交 node commit、归属匹配的 allow/review 审计决定、已批准审查记录、封存 Artifact manifest 及校验和、失败分类与恢复建议、当前资源健康。重试复制的输出沿血缘追溯原始 commit 和审计。

没有 commit/audit 的伪造完成状态、跨 Run 的非法引用、未封存或不匹配的 Artifact 不会被当作 Planner 事实。`verificationReport` 只接受结构化 passed/partial/failed；failed/partial 阻止继续或完成。声明了产物却没有有效 Artifact 引用，也阻止完成。Executor 的自然语言 summary 没有进入运行期 prompt。

这些检查证明归属、提交和内容完整性，不证明业务事实正确。现有 Auditor 仍不是独立的环境验证器；passed 验证报告也不是经过外部环境认证的真相。Planner 当前看到的是经过校验的状态和证据引用，尚未自动读取产物正文作语义判断。

## 6. 持久化、重启和真实接线范围

`planningLoop` 保存当前 round 的 observation、decision、状态、指纹及预算；先保存 observation，再调用模型，先保存 decision，再应用。下一轮替换当前 round，不累积 conversation。Trace 只增加有限字段的 observed/requested/decided/rejected 事件，不写模型全文。

重启时，对相同状态的未应用决策重放，避免已保存 decision 被重新询问模型。已批准但中断的 recover/revise 转移通过既有幂等键和 authority 补完。活动节点中断则先由已有 NodeRunner 的提交重放机制对齐，再唤醒 Planner。审查态不自动批准。

replacement 和新 retry Run 继承 roundsUsed、maxRounds 与 parentObservationId，清除旧 Run 的 observation。默认预算为 12 轮，耗尽进入持久化等待屏障，避免修订与重试无限重置预算。

已经接线：正常完成前决策、验证唤醒、失败后决策、原地恢复、Planner 发起语义 replacement 并实际执行、等待/恢复、服务重启重新提交、持久化 decision 重放、取消和并发修改保护。

还没有：资源事件驱动自动唤醒；更细的外部条件等待合同与对应 UI；可信 Artifact 内容摘要/读取；独立业务验收器；多 worker 的分布式执行所有权。当前互斥仍是已有进程内 RunLock/执行槽；外部副作用的重复执行保护依赖现有后端提交幂等机制。

历史上没有 `planningLoop` 的记录不会自动迁移为新 loop；新物化的 TaskPlan Run 接入。保留无 TaskPlan 的旧 workflow kernel 路径。Semantic replacement 沿用现有重新执行语义，没有额外实现跨修订产物复用。外部执行后端和 Resource Center UI 均未涉及。

## 7. 验证结果

最终全量：**835 passed、2 failed，126.24 秒**。命令为 `python -m pytest -q --import-mode=importlib --tb=short`，工作目录 `apps/agentOS`；通过已有 `AGENTOS_*_DB` 环境配置指定本轮独立临时 SQLite 库，没有删除或重置现有数据。完整日志保存在 [`output/agentos-runtime-loop/`](../../output/agentos-runtime-loop/)。

剩余两项在独立基线源码中复现：`test_v2_schema_is_independent_and_complete` 仍断言 schema version 为 2，当前实际为 3；`test_run_snapshot_outbox_excludes_execution_bodies` 的旧 V2 fixture 缺少 Planner identity，因此找不到预期 outbox。没有扩大本轮范围修改这两个旧测试。

使用默认累积库的另一轮全量为 831 passed、6 failed，额外四项为 `test_resource_binding.py` 中 1 秒预算的资源超时。它们在默认库独立运行也失败，在基线新库独立检查 4 passed，在当前独立库全量全部通过。默认库已积累数十 MB；这组结果指向库状态/性能与测试隔离问题，没有证据表明是 Planner Loop 的功能回归。保留两轮日志，不将默认库的检查宣称通过。曾出现的 trace 排序失败在基线可复现，最终独立库全量该项通过。

- 新增 15 项 Runtime Loop 测试，使用真实 ACG、SQLite 持久化和身份投影，模型为受控 fixture；覆盖正常任务稀疏唤醒、验证失败不能完成、等待与重启、实际 replacement 执行、原地重试不重放已完成节点、决策中取消、预算、fresh-state 模型合同、观察/决策/恢复/修订中断及并发状态变化。
- 最终 loop + single-step retry 专项：22 passed。
- Planner progress + fault recovery + loop 回归：26 passed。
- 受影响的恢复、语义修订、Checkpoint、身份、取消与资源回归选择：56 passed。
- 应用 API 与主要 pack 回归：53 passed、5 failed；这 5 项在独立基线源码中复现，属于原有模型 fixture、依赖/关系与 capability catalog 不一致。附件 HTTP E2E 在修改后的正常链路通过。全量中的真实 terminal/edge/cloud 多进程演示也通过。
- `compileall`、新增代码 Ruff、`git diff --check` 通过。默认 pytest 收集有旧重名模块冲突，全量使用 `--import-mode=importlib`。

没有运行付费真实 provider 的任务，没有部署到实际应用环境，也没有浏览器/UI 验收。上述真实接线是代码、实际 Runtime/存储及 ASGI 路径的验证，不等同于外部模型现场任务已验收。

## 8. 下一阶段

先补独立验收事实与受限的证据内容读取，使 Planner 除了状态/引用，还能看到带来源、可检查的业务结果。其次将等待条件绑定到已有 Resource/Runtime Event，恢复时重新观察，同时保持稀疏唤醒。之后再做查询投影和 Inspector 展示，让用户能看清“观察了什么、为什么唤醒、提案为何被接受或拒绝”。

长程控制链已经由 Planner 的持久化决策驱动；其智能决策与确定性 authority 分开，执行权仍留在知弈已有 Runtime 中。余下工作应增强可信 observation 和等待唤醒，不应扩大 Planner 的任意执行权。

## 9. 第二阶段：独立产物检查与受限正文观察

本阶段实现第一批可独立检查的产物事实，复用现有 Artifact/ContentManifest/commit/审计链。没有把任意自然语言验收标准转换成“已通过”的结论。

当前链路：原有 Runtime 唤醒 → `RuntimePlanningObservationBuilder` 校验 commit、归属和审查 → Auditor 的 `inspect_artifact` 读取该 commit 授权的封存 manifest → 完整性与内容检查、受限摘录 → 当前 observation 持久化 → 同一 Planner 模型调用 → 原有确定性 decision 门禁。检查失败成为 completionBlockers，阻止继续或完成；Executor 自述“验收通过”不能覆盖检查结果。

### 9.1 已落实的检查与读取边界

- 校验完整正文 checksum 和 byte length；取得摘录后仍读完流，尾部损坏也会拒绝 observation。
- 文本独立检查非空、UTF-8 编码；JSON 在 256 KiB 解析预算内独立检查语法，拒绝非法语法和 NaN/Infinity。超预算或解析深度受限只报告 unverified。
- 每个产物摘录最多 2048 UTF-8 字节，每轮所有产物合计最多 8192 字节，明确给出截断和未读取原因。二进制不作为文本解码；未批准的审查不向 Planner 放出正文。
- 摘录带 sourceRunId、commitId、manifestId、checksum 和命名检查结果。重试复制的产物沿原有血缘回到来源 commit，不伪造为 replacement/retry 新产生的内容。
- checks 是代码执行结果；正文仍是不可信的来源数据。prompt 明确禁止把正文指令当授权，也禁止从前缀推断全文覆盖。`businessAcceptance` 始终明确标为 unverified。
- 当前 observation 持久化检查与有界摘录，模型依然使用 fresh-state prompt。旧的 reference-only round 指纹保持兼容，恢复时不会因增加默认字段失去已经保存的决策。

审查判断同时覆盖 Auditor 的 review 与 Blueprint 的 reviewRequired，即使风险审计为 allow，也不提前暴露需要人工批准的产物。

### 9.2 更改区文件管理

本阶段增量限制在以下 10 个路径；第一阶段修改继续保留，不覆盖原有前端修改：

| 路径 | 用途 |
| --- | --- |
| `.gitignore` | 精确忽略 `/output/agentos-runtime-loop/` 本地验证日志 |
| `apps/agentOS/src/contracts/artifacts.py` | 产物检查与证据合同，保持 Auditor 对 Planner 实现无依赖 |
| `apps/agentOS/src/contracts/runtime_planning.py` | observation 挂接产物证据及旧指纹兼容 |
| `apps/agentOS/src/components/auditor/artifact_acceptance.py` | 新增独立内容检查与受限摘录 |
| `apps/agentOS/src/components/planner/runtime_decision.py` | 说明证据可信边界和截断限制 |
| `apps/agentOS/src/runtime/planning_loop.py` | 保留战略控制，委托 observation 组装 |
| `apps/agentOS/src/runtime/planning_observation.py` | 从控制文件抽出既有可信状态组装，接入产物检查 |
| `apps/agentOS/tests/components/auditor/test_artifact_acceptance.py` | 独立检查、编码边界、尾部损坏与跨 Run 拒绝 |
| `apps/agentOS/tests/runtime/test_planning_loop.py` | 实际 Planner prompt、审查、预算、重试血缘及恢复 |
| `docs/audits/agentos-runtime-loop-2026-10-05.md` | 两阶段审计和验收记录集中在同一文档 |

源代码和正式报告继续留在更改区；日志保留在已忽略目录供本地复核。临时库通过已有环境配置置于 `.tmp-tests/`，没有删除、搬移或重置已有数据库，也没有创建 commit。

### 9.3 验证与剩余范围

最终验证：

- 产物检查 + Runtime Loop 专项：**32 passed**，包含 11 项 Auditor 检查和 21 项实际 Runtime 路径检查。
- 独立临时库 AgentOS 全量：**851 passed、3 failed，92.25 秒**。三项为先前在基线复现的 trace 排序、schema 版本断言和旧 outbox fixture；正常任务、资源、恢复、Checkpoint、replacement 与新增证据路径通过。
- V2 API、Artifact API 与 Workspace API 回归：**43 passed、2 failed，27.73 秒**。两项旧 fixture 使用已禁止的 StepNode.agentName，在进入本阶段读取代码前就失败；独立基线同两项失败、另外两项通过。
- 本阶段涉及源码/测试的 Ruff、compileall、`git diff --check` 通过。前端文件 SHA256 在本阶段前后相同；Git HEAD 仍为原基线，没有 stage 或 commit。

日志为 `output/agentos-runtime-loop/phase2-targeted-final.txt`、`phase2-full.txt`、`phase2-api.txt` 和 `phase2-api-baseline.txt`，均为本地验证产物，不进入更改区。没有付费真实 provider 或浏览器验收。

自然语言业务标准、真实环境行为验证、资源事件自动唤醒仍未接入。本阶段证明的是内容完整性、可读取性和指定格式性质，不能把业务验收标为通过。下一步应选择一个有明确验收接口的实际任务领域接入环境验证，避免创建无约束的通用 LLM Auditor。

## 10. 第三阶段：调用方冻结的结构化交付验收

### 10.1 架构判断与实际接线

第二阶段的 Artifact 检查只能证明内容存在、完整、可解码和语法性质。TaskPlan 的自然语言 `acceptanceCriteria` 属于可修订的执行计划；若直接把它们当作任务完成标准，Planner 可以在改计划时弱化自己的考题。现有工具审计记录主要是安全元数据，也不能证明现实业务状态。因此本阶段选择明确可检查的 JSON 文档交付要求，建立独立于可变 TaskPlan 的调用方合同。

合同通过现有 Mission/Run 的 `input.taskAcceptance` 进入，在 Run 准入时校验、归一化并深拷贝到 `executionState.taskAcceptance`。它不是 TaskPlanPatch 的字段，没有增加 API、Workflow、Graph 或 Recovery 系统。执行、观察、恢复和语义修订使用同一冻结快照；快照丢失或与 Run 输入不一致时拒绝继续。比较还区分布尔值和数字，避免 Python 的 `True == 1` 破坏冻结边界。

完整链路：调用方要求 → Run 冻结快照 → 初始 Planner 和原生 Executor prompt → 既有 ACG 执行、审计与 node commit → 封存 Artifact → Auditor 独立读取正文并检查声明的谓词 → 当前 observation 持久化 → Planner 决定继续、恢复、修订、等待或完成 → 既有确定性 authority 落实决定。

Planner 的介入频率沿用前两阶段的战略边界，没有每节点调用。每次介入都会重新计算当前任务的验收结果。最终无未完成节点时，失败或未验证的必需要求进入 completionBlockers；完成决定还单独检查所有冻结要求都有 passed 结果。最终产物尚未产生、且仍有待执行工作时，missing 结果不会提前卡住正常继续。

### 10.2 合同、验收范围与原生执行

例如通过现有输入字段声明最终交付文档的标题要求：

```json
{
  "taskAcceptance": {
    "version": 1,
    "criteria": [
      {
        "criterionId": "required-title",
        "artifactKey": "final",
        "pointer": "/title",
        "operator": "equals",
        "expected": "交付报告"
      }
    ]
  }
}
```

可选 `taskKey` 限定语义任务；省略时通过 artifactKey 定位唯一产物。支持 JSON Pointer 的对象、数组、`~0`/`~1` 转义，以及 exists、equals、at_most、at_least 四个不可执行的谓词。存在性检查允许 null，比较区分布尔与数字；数值上下限拒绝字符串和布尔。最多 32 条要求，指针和期望字符串有长度上限，不接收代码、正则或工具调用。

只有既有 Runtime 校验过 commit、归属和审计血缘的产物才成为候选。读取检查来源 Run、manifest、封存状态、checksum 和 byte length，并完整消耗存储流的 checksum 校验。JSON 解析上限沿用 256 KiB；无产物、目标歧义、未批准 review、非 JSON、超预算或解析深度受限记为 unverified；非法 JSON、重复对象键、缺失字段或谓词不符记为 failed。结果携带 criterionId、verifier、sourceRunId、commitId、manifestId 和 checksum，不采用 Executor 的 summary 或 verification 自述。

原生 Agent 已有确定性 Artifact 投影，但原来固定输出 Markdown。现在冻结要求匹配当前产物时，将同一份原生 `deliverable` 对象封存为 application/json，谓词的根即该对象；`final_answer` 保留已有 Markdown 展示。没有匹配要求的普通任务仍用 Markdown。原生能力合同允许该 JSON 格式，不要求模型重复生成一份正文。另修复旧 Workflow 转 Blueprint 时丢弃 logicalRole 的单行兼容问题，使已声明的最终产物身份在准入与 replacement 后一致。

所有结果明确标注 `scope=document_requirement`。JSON 中“成本为 99”满足值域要求，只证明交付文档写了这个值，不能证明现实成本、计算依据、工具执行或自然语言业务结论真实。通用 ArtifactEvidence 的 businessAcceptance 继续是 unverified；本阶段的命名检查不会冒充全面业务验收。

### 10.3 恢复、重规划与边界

- 原地 Recovery 保留合同。successor retry 显式继承源 Run 的冻结要求；即使 Mission 后来修改了输入，也不会改变失败任务的验收要求。无原始合同的 retry 也不会意外引入后来加到 Mission 的合同。
- Semantic Revision 通过既有 authority 创建 replacement，并继承合同和 Loop 预算。实际测试中 101 超过上限 100 → Planner 修订交付节点 → replacement 产生 99 → 独立检查通过 → Planner 完成；原始要求始终是 100。
- 删除要求对应的交付节点只会产生 artifact_missing，无法删除调用方合同。human review 只恢复 Planner 决策机会，不能把失败的谓词变成通过。
- Run SQLite 快照和现有 Checkpoint 共同支持冷启动恢复：重建 observation 时重新读取冻结合同与提交产物，而不是拼接旧对话。无合同的旧 round 默认字段不进入指纹，保留前两阶段持久化决策的兼容性。
- retry 的复用输出沿既有 commit 血缘回溯，验收结果仍指向原始 source Run；不把复制引用当成新执行证据。
- 保留现有 Semantic Revision 的 fresh graph 行为：replacement 会重新执行该修订计划中的节点，本阶段未改变其工作复用策略。测试明确检查这一行为，不能宣称 replacement 自动只执行受影响节点。

### 10.4 更改区管理

本阶段新增 3 个文件：`src/contracts/task_acceptance.py`、`src/components/auditor/task_acceptance.py`、`tests/components/auditor/test_task_acceptance.py`，均在 `apps/agentOS/` 下。现有文件按职责接线：

| 区域 | 本阶段继续修改的路径 |
| --- | --- |
| 当前状态与完成闸门 | `apps/agentOS/src/contracts/runtime_planning.py`、`apps/agentOS/src/runtime/planning_loop.py`、`apps/agentOS/src/runtime/planning_observation.py` |
| 准入、恢复与修订 | `apps/agentOS/src/runtime/workflow_runtime.py`、`apps/agentOS/src/runtime/runtime_recovery.py`、`apps/agentOS/src/runtime/semantic_revision.py` |
| Planner 输入 | `apps/agentOS/src/components/planner/task_decomposer.py`、`apps/agentOS/src/components/planner/runtime_decision.py` |
| 原生交付投影与兼容 | `apps/agentOS/src/adapters/model/native.py`、`apps/agentOS/src/adapters/model/native_prompt.py`、`apps/agentOS/src/support/acg/native_capabilities.py`、`apps/agentOS/src/support/acg/legacy/workflow_adapter.py` |
| 执行与输入回归 | `apps/agentOS/tests/runtime/test_planning_loop.py`、`apps/agentOS/tests/adapters/test_native_agent.py`、`apps/agentOS/tests/adapters/test_native_prompt_v2.py`、`apps/agentOS/tests/components/planner/test_hierarchical_task_decomposition.py`、`apps/agent/tests/test_agentos_v2_api.py` |
| 审计报告 | 本文继续追加，未建立第二份阶段报告 |

前两阶段的未提交修改继续保留，原有 `apps/frontend/src/components/workspace/RuntimeInspector.vue` 未触碰，SHA256 与阶段开始一致。验证日志仍位于已忽略的 `output/agentos-runtime-loop/`，独立数据库使用 `.tmp-tests/` 与已有环境变量；没有重置数据库、stage 或 commit。

### 10.5 验证与剩余工作

最终受影响专项：**97 passed，38.89 秒**，覆盖两个 Auditor 验证器、Runtime Loop、原生 Agent、原生输入合同与初始 Planner 分解。

AgentOS 独立临时库全量运行：**876 passed、3 failed，85.65 秒**。失败与第二阶段相同：trace 时钟排序、旧 schema_version=2 断言、缺少 Planner identity 的旧 outbox fixture，均已有基线复现记录。随后补充的布尔/数字冻结替换回归纳入最终专项验证。

Mission/Run、Artifact 和 Workspace API 回归：**44 passed、2 failed，19.71 秒**。新增 API 测试真实经过现有异步命令、初始 Planner、ACG、提交产物、验收与运行期 Planner 完成；模型与执行响应为受控 fixture。两项失败仍是已基线复现的旧 StepNode.agentName fixture，尚未进入 Runtime。原生 Agent 的分节恢复和确定性组装同时验证普通 Markdown 与 JSON 验收模式。

新增文件和没有存量告警的受影响文件 Ruff 通过，compileall 与 git diff --check 通过。三个旧文件存在 **11 条基线 Ruff 告警**：native_capabilities.py 9 条、task_decomposer.py 1 条、workflow_runtime.py 1 条；本阶段逐一与 HEAD 对照，未为清理它们扩大改动。

日志：`phase3-full.txt`、`phase3-api.txt`、`phase3-targeted-final.txt`、`phase3-lint-clean.txt`，以及三个 `phase3-*-lint-baseline.txt`。未进行真实付费 provider、部署后长程任务或浏览器验收。

本阶段完成首批结构化文档验收接线，未接入自然语言语义验收和外部环境事实验证。后续主阶段仍是：第四阶段建立持久化外部等待条件与事件唤醒；第五阶段做真实模型的多轮长程任务、重启及异常验收。特定任务领域的外部 verifier 可以沿当前合同与证据边界继续接入，应保持有限、可测试的 authority，不扩展成万能 LLM Auditor。

## 11. 第四阶段：持久化条件等待与自动唤醒

### 11.1 缺口与方案

前三阶段已经建立运行期决策，但 Planner 的 wait 只有人工恢复入口。资源变化虽然进入 observation，却不能让一个暂停任务重新获得决策机会。靠保留一个等待中的模型 conversation 或执行协程无法解决冷启动和通知丢失。

本阶段把有限条件挂在原有 wait decision 上，在 `executionState.planningLoop.waiting` 保存所属 observation、条件、armedAt 和满足条件的证据。仍复用现有 Planner Checkpoint 屏障、Run FSM、Run lock、NodeService、Runtime Event 和应用层 RunExecutionCoordinator；不建立另一套 Runtime，也不新增 Workflow 或通用回调 API。新增一个 `runtime/planning_wait.py`，只负责确定性条件检查和持久化唤醒转移。

首批支持：

| 条件 | 满足依据 | 不授予的权力 |
| --- | --- | --- |
| `until` | 带时区的 notBefore 与系统当前时间 | 不证明工作已完成 |
| `node_available` | 已被本轮 observation 观察的 Node；启用、当前 online、心跳有效且无连续失败 | 不授予 Agent binding、租约、容量预留或节点审查批准 |

例如 Planner 可以返回 `{"action":"wait","observationId":"...","reason":"等待节点恢复","waitFor":{"kind":"node_available","nodeId":"edge-1"}}`。不带 waitFor 的 wait 继续使用人工恢复；模型异常、非法决定、预算耗尽产生的安全等待不自动循环唤醒。

### 11.2 完整运行链路与权限

Planner 提出 wait 和条件 → 确定性合同校验及 Node 注册检查 → 原有 Planner review 屏障与 Checkpoint 持久化 → 执行协程退出 → 当前协调器收到可信节点 observation 的提示，或周期性重查持久化等待 → 在 Run lock 下重读最新 Run、检查屏障所属决定及 Checkpoint/输出引用一致性 → 检查当前时间或 NodeService 状态 → 原子保存 wake proof、清除仅属于 Planner 的暂停标记、转为 RETRYING，并记录 `planner.runtime.woken` → 原有协调器 submit → Runtime 重新构造当前 observation，wakeReason 为 condition → Planner 决定 continue/recover/revise/wait/complete/abort → 既有 authority 校验并落实决定 → 继续当前执行片段或结束。

节点 observation API 继续要求现有身份签名和单调 sequence；成功写入 NodeService 后只发一个重新检查的提示。提示不携带决策权，未认证请求不能推动可信状态。监视器每秒执行同一确定性检查以覆盖计时条件、通知丢失及直接写入 NodeService；条件未满足时不调用模型。Run 查询分页遍历，避免较早等待被最近 200 条记录遮挡。事件突发和重复重查仍走原有协调器去重及 Runtime 执行槽。

Auditor 节点/控制审查不会被条件唤醒自动批准。条件满足不能绕过 Artifact、冻结文档验收、失败节点、Recovery 或 Scheduler 准入。失败节点必须通过 recover；可用 Node 仍可能在之后失去容量，由 Scheduler 再次判定。Planner 仍不介入普通节点完成、租约分配及图内局部验证控制。

### 11.3 持久化、重启与接线修复

- 满足条件的证据与 RETRYING 状态一起持久化；提交前进程退出，启动后可重新投递，不重复追加 wake 事件。未满足的等待保持原屏障，重启不重新请求模型。
- condition observation 带原等待 observationId、checkedAt；节点条件另带 snapshot version、observation sequence 和 online 状态。每轮仍重新读取当前任务、产物与冻结验收，不拼接历史 conversation。
- Checkpoint 丢失、不匹配、存在活跃步骤时不唤醒；取消和普通人工等待不进入自动唤醒。
- replacement/retry successor 继续继承预算和决策血缘，清除源 Run 的等待及唤醒证明；新 Run 必须自己建立当前等待，不能复用旧条件的许可。
- 恢复入口现在落实 Planner 的 complete 返回值，直接走原有统一完成处理，避免再到 exhausted 边界重复请求 Planner。
- 实际节点放置的恢复测试暴露旧入口将 Node ID 当作 Agent ID 的问题。恢复 runner 时读取原有 executionBindings 的 Agent/Node 元数据，仅在 resourceId 一致时使用；显式重新绑定仍优先。没有增加另一套 binding authority。

### 11.4 更改区管理与验证

本阶段只新增 `apps/agentOS/src/runtime/planning_wait.py`；继续修改既有 runtime planning 合同、Planner prompt、observation/decision 应用、Runtime facade/执行入口、应用协调器、节点 observation API，以及对应原有测试和本报告。前阶段未提交工作全部保留，前端 `RuntimeInspector.vue` 未触碰。日志集中于已忽略的 `output/agentos-runtime-loop/`，测试 SQLite 放在已忽略的 `.tmp-tests/`；未 stage、commit、迁移或清理已有数据库。

AgentOS 完整测试：**891 passed、3 failed，102.15 秒**。失败仍为已基线复现的 trace 排序、schema 版本断言和 outbox 旧 fixture。随后补充的失败等待恢复及 condition round 中断重放，另行纳入最终 Runtime 专项验证。

最终 Runtime 专项：**46 passed，70.72 秒**。覆盖未满足条件不调用模型、重复投递不重复 wake、等待及已满足条件的冷启动、SQLite 节点状态恢复、取消/人工等待隔离、Checkpoint 损坏拒绝、分页公平性、未完成片段继续、失败验收阻断、失败等待后走原有 Recovery，以及 condition observation/decision 持久化后的进程中断重放。最后三项组合案例是在全量运行后新增并通过此专项验证，未再次修改生产代码。

应用协调器与 Mission/Run、Artifact、Workspace API：**50 passed、2 failed，15.53 秒**。新增测试真实经过异步 Mission、动态初始规划、ACG 执行、产物提交、运行期 Planner 等待、后台时间/签名节点唤醒，再进入 Planner 完成；模型及 Agent 响应为受控 fixture。两项失败仍是已基线复现的非法 StepNode.agentName 旧 fixture。

本阶段涉及文件的 Ruff 检查未增加告警；无存量告警的涉及源码和测试检查通过，compileall 与 git diff --check 通过。旧 acg_execution.py 的 25 条 E402、API 的 2 条 F841/F811 和 workflow_runtime.py 的 1 条未使用导入分别与 HEAD 对照保留；不扩大范围处理这些旧问题。详细日志为 `phase4-loop-final.txt`、`phase4-full.txt`、`phase4-api-final.txt`、`phase4-lint-clean.txt`、`phase4-lint.txt` 及对应 baseline 日志。

### 11.5 尚未接线与下一阶段

首批仅接时间及 NodeService 健康条件；尚无任意外部 webhook、外部业务状态订阅、provider 可用性条件、通用自然语言业务 verifier 或等待 UI。单进程去重沿用已有所有权机制，尚未建立分布式多 worker claim。定期分页检查是可靠性兜底，更多等待规模下可再优化索引/通知和检查成本；不应把每次状态变化变成模型调用。

第四阶段完成后，五阶段路线剩第五阶段：使用真实注册模型与知弈自身执行器，验证多次战略决策、失败后等待恢复、语义 replacement、Checkpoint/进程重启及最终可信验收，并修复实测边界。当前未调用付费 provider、未部署、未做真实长程任务或浏览器验收，不能据测试 fixture 宣称这些路径已在线验收。

## 12. 人机澄清与真实 ACG Copilot 面板

### 12.1 实际缺口与接线方案

原面板的会话、执行预览及模型标签是静态样例，发送操作没有请求后端。原有 review comment 虽能记录人工决定，却不进入 Planner observation；因此不能用“已有审核入口”代替多轮澄清。

本轮保留既有工作区和 Runtime，接通两条边界：普通对话使用当前任务注册的规划模型，读取新的可信状态快照，仅解释和建议；Planner 澄清通过 wait.question 暂停，用户回答写入现有 planningLoop 的有限状态后，交回原有执行协调器。聊天本身不批准审查、修改图或启动执行。

没有接入 Codex、DeepSeek Harness 等外部执行后端。视觉及轨迹组织参考用户截图与 [DeepSeek Harness 开源实现](https://github.com/deepseek-ai/deepseek-harness/tree/5badb15009ae1756c3afe0ae0cef1faafc290ccc/packages/client/ui-trajectory/src/client)：读取了 TrajectoryCell、trajectory-record 和 timeline 的记录类型、callId、时间及来源组织；仅吸收展示原则，未把其运行循环或源码组件复制到知弈。

### 12.2 完整交互链路

执行结果 → Planner 读取当前 observation → 需要用户澄清时返回 wait.question（问题与最多五个建议答案） → 原有 Planner Checkpoint 屏障持久化并退出执行 → Copilot GET 读取真实待回答问题 → 用户通过已认证 Run 边界提交 questionId、answer、expectedRevision、operationId → 在 Run lock 内验证当前问题、revision、Checkpoint 和输出引用 → 保存有 sourceRunId/questionId/answeredAt 的回答及 userInputPending，并转为 RETRYING → 原有协调器 submit → 新 observation 的 wakeReason 为 user_input → Planner 消费 humanAnswers，决定继续、恢复、修订、再次提问或结束 → 原有确定性 authority 落实。

回答最多 2000 字符，澄清记录最多 32 条，仍受原有 lineage 规划轮数预算限制。答案是用户陈述，不是经过环境验证的事实，也没有修改冻结 taskAcceptance 的权力。节点/控制审核与 Planner 澄清严格区分；有问题的 Planner 屏障不能通过普通 review approved 解除。

回答与恢复标记在同一 Run 快照事务中保存；提交前中断可由原有启动/等待扫描重新投递。每轮回答只针对当前问题，同 operationId 相同内容可重放，不同内容、旧问题或旧 revision 返回冲突。replacement 和 retry successor 继承有效回答及来源，但清除源 Run 的待唤醒标记；不会将源 Run 的回答重新当成新 Run 的操作许可。

普通对话单独保存在 WorkflowStore 的 run_copilot_exchanges 表，避免模型响应覆盖并发变化的执行快照。每次只读取最近四轮对话和新的当前状态快照；界面读取最近三十轮。聊天请求及成功响应以 operationId 成对持久化，模型失败明确报错，保留草稿；不产生静态成功回复。当前会话是 Run 范围，尚未提供跨 Run 的完整聊天历史分页。

### 12.3 前后端与轨迹

| 入口 | 行为 |
| --- | --- |
| `GET /runs/{runId}/copilot` | 读取当前问题、回答、对话、决定摘要及状态 |
| `POST /runs/{runId}/copilot/messages` | 调用当前任务规划模型，返回只读解释 |
| `POST /runs/{runId}/copilot/answers` | 校验并持久化回答，异步提交 Runtime 恢复 |

Python 保留既有 Run 所有者/租户检查；Java 经原有 AgentOsReviewController 转发路径、请求与响应状态；Vue 通过现有 authenticated agentosRequest 调用。回答接收为 202，不在 HTTP 请求中同步等待整项任务完成。

面板移除演示会话、模拟执行预览与硬编码模型名，使用既有深色 token、图标与安全 Markdown 渲染。增加真实空状态、加载/错误状态、问题选项、回答/询问模式、保留草稿的重试、历史只读、切换 Run 的过期响应保护和输入法 composition 处理。只在用户接近底部时跟随新消息，不强制拉走正在阅读的位置。

轨迹复用 RuntimeObservation Trace，以及已有 resource-usage/calls 的模型调用记录。按规划、模型、工具和执行分类，可搜索、展开详情、加载更多模型调用；显示已记录的所属步骤、callId、callChainId、partIndex、延迟及 token。相同 callId 的两种投影去重；仅从明确记录追溯归属，不伪造父子调用边、并行关系、token 或时间。尚未实现完整瀑布时间轴、调用关系图及全量轨迹虚拟滚动。

### 12.4 文件管理、验证与交付边界

新增源码仅两个文件：`apps/agentOS/src/runtime/planning_interaction.py`、`apps/frontend/src/services/api/agentos/api/copilot.ts`；新增前端专项 `AcgCopilotPanel.spec.ts`。现有 Runtime planning 合同、observation/application/wait/loop、ReviewService 和 WorkflowStore 按职责接线；应用 API、既有 Java 控制器和对应测试同步修改。前端只改 Copilot 面板、API composition 及 Workspace 测试。

此前未提交工作保留，RuntimeInspector.vue 的 SHA256 仍为 FB5F02D2DEE4B6A06B98E51E8F0CE4DF26B5D7048F89E1EC540A1E7D6B780AF3。执行期间出现的 ModelRuntimeControls、AuthenticatedAppShell、ChatView、SettingsView 和翻译等其他改动未被本轮覆盖。构建自动删除的 RoleManagementPanel 全局类型声明已恢复到阶段开始状态。未 stage、commit 或替换正在运行的服务；日志、参考源码和视觉验收页放在已忽略的 output/agentos-runtime-loop，测试数据库及构建临时文件放在 .tmp-tests。

验证记录：

- AgentOS 全量 **898 passed、3 failed，177.38 秒**；失败仍是已有 trace 排序、schema 断言和 outbox fixture。新增多轮澄清、冷启动、普通聊天持久化/幂等及回答血缘测试通过。随后把回答血缘检查加强为真实 semantic replacement 集成，并整理 Planner 澄清与条件等待的提示词；最终相关专项 **7 passed、43 deselected，12.11 秒**，编译检查通过。全量测试未在这次提示词调整后重复执行。
- Python 应用协调器与 API 回归 **51 passed、2 个已有 StepNode.agentName fixture 失败**；最终 Copilot 专项 **4 passed**，包括真实异步回答续跑，以及三个新接口的 Run 所有者隔离。
- Java AgentOsReviewController **5 tests、0 failures/errors**，覆盖读取、回答 202 和模型不可用 503 的透传；未运行整个 Java 测试集。
- 前端 Copilot/Workspace 专项 **37 passed**；Web 类型检查和生产构建通过。最终前端全量 **91 个测试文件、592 项测试全部通过，89.20 秒**，结果见 interaction-frontend-full-final.txt。首次全量曾受执行期间其他 ChatView 改动影响；本轮未修改该页来绕过失败。
- Playwright 检查实际 Vue 组件：420px 对话布局、选择回答并提交、轨迹与模型调用展开、300px 侧栏宽度（实际 299px，scrollWidth 不超过 clientWidth）。最终组件页无新增 console 错误/警告；截图为 copilot-question.png、copilot-trajectory.png、copilot-call-details.png、copilot-narrow.png。浏览器使用标注的受控视觉数据；不是完整线上服务或付费模型验收。
- 涉及的新源码及无存量告警的 Python 文件 Ruff 通过，保留 API 已确认的两项旧告警；编译和 git diff --check 通过。构建曾遇到 Windows 临时文件/声明文件访问错误，停止本轮预览服务并隔离临时目录后标准 build:web 成功。

当前完成了代码、接口及受控端到端接线。现有部署必须加载新的 Python/Java/前端版本后，实际工作区才会使用这些入口；不能把本次组件截图或测试等同于已更新当前在线实例。真实模型的长程多轮澄清、恢复与 replacement 验收仍是下一阶段工作。本轮也未增加聊天流式响应、附件上传、模型切换或任意工具执行入口。

### 12.5 实际部署接口不存在的修复

2026-10-05 用户反馈工作区 GET copilot 返回接口不存在。现场确认 Java 日志为 NoResourceFoundException，运行中的 /app/src 控制器及其 class 仍为旧版本（class 编译时间为 2026-10-04）；宿主机挂载 /kinlin-host/backend-src 已包含新接口。当前开发容器在启动时同步源码并运行 Maven，并不会仅因宿主源码修改而同步缓存、重新注册路由。

只重启现有 backend 容器，复用其源码同步、Maven 编译和 Spring 启动流程；没有重建镜像、重启 AI 服务或操作数据库/数据卷。同步结果 changed，新的 controller class 于 2026-10-05 重新编译，五个服务均 healthy。

经实际 9050 前端代理 → Java 认证网关 → Python 的链路验证，截图对应 run_2f7f44e7eceb 的 GET copilot 返回 **200**，runId 正确、status=completed、modelAvailable=true；messages 与 answers 用空请求验证均返回 **422**，不再为接口不存在，且未触发模型调用或续跑。诊断脚本位于已忽略的 output/agentos-runtime-loop/verify-live-copilot.py，凭证只在内存中使用，未输出或保存。真实模型发送及澄清续跑的在线验收仍待进行。

### 12.6 输入框、模型与权限选择

依据用户提供的 Codex 插件截图调整输入区：更克制的圆角与边框、自动增长且不显示拖动柄的输入框、底部左侧权限、右侧模型及圆形发送按钮。菜单在输入框上方展开，支持键盘 Tab/Escape 与点击外部关闭；历史 Run 和提交期间禁止修改选项。工作区既有主题、图标与其他未提交修改保留。

模型目录直接从 Runtime 的 ModelCompatibilityRegistry 健康路由投影，不新增注册表，不读取用户普通聊天的外部 API 配置或接受客户端传入端点/密钥。RegisteredPlannerLLM.for_model 创建独立请求绑定，沿原结构化模型调用链完成请求；不修改 Runtime 的默认绑定。消息记录保存 modelId、requestedModelId、permission，幂等重放也校验选项，用户改变模型或权限后重试会产生新的操作 ID。不可用/未注册模型被拒绝，不静默回落到其他模型。

权限为 read_only（仅对话）及 task_collaboration（按需确认）。普通消息两种模式均只能解释状态和建议；仅 task_collaboration 允许显式回答当前 Planner 问题并沿既有恢复屏障续跑。后端拒绝 read_only 回答，不以 UI 禁用替代检查，不开放任意文件写入、工具执行、Graph 修改或绕过审计的“完全访问”。回答模式显示并固定任务规划模型；选择其他模型仅影响普通对话。

验证：前端全量 **594 passed / 91 files，119.39 秒**；Runtime Loop 与模型注册表完整相关文件 **63 passed，125.46 秒**。随后补充默认模型可用性判断和回答模式固定模型显示，最终 Copilot UI **8 passed**、Runtime 交互 **8 passed**、API/应用绑定 **7 passed**。TypeScript 检查及标准 build:web 通过（Vite 15.53 秒），构建生成器删除的原 RoleManagementPanel 类型声明已单独恢复。核心新增 Python 文件 Ruff 通过；wiring 与其原测试文件的四项旧 unused-import 告警经 HEAD 核实，未扩大清理范围。

Playwright 检查实际 Vue 组件的模型/权限菜单及 300px 侧栏，实际宽度 299px、无横向溢出，控制台无错误或警告。截图 composer-model-menu.png、composer-permission-menu.png、composer-narrow.png 使用明确标注的受控数据，不代表生产环境拥有截图中的模型。实际 9050 网关 GET 返回 **200**，当前注册模型是 deepseek/deepseek-flash，并返回两种权限；未注册模型消息及 read_only 回答均返回 **422**，未调用付费模型或修改 Run。在线模型调用与长程任务验收仍待进行。日志在已忽略的 output/agentos-runtime-loop/composer-*，没有 stage 或 commit。

### 12.7 思考程度、流式回复与对话加载

模型菜单增加思考程度，档位来自应用层已有 provider_model_capabilities 的声明，Runtime 仍只接收经过声明校验的 reasoningEffort。本地当前 deepseek-flash 声明 low/high/max，另有关闭选项；关闭沿原无显式档位路径，显式档位传入原 RegisteredModelRuntime，再由提供商适配器落实，不伪造统一的所有模型档位。交换记录及操作幂等校验包含档位。用户消息与普通助手消息不再显示“你”、ACG Copilot 等角色标题和时间行；Planner 澄清仍保留其业务标记。

新增 POST copilot/messages/stream，沿既有 Java AiSseGatewayService.openPost 非缓冲转发，Python 使用原 call_planning_model 的 progress_callback 消费 RegisteredPlannerLLM.stream_generate_json。增量只解码 JSON 的 content 字段，包含半个转义序列、UTF-8、Unicode surrogate 的边界处理，不展示原始 JSON 或私有推理。预览采用有界队列、累计正文快照、重试时清空及心跳；只有完整 CopilotReply 校验通过并写入 Workflow Store 后才发送 completed。失败/截断预览不存为对话事实。客户端断开时，同一幂等操作在原模型期限内完成，重新连接重用 operationId；无新的 Runtime 或 Planner 控制权。

前端通过带现有登录凭证的 fetch 读取 SSE，覆盖任意网络分片、多字节字符、错误、提前结束和取消。生成中的用户消息立即显示，正文随服务器内容逐步更新；只有 completed 后进入正式消息列表。面板关闭或 Run 切换时终止客户端读取，仍保存未完成操作的 ID，防止重开后重复调用模型。

用户反馈加载慢后，实际 9050 链路 GET 抽样约 32–46ms，未证明存在持续后端阻塞。对话 GET 改为复用既有内容寻址快照并只读取一次，不再为目录查询构建整个 PlanningEngine。前端新增最多八个 Run、仅内存、随登录凭证切换失效的展示缓存，恢复聊天、草稿和选项后再读取最新服务状态；最新状态确认前禁用提交，权限仍在服务端校验。缓存不会写入 Runtime、持久化用户凭证或成为 Planner observation。未变化 Markdown 使用 v-memo，终态轮询从 3 秒降至 15 秒，页面后台暂停读取，并修复卸载后异步轮询可能重新排队的路径。本轮未测量完整桌面冷启动/FCP，不能把接口抽样当成整体页面加载性能。

验证结果：前端全量 **599 passed / 92 files，114.82 秒**；Runtime Loop 与注册表完整相关文件 **65 passed，122.10 秒**；Python Copilot/绑定/归属专项 **7 passed**；Java SSE/Review 控制器 **8 tests，0 failures/errors**。全量后补充重开面板保持原操作 ID 的保护，最终组件及 SSE 传输专项 **14 passed**；标准 build:web（含 TypeScript 检查）通过，Vite 16.99 秒，生成器删除的原类型声明已单独恢复。测试覆盖正文先于完成到达、未完成时无持久化事实、断开后完成并可幂等取回、失败无保存、档位透传、跨 Run 旧响应、初始缓存展示与最新状态门禁。

Playwright 检查实际组件：思考菜单、回复完成前正文可见、角色标题数为零、300px 侧栏无横向溢出，控制台无错误或警告；截图 copilot-thinking-menu.png、copilot-streaming.png、copilot-stream-narrow.png 仍为标注的受控数据。运行中的 backend 已重启加载 SSE 路由，五服务健康；真实 9050 网关返回 SSE **200**，未注册模型产生预期 error 终止事件（约 33ms），证明实际路由及协议可达，不调用付费模型、不修改任务状态。正常真实提供商输出流与整段长程任务在线验收尚未执行。日志为 output/agentos-runtime-loop/stream-*。

### 12.8 Copilot 受控操作与断点重跑

Copilot 现在是用户意图进入既有 Runtime Loop 的入口。新增 `runtime/planning_operations.py` 管理结构化操作方案和确认回执，复用 Runtime facade、Recovery、Workflow Store 和 RunExecutionCoordinator；没有新增 Workflow、图执行器或恢复引擎。普通模型对话可以提出 typed action，也可以从输入框左下角“任务操作”菜单直接指定操作和节点。显式菜单的预览不需要模型调用。

当前完整链路为：用户消息或节点选择 → Copilot 提出操作意图 → 后端校验所有权、权限、当前状态、Checkpoint 与证据 → 保存不可变方案并展示重跑/复用范围 → 用户确认 → Run lock 内重查 revision 与实际影响范围 → 既有确定性组件准备 successor Run 或持久化补充要求 → 原协调器投递执行 → Runtime 在可信执行边界重新观察 → Planner 决策 → Scheduler、Recovery、Semantic Revision、Auditor 落实各自职责。模型输出方案不代表操作已经执行；回执只表明运行已提交或要求已保存。

| 操作 | 实际行为 |
| --- | --- |
| 原样重跑 | 终态且未被替换的 Run，沿用该 Run 的计划、输入、绑定、插件范围和冻结验收，创建同 Mission 的 successor；不读取后来修改的 Mission 输入替换原材料 |
| 从指定节点重跑 | 新 Run 重跑指定可执行 step 及因果下游，其余已完成且可验证的节点提交复用；依赖边及编译后的通信边共同参与影响范围 |
| 已结束的验证循环 | 编译后的 ControlManifest 决定循环边界；触及循环内节点时，控制节点、body entry/exit、条件生产者及其下游作为整体失效，原图重新执行循环与迭代限制 |
| 恢复失败任务 | 仅 FAILED Run，经原 Recovery 的失败节点/已提交上游复用 authority 创建 successor；暂停任务通过回答问题或补充要求重新进入 Planner，不能借恢复操作审批审核 |
| 提交补充要求 | RUNNING/RETRYING 或没有未答问题的 Planner 等待；先独立持久化用户输入，执行片段结束并解决局部控制/审核后再唤醒 Planner |

第一批断点操作支持严格通信的依赖图，以及已结束且没有遗留迭代状态的 bounded verification loop。活跃控制帧、loopIterations/loopPaths、未解决的节点/控制审核、blackboard/debate/consensus，以及其他控制类型继续拒绝。不能仅重跑一个生产者却留下消费者的旧结果。复用证据检查可跨多代 successor 追溯原提交和审核；新尝试与复用步骤沿原身份投影落实，原 Run、Checkpoint 与 Artifact 不被覆盖。

补充要求采用 Workflow Store 的独立 `run_planning_inputs` inbox，SQLite 与 Memory 实现保持一致，每条有 sourceRunId、operationId、正文和时间，且全血缘最多 32 条。它属于可追溯的用户声明，不是已验证业务事实、工具权限或新的冻结验收。普通长对话仍不作为 Planner 的无限历史上下文。Planner 在无活动执行片段、无待处理审核和局部控制帧的边界导入新要求，新增稀疏 `user_input` wake；模型不可用时等待，不能静默忽略要求。输入在模型决定期间到达会使旧决定失效，原 Runtime 重读状态再决策。Checkpoint 等待、冷启动、Recovery 和 Semantic Revision replacement 均继承尚未消费的输入及既有规划预算。

确认按 proposalId 派生幂等键。重复点击、丢失响应后重试和已生成 child、尚未保存回执的中断都复用已有结果；确认时不能更换目标、升级只读权限或使用过期 revision。节点 successor 在复用提交和身份事件全部准备后才发布，避免重启时观察到半初始化 Run。SQLite outbox 同秒事件改为按插入序号保持因果顺序，避免 Attempt 的字母序 ID 先于 Run 创建事件被投影。新增回归覆盖发布前中断，重试后只出现一个可见 child。

检查还修复了上一阶段文档验收对 Python 全局递归限制的隐式依赖：JSON 文档在解析前有明确的 128 层嵌套上限，字符串中的括号/转义不计入层数。超深文档为 parser_limit/unverified，不能因其他测试提高递归限制而改变验收事实。

验证期间发现原 Runtime 在真实验证循环第二次执行时，执行记忆可能使用不含 iteration 的 `memory:{run}:{step}` 键而发生不同输出冲突；该路径在创建原 Run 时即复现，不由断点操作引起。本轮未扩展重构 Memory authority，也未放开带遗留迭代状态的 source。下一阶段应结合尝试身份、Checkpoint 和执行记忆解决这个循环重入问题，再扩大断点支持范围。

#### 人工验收

按用户要求停止本轮浏览器自动验收。此前的浏览器截图属于上一轮样式/流式验证；本轮仅打开了受控预览，随后关闭浏览器和预览服务器，不把它记为操作验收。

1. 打开一个已结束且未被替换的当前 Run，将输入框权限设为“按需确认”。打开左下角“任务操作”，选择一个节点，再点“从指定节点重跑”。此时只应出现方案卡，不应开始执行。
2. 核对卡片中的重新执行与复用步骤。普通依赖图包含所选节点和下游；验证循环内节点包含整段验证区域。点击“确认操作”，再点“查看新运行”。Run ID 必须改变，Mission 不变，原记录仍可查看。
3. 检查新运行的步骤与轨迹：影响范围内有新执行/模型调用，其余可复用步骤沿旧提交血缘完成；产物来自新 Run 的真实输出。重复确认或刷新重试不应创建第二个 child。
4. 分别检查“原样重跑”和 FAILED Run 的“恢复失败任务”；检查只读模式不能准备或确认任务操作。暂停审核不能通过任务操作绕过，过期方案应要求刷新。
5. 在较长的执行中或普通 Planner 等待时，填写要求并选择“提交补充要求”，确认后观察 `planner.runtime.*` / `user_input` 和后续规划。若已有 Planner 问题，走现有“回答问题”入口。该测试检查用户交互真正进入 Loop，不以普通聊天回复或确认回执代替规划结果。

#### 更改区与服务边界

此前实现阶段没有执行 stage、git commit、reset 或数据清理，`RuntimeInspector.vue` 保持原哈希，日志和测试数据仍集中在忽略目录 `output/agentos-runtime-loop/`、`.tmp-tests/`。另一个并行会话在验证期间创建了 `aa4cef8b` 工作区基线快照并开始资源平面重构，随后移除了旧消费者仍导入的 ResourceProfile，使当前工作树暂时无法收集 Runtime 测试。没有回滚或覆盖其资源文件；最后的断点/Runtime 回归在该快照的隔离源码副本中覆盖本会话最后修改后执行。隔离验证不代表并行资源重构已通过验收。本次提交仅包含下文列明的 Copilot 操作边界修正，不包含并行资源平面改动。

新增 Java 网关路由已通过现有 backend 的重启编译加载。在资源重构开始前，真实 9050 → Java → Python 链路 GET 返回 200；两个新操作入口的空请求均为 422，只读操作请求均为 409，SSE 无效模型请求仍为 200 + error，未创建真实任务、持久化真实操作方案或调用付费模型。这些结果证明当时路由可达，不替代重构完成后的服务和人工执行验收。

#### 本轮测试结果

| 范围 | 结果 | 说明 |
| --- | --- | --- |
| AgentOS 全量 | 913 passed / 3 failed，295.37 秒 | 最后完整运行保留已记录的 trace 同时间排序、schema 期望版本、旧 outbox fixture 三项失败；此前偶发 edge/cloud 进程超时单独复跑通过，最后全量也通过该案例 |
| 最终相关 Runtime 回归 | 89 passed，185.52 秒 | 并行资源改动发生后，在隔离快照覆盖最后的 Recovery/操作代码，包含 11 项新操作用例、完整 Planning Loop、既有单节点恢复和文档验收；全量之后新增的 settled-loop/链式下游重跑真实执行亦纳入此组 |
| 最后补充权限/暂停边界检查 | 2 passed，7.61 秒 | 最后明确 recover 仅用于 FAILED，拒绝把 Planner 暂停预览为可直接恢复的操作；普通补充要求唤醒和既有失败恢复仍通过 |
| 应用层 API、协调器、组装 | 65 passed，43.85 秒 | 包含新预览/确认接口、owner 隔离、successor 进入原协调器的执行链 |
| 前端全量 | 602 passed / 92 files，136.36 秒 | 包含选节点→预览→确认→新 Run 导航和只读门禁；受影响三组专项 47 passed |
| Java 控制器 | 9 tests，0 failures/errors | Review 6、Event 3；新操作转发保留目标 ID、revision、状态和回执 |
| 标准 build:web | 通过，Vite 24.02 秒 | 包含 TypeScript 检查；生成器顺带删除的既有 RoleManagementPanel 类型声明已恢复 |
| 源码检查 | Ruff / 受影响 diff --check 通过 | RuntimeInspector 原哈希不变；未处理其他并行模块的改动 |

最后全量先于 settled-loop 最终收敛，后者由完整相关 Runtime 回归覆盖；不是“整个当前工作树全绿”。日志为 operations-agentos-full-final.txt、operations-isolated-runtime-final.txt、operations-final-permission.txt、operations-app-full.txt、operations-frontend-full.txt、operations-java.txt、operations-build.txt 及 operations-live-*.txt。下一阶段优先处理循环重入的 Memory/Attempt/Checkpoint 身份一致性，再扩展其他控制类型的断点语义与终态任务带新要求的语义续作。
