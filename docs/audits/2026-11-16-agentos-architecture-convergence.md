# AgentOS 分层迁移与验证记录

日期：2026-11-16。分支：`refactor/agentos-architecture-20261115`。

## 提交边界

- `faf7ba8a`：迁移前工作区快照，保留用户此前的目录和设计改动。
- `1c63269b`：实际目录、实现与调用路径迁移的检查点。
- 后续修正：规划包编译职责拆分、事件发布器注入、重复关闭保护、测试包身份及冻结门禁路径同步。

本次只提交当前分支，不执行 push。

## 实现归属与去重

| 范围 | 已落地的归属与约束 |
| --- | --- |
| components | 固定 mission、planner、resource、scheduler、executor、communicator、memory、auditor、recovery、attachments、environment、evolution、safe，共 13 个。 |
| runtime | composition 装配，orchestration 协调用例与提交，projections 提供读视图，events 分发进度，compatibility 保留转发入口。根目录仅保留公开入口和运行时门面。 |
| planner / executor | 蓝图到不可变执行包的 12 个编译方法归 `planner/package_compiler.py`；executor 保留 2 个执行图适配方法并继承原公开入口。全部 14 个方法与拆分前 AST 一致，实现指纹同时覆盖两份源码。 |
| scheduler / resource | 依赖就绪选择只有一个算法实现，executor 委派 scheduler；资源评分、绑定与容量租约继续归 resource。 |
| adapters / Agent | 外部接入分 model、agent、tool、retrieval、transport；原 Agent 注册和协议归 adapters，实例池和供给归 resource。 |
| contracts / domain / support | ACG 合同归 contracts，规划校验归 planner，纯图不变量归 domain；support/acg 只转发。相同完整字段摘要共用 stable_digest，省略默认值的 stable_checksum 保持原有语义。 |
| environment | content、Hands、compact 归同一部件；两个 TypeScript 项目的依赖、构建和进程边界独立保留。 |
| safe / model_partition | 不新增第 14 个部件。分区 DTO 归 contracts，分区验证入口归 safe/integration；验证只检查层区间与张量边界，不伪装成已可用的通用模型执行器。 |
| resource/catalog | 原 marketplace 归资源目录；安装任务、资格和健康检查保留。关闭操作具有幂等保护，避免重复访问已关闭的任务数据库。 |
| storage | 共享 Identity / New ACG 仓储与历史 WorkflowStore schema 保持隔离，不以目录统一为理由合并数据库。 |

事件发布器由 runtime 装配后注入 executor 和 Agent 上下文，部件不再导入顶层 runtime 的全局 broker。修正了上下文参数别名造成的发布器丢失；流事件和执行结果提交仍分别验证。

测试位于仓库根的 `TEST/tests/`，使用原生包标记和 `TEST.tests...` 导入，避免 Windows spawn 生成不可导入的模块名。移除把测试子目录当成业务模块根的旧路径注入。冻结门禁继续使用原始接受基线及摘要，只转换迁移后的实际源码和测试位置。

## 验证口径

环境为 Windows、Python 3.13.3、pytest 8.4.2、Node 24.11.1。系统 Node 22 不满足 Hands/compact 的 Node >=24.9 要求，因此使用本地隔离的 Node 24。Python 缺失依赖从已有真实 wheel 缓存恢复到临时依赖目录，没有伪造 SDK 或修改系统 Python。

分批回归存在重叠，不能把各批次数字相加当成独立测试总数。最终结果以完成的命令和其退出状态为准；中断的诊断试跑不计作通过。

