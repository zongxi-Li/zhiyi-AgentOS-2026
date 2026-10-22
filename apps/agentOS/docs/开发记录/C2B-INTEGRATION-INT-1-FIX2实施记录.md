# C2B-INTEGRATION-INT-1-FIX2 实施记录

日期：2026-10-22。范围仅为冻结门禁基线完整性与 Schema 预检证据关联；不改变执行授权合同，不进入 INT-2。

## 1. 入场与保护范围

- 本地 `master` / HEAD：`25bc3b956310737ebcb224c37dababd659bedd2c`。本轮用 `git ls-remote https://github.com/zongxi-Li/zhiyi-AgentOS-2026.git refs/heads/master` 确认 GitHub 同 SHA，`HEAD...origin/master` 为 `0 0`。暂存区为空。
- 入场 AgentOS src/tests 为 451 个 Python 文件，聚合 SHA-256：`b89e62e26d26c3eca968fd2eeaa9af87d475b4f0f90a947e4be58668f287bbc1`。此前提交和测试均只作历史依据，不冒充本轮验证。
- 操作中发现前端并行工作：`apps/frontend/components.d.ts`、`apps/frontend/src/components/agentos/AcgTopologyGraph.vue`，以及未跟踪的 `apps/frontend/src/utils/acgExecutionLayout.ts` / `acgExecutionLayout.spec.ts`；diff 检查还出现自动导入声明的换行提示。均保留，不编辑、不暂存、不纳入本轮范围。README、EX-00、图片及其他用户工作均未清理或覆盖。
- 原基线 `scripts/freeze_gate_baselines/c2b-int1-entry.json` 未修改：原始字节 SHA-256 为 `54ccc02a3d0ba550fffff8dd23f259460977ae0a75f3d8eea4d7c1848ce1a591`，445 项 manifest 聚合为 `cb5809b8a2e29278d39d6ab70c6bd1567da7073148195201d013f1105f9a2c47`。

## 2. 失败反例与根因

### 门禁基线

`changed_python_paths()` 原先在基线不存在时回退 Git HEAD；干净工作区可能因此返回无变化成功。已存在的 JSON 未认证其固定内容，即便重算 aggregate 也可以替换比较对象。外部 API/CLI 只比较 HEAD，遗漏已提交变化；门禁自身也不在源码集合内。

修复前命令（pytest 的工作目录均为 `apps/agentOS`）：

```text
python -m pytest -q tests/storage/test_freeze_gate_integrity.py -k "untrusted_baseline or missing_default or committed_external" --tb=short
```

8 failed / 19 deselected，pytest 3.74 秒、启动器墙钟 7.051 秒。四项是基线缺失/篡改/aggregate/替换未拒绝；默认缺失入口抛未结构化异常；三项为固定外部比较能力缺失。后者是新增接口尚不存在的红灯，不把 KeyError 本身夸大为生产数据损坏。原始记录：仓库 `tmp/c1_audit/int1-fix2-baseline-before.{log,json}`。

### Run—Permit 语义关联

`_inspect_evidence()` 原先只确认 Run 引用的 permitId 存在。独立 Permit/Handoff checksum 校验不足以证明该 Permit 属于这个 Run/Mission/正式 Head。

新增 `two_permits` 夹具使用同一 Runtime、两个 Mission 和同一 Workflow SQLite，分别经过真实接受、Initial 物化、Activation、Handoff 和 ISSUED Permit。两条图身份不同。仅损坏注入使用 SQL，真实成功事实均由既有 Authority 产生。

稳定复现命令：

```text
python -m pytest -q tests/storage/test_c2_schema_integrity.py -k "semantic_identity or two_valid" --tb=short
```

修复前 6 failed / 1 passed / 11 deselected，pytest 28.91 秒、墙钟 30.586 秒。六个失败均为预期 `INVALID`、实际 `READY`：完整交叉 Permit 投影、Permit Mission 篡改、Permit Graph 篡改、投影 GraphVersion/Activation/Handoff 篡改。Mission/Graph 两项重新计算合法 checksum，并断言正式 typed Store 仍能读出记录，证明拒绝必须来自身份关联而非 checksum 失败。原始证据：`tmp/c1_audit/int1-fix2-identity-reproduced.{log,json}`。

