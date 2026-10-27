# INT-2E REMEDIATION-3 最终独立复验

日期：2026-10-27（Asia/Shanghai）。**最终复验：BLOCKED / INCOMPLETE_EXECUTION_EVIDENCE**。停止后续验收，不重新运行门禁，不修改预算或缓存，不宣布 V1 冻结。

## 入场与源码

实际 HEAD：`53eb030023dd2f2c631a222df3786dfd18fc1fa5`，暂存区为空。保留工作区脚本/测试和上一轮三份未跟踪审查记录，没有覆盖任何入场文件。

实际源码包含 remediation-3：发布后在既有锁内保存剖面原始字节 SHA-256，并将 `profileSha256` 写入 receipt；reader 单次读取原始 bytes、匹配摘要后才解析，继续核验 publication/report/receipt 及完整性重算。不是以 HEAD 替代工作区实现。

入场保护摘要：

| 文件 | SHA-256（最终核验仍一致） |
| --- | --- |
| scripts/freeze_gate.py | `fb834c0ad42dcfa9c51e1a1dc0ad879f13d4de1493988ab85e6523cd01e96484` |
| scripts/freeze_gate_pytest_runner.py | `03bce25689a960b85eec4e718922f66060648036ae2b171d36b8a0a3851e39f6` |
| apps/agentOS/tests/storage/test_freeze_gate_integrity.py | `0b73609e2d6dc8d1729628ca0d3e725aad69b0811112a5aa852b86548101d5c7` |
| scripts/freeze_gate_baselines/c2b-int1-entry.json | `54ccc02a3d0ba550fffff8dd23f259460977ae0a75f3d8eea4d7c1848ce1a591` |
| docs\audits\INT-2E-ESTIMATOR-FIX-REVIEW-REMEDIATION-2.md | `b5f2cc574428ca03d9bef2fb0cad23e5076877e58a3efe66d1d4aee4e9d50631` |
| docs\audits\INT-2E-ESTIMATOR-FIX-REVIEW-REMEDIATION-3.md | `246b7ae968abbc15d085fcdf33b529f3c70a9b7b795a8aef73131cb250dd6346` |
| docs\audits\INT-2E-ESTIMATOR-FIX-REVIEW-REMEDIATION.md | `053ee12ccdc329d65c73effb3ae4c444eb7344c1686669281c2f2c55fe3985e9` |

## 定向完整性测试：通过

cwd：`C:\Users\LZX\Desktop\kinlin_ai`。

```powershell
python -m pytest apps/agentOS/tests/storage/test_freeze_gate_integrity.py -q --disable-warnings
```

实际结果：**110 passed，18.01 秒，真实退出码 0**。包装进程墙钟 **20.016 秒**，退出码来自 `subprocess.run().returncode`，未使用管道末尾命令状态。完整 stdout/stderr 保存在 `targeted.log`，argv/cwd/退出码/墙钟在 `targeted.json`。

覆盖并通过：合法回执、原始字节篡改、自洽 process/observation 篡改、publication 修改、错误关联、缺失/损坏回执、同一读取快照 TOCTOU、预算切点及恢复失败等永久回归。测试前后完整源码快照一致。

## 正式冻结门禁：执行证据不完整

只有定向测试 exit 0 且源码未漂移之后，才启动一次：

```powershell
python scripts/freeze_gate.py
```

没有增加参数、改变环境变量、清缓存或删减节点。与 HEAD 的 AST 对照证明 300 秒常量、固定 baseline SHA/aggregate/commit、测试映射与 external baseline 不变（`policy-check.json`）。

本次 artifact ID：`20261026T160232Z-d777666d5577480d95f97a487a053c1c`。文件名使用 UTC，对应上海时间 2026-10-27 00:02:32。