| 验证范围 | 完成结果 |
| --- | --- |
| 架构、scheduler、executor、编译合同、初始规划来源、进程退出恢复、许可与恢复、storage、catalog、应用生命周期 | **538 passed**；其中包含冻结门禁自身的 100 项测试。日志：`tmp/agentos-integration-verified.log`。 |
| 全 adapters | **406 passed**，含流事件先于提交及重放不重复请求的回归。日志：`tmp/agentos-adapters-final.log`。 |
| safe、model_partition、domain、运行时导入、事件/展示、Agent 注册、执行提取、应用设置、取消互斥、资源绑定 | **470 passed**。日志：`tmp/agentos-boundaries-final.log`。 |
| compact | 类型检查通过；Node 24 测试 **51 passed**。 |
| Hands | 类型检查通过；Node 24 执行验收 **91 passed / 11 failed**，不是全绿。日志：`tmp/hands-node24-final-tests.log`。 |
| Python 语法 | `apps/agentOS/src` 与 `TEST/tests` 共 **716 个文件** AST 解析通过。 |
| 完整测试树收集 | **3078 tests collected / 3 errors**，均因 `examples.contract_review` 缺失。日志：`tmp/agentos-collection-verified.log`。 |

最后一组初次执行时，隔离 SDK 带入的 Starlette 1.10.0 与系统 FastAPI 0.116.1 声明的 `starlette>=0.40,<0.48` 不兼容，导致 5 个 HTTP 初始化失败。根据本地 wheel 元数据，在独立临时目录使用 Starlette 0.47.3 与 sse-starlette 3.0.2 后重跑，得到上述 470 项通过结果。没有修改系统 Python 或项目的业务代码来规避该依赖冲突。

本机复现最终 HTTP 批次使用以下临时依赖路径；普通开发环境应按项目依赖安装一组相互兼容的版本：

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'tmp/agentos-http313') + ';' + (Join-Path (Get-Location) 'tmp/agentos-sdk313')
```

## 全套验收的已知限制

- 仓库缺少 `examples.contract_review`，影响生产装配、合同审查交付和垂直切片相关用例；迁移前快照中也未包含该实现。本次没有制作替代示例来掩盖缺失。
- 部分旧 runtime 断言只允许早期 trace 字段，或要求自动重试状态未知的外部操作；现有实现已经增加读取元数据和显式对账保护。本次没有删除安全守卫来适配这些旧断言。
- Hands 的 Windows 沙箱执行测试受当前权限配置影响，涉及 ACL、受限令牌、junction 和子进程隔离。类型检查与隔离能力验收分别记录；未放宽隔离边界以获得绿色测试。
- `apps/agent/app/services/federatedlearning.py` 和 `globalmodelmanager.py` 仍引用历史 `safe.encryptionservice`。该参数聚合链与当前 safe 拆分推理不是同一实现，依赖在迁移前已缺失；未恢复占位加密服务。
- “当前最大可执行子图”仍是分阶段的依赖就绪选择和资源准入，不代表已实现统一考虑容量、权限、预算的全局最优求解器。

## 复现方式

先安装项目声明的 Python 依赖。在仓库根运行并显式指定测试目录，统一测试节点根目录：

```powershell
python -m pytest --rootdir=. -c apps/agentOS/pytest.ini TEST/tests/architecture TEST/tests/components/scheduler -q
python -m pytest --rootdir=. -c apps/agentOS/pytest.ini TEST/tests/adapters -q
python -m pytest --rootdir=. -c apps/agentOS/pytest.ini TEST/tests/storage TEST/tests/components/marketplace TEST/tests/runtime/test_app_lifespan.py -q
python -m pytest --rootdir=. -c apps/agentOS/pytest.ini TEST/tests/safe TEST/tests/components/test_model_partition.py -q
python -m pytest --rootdir=. -c apps/agentOS/pytest.ini TEST/tests --collect-only -q
```

Hands 与 compact 分别进入 `apps/agentOS/src/components/environment/hands/`、`compact/`，使用满足版本要求的 Node 执行各自 `package.json` 声明的 typecheck 和 test。不要从仓库根仅运行带应用配置的裸 pytest，以免将其他工作区或临时依赖包的测试混入验收。

源码和调用关系以 [AgentOS README](../../apps/agentOS/README.md) 及 [当前实现梳理](../../apps/agentOS/docs/当前实现梳理.md) 为准；[实施计划](../superpowers/plans/2026-11-15-agentos-architecture-convergence.md) 保留任务逐项记录。