构造夹具的首轮曾因 `execution_permit_projection` 导入位置错误而失败，已修正为正式 contract 导出；`int1-fix2-identity-before` 属于夹具失败且测试期间文件变化，不能用作生产缺陷或最终快照证据。以上稳定复现才是修复依据。

## 3. 实际修复

| 文件 | 行为 |
| --- | --- |
| `scripts/freeze_gate.py` | `load_baseline()` 认证固定文件 SHA、数量及 aggregate；缺失/损坏/替换返回 `BLOCKED_BASELINE_INTEGRITY`，在测试发现及启动前终止。取消 HEAD 回退。运行后复查基线，变化返回 `INCOMPLETE_BASELINE_CHANGED`。 |
| 同上 | API、CLI、门禁自身与原 INT-1 入口的固定内容比较，不随当前 HEAD 前移；脚本变化映射到完整性测试，缺失外部源码阻断；纳入运行前后源码保护和报告。预算仍为 300 秒。 |
| `src/support/stores/c2_schema_upgrade.py` | 在只读 Workflow 事务内读取完整 Run，核对行索引身份，复用 `validate_activation_run()` 验证 Run→Head→Activation→Materialization→Permit→Handoff 和完整 Permit 投影；错误包含 Run/Permit 定位。另补 Handoff candidateGraph.graphId 与 Permit.graphId 对应检查。 |
| `tests/storage/test_freeze_gate_integrity.py` | 基线篡改/删除/替换、默认入口拒绝、三个外部源码已提交变化、门禁单独变化及测试运行期间基线变化的永久反例；既有超时和失败断言保留。临时真实 Git 仓库验证 `git diff HEAD` 为空仍能发现固定基线差异。 |
| `tests/storage/test_c2_schema_integrity.py` | 两条真实 Permit 链的身份错配与重算 checksum 反例；拒绝升级后 Workflow/Checkpoint/Identity 三库完整 SQL dump 相同；有效双 Run 正例、合法 Native 执行后 Checkpoint 推进正例。 |

没有修改 `validate_activation_run`、Permit Authority、Head、Handoff 或 Runtime 的生产授权语义。预检调用的是既有只读校验函数，不建立第二套 Authority。无依赖事实的中断安装与合法 STAGING 窗口仍由原测试验证可恢复。

外部比较锚点仍是 `09860f8c88c4b8d40cac2c80ca836f0bfa5a2c35`。API 原 Windows 工作区 CRLF 字节 SHA 为 `b78ffdd8d0b1c004f9befdd63c7372070cf9a733c244f86591328897791ccc21`（原 Git LF blob 为 `1b3d89fe60f77c9ca1e61985d6ada70e2651836b6b4157ca1d22321d28f9275d`）；门禁原 LF 字节 SHA 为 `06816f400a6d5a6143ead0f9d32af1d70a2715202cbbcd7223e05df1469d0637`；升级 CLI 当时不存在。只补这些外部锚点，未重新生成原 manifest。

## 4. 测试与最终快照

环境：Windows 11 build 26100，Python 3.14.5，默认计时环境；未请求 1ms，未修改 deadline、预算、marker 或既有断言。所有数据库实验均为 pytest 临时 SQLite，不连接真实业务库。

开发反馈：

1. 修复主体后，`python -m pytest -q tests/storage/test_c2_schema_upgrade.py tests/storage/test_c2_schema_integrity.py tests/storage/test_freeze_gate_integrity.py --tb=short`：82 passed，pytest 51.01 秒、墙钟 53.220 秒，退出 0。当时 src/tests 摘要 `c87bcb005b0012b86f3c08b8096e3865754d3984deff1d7ade2ba106c21bf895`，是增加最后两项保护测试之前的中间快照。
2. 最终补充测试后，精确运行 `test_gate_never_reports_success_for_changed_sources_failed_preflight_or_timeout` 及 `test_preflight_accepts_legal_native_checkpoint_advancement`：5 passed，pytest 6.37 秒、墙钟 8.636 秒，退出 0。使用下述最终快照。
3. `python scripts/freeze_gate.py --dry-run`：退出 0，0.259 秒；26 个固定基线差异路径映射至 16 个测试文件；未覆盖源码、缺失测试、缺失外部源码均为空，diff check 为 0。原始结果 `tmp/int1-fix2-dry-run.json`。