- manifest 已生成，566 节点，566 个唯一身份；SHA-256 为 `a863a6369314a23a476e8c30a7b68195547b4093d09a792239d5d0a56fe0ee7e`。
- 原始 child 日志仅有部分进度（129 字节），没有 pytest 最终汇总；不能由进度字符推算已完成节点及身份。
- 用户要求继续时，发现 Python 进程已不存在，原会话读取返回 `Unknown process id 87871`。
- 没有本次正式 `.json` 报告、`.observation.json`、wrapper 的 `formal.json` 完成记录或新完整剖面/receipt。外层 `formal.log` 为空是父门禁未输出最终报告，不代表节点通过。
- **真实门禁退出码与完整墙钟无法恢复，均记为 null/UNKNOWN。** 没有证据判定具体退出原因，更不能称为 exit 0 或 300 秒超时。后续只读命令 exit 0 不代表门禁 exit 0。

按照“执行证据不完整立即停止”的合同，不另起门禁，不重跑测试，不修复源码，不通过预算或缓存操作制造通过。终止根因未确定；本报告不把无证据的环境中断归因写成已确认事实。

## 最终七项核验

| 条件 | 结论 | 证据 |
| --- | --- | --- |
| 正式报告 PASSED | 未满足 | 本次报告缺失 |
| 门禁 exit 0 且原 300 秒内完成 | 未证实 | 退出码/完整墙钟记录缺失，不能推断 |
| 选集、manifest、实际执行身份一致 | 部分可证 | manifest 566 个唯一节点；无完整观测，实际完成数/身份不可核验 |
| 源码快照一致 | 通过 | 门禁前与最终只读快照相同，见下文 |
| 新 receipt 的 profileSha256 匹配 | 不可验收 | 本次未生成完整剖面和 receipt；定向测试通过不能替代正式产物 |
| 旧缓存/失败证据保留 | 通过 | 入场 81 份既有门禁文件全部仍存在且 SHA 一致 |
| git diff --check HEAD | 通过 | 最终真实 exit 0，见 final-audit.json |

AgentOS source aggregate 前后均为 `be8ef516c23743eccb6cc6093eb766323e940eb2747a0e46c49ae5ccb487bb65`；external snapshot 也完全一致。原历史耗时缓存 SHA-256：`c02e3af5018b675ef6bb68fb60c0370aa1e21bd5017225afa33d0cb5a5970519`；旧失败报告 SHA-256：`bb49c8114a58093824a7e1089ba4a6f870d9fc316cd8f18bff1394271a715fbd`。全部与入场一致。

本次新 partial log SHA-256：`82cc591357df6b3c6fdaa6cad3101d3d6e51704ac3a526d72348d51d79f244aa`。新文件仅日志和 manifest，没有覆盖旧 artifact。

## 独立复验材料

本机目录：`.tmp-tests/int2e-final-recheck-20261027-425eedb2/`。

- `entry.json`：HEAD、工作区/暂存区、保护文件摘要、81 份旧证据逐文件 SHA。
- `source-entry.json`、`targeted-source-before/after.json`、`formal-source-before.json`、`source-final.json`：完整源码快照。
- `targeted.log/.json`：定向完整输出、真实退出码和墙钟。
- `formal.log`：原父进程输出（空）；没有虚构其完成记录。
- `gate-partial.log`、`gate-selected.nodeids`：原日志和节点清单的字节一致副本，原文件仍保留于 tmp/freeze_gate。
- `manifest-discovery.json`、`policy-check.json`、`formal-incomplete.json`、`final-audit.json`：节点数/摘要、预算映射、无法恢复的退出码及最终核验记录。

所有临时材料留忽略目录，不提交日志、数据库、机器缓存或凭据。当前新增的仅是本复验报告；原未提交源码和文档均保留。

## 裁决与剩余限制

定向源码完整性自测通过；**正式冻结复验 BLOCKED**，原因是本次运行缺少最终执行与退出证据，而非已经证明某项业务测试失败。不得用历史通过结果、部分进度或后续只读命令的退出码替代。

V1 仍保持 BLOCKED；正式 300 秒完整门禁和新 receipt 的实际产物验收尚未完成。此前回执规模性能、生产环境及线性化边界等限制不因本次定向通过而消失。若后续授权重做正式复验，应另建新 artifact 并保留本次不完整证据，不在本任务中自动重试。

未提交、未推送、未部署，未修改生产数据库、compose 或生产开关。证据提交给用户供最终架构裁决，不自行宣布 V1 冻结。