最终正式门禁（只执行一次）：

```text
python scripts/freeze_gate.py
```

- `PASSED`，退出 0；230 passed，0 failed / errors / skipped / deselected，2 项既有弃用警告（Starlette TestClient/httpx、Pydantic class-based config）。
- pytest 153.21 秒；门禁完整墙钟 **160.616 秒**（外层启动器 160.794 秒），未超 300 秒。
- 历史测试耗时已知项总和为 75.510 秒，未知项列于报告，没有以未知耗时当作零成本承诺；实际超时保护保持原样。
- 16 个测试文件的 230 个唯一 node ID 全部完成；包括本轮新增 17 项反例/兼容性测试、全部 Schema 升级/完整性用例、既有 Permit、资源、Scheduler、流式调用、Identity Schema、C1 纵向恢复与交付回归。未覆盖源码、缺失测试、缺失外部源码均为空。
- 最终源码与外部源码前后相同；基线运行前后均认证通过。最终快照与下面摘要相同。`git diff --check` 通过（退出 0，只有 Windows LF/CRLF 提示）。
- 原始日志：`tmp/freeze_gate/20261022T115641Z.log`；门禁完整 JSON：`tmp/freeze_gate/20261022T115641Z.json`；外层 stdout：`tmp/int1-fix2-freeze-console.json`。这些 tmp 证据未暂存。

本轮不运行全量 pytest，不用此前全量结果代替本次验证。开发期中间快照的 82 项结果单独列出；最终门禁重新覆盖这三份测试文件及新增正例，避免将中间结果充当最终结果。

最终 src/tests：451 个 Python 文件，SHA-256：

```text
49a91f777b2d5cc520b0374ddedc26f5b385e3d8ad8bbbdc7db3816a319c913a
```

算法与既有门禁一致：每个 src/tests `.py` 原始字节计算 SHA-256，按仓库相对路径排序，组成无结尾换行的 `path digest` 行序列，再对 UTF-8 序列计算 SHA-256。完整逐文件 manifest：`tmp/int1-fix2-final-snapshot.json`。该文件和原始日志在本地 tmp，不作为源码提交。

最终外部源码 SHA-256：

| 路径 | SHA-256 |
| --- | --- |
| `scripts/freeze_gate.py` | `4405b0b923d828574712e867fa1c40b6a6e90103e362f23889986940b277015e` |
| `scripts/upgrade_agentos_c2_schema.py`（本轮未改） | `72b55f01379900c658391cb110d142fa7de126f4d9dbea0c3d076b82c3cb08cd` |
| `apps/agent/app/api/agentos_v2.py`（本轮未改） | `2127e6e7065db1ca7179b6c5a805bb4c73d2868d5adba12431c2d76d3abe14e3` |

## 5. 限制与状态

- 预检是运维维护窗口下的只读一致性验证；Workflow 内关联使用同一读事务，后续分库读取和 DDL 仍无联合原子性，须停止并发业务写入。既有跨库限制未消失。
- Schema 预检不等于实时执行授权、所有历史 Receipt 的真实性证明或通用恶意数据库取证；本次验证的是被 Run 采用的 Permit 链和已有 Handoff/Checkpoint 依赖完整性。没有修复或补造丢失证据。
- 原始字节固定基线采用保守策略，换行或格式变化也会阻断/触发回归。`--baseline` 只允许定位同一已验收文件的精确副本，不允许任意移动验收基线。
- `apps/agent/tests/test_agentos_v2_api.py` 不在 AgentOS 门禁直接测试目录，本轮未单独执行；API 差异触发的是既有 C1 纵向与交付测试。全量、生产装配、部署及业务库升级均未验证或执行。
- 最终状态只标记 SELF-TESTED，等待独立复验；不自行声明 ACCEPT。
