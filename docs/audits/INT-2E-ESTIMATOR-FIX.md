# INT-2E-ESTIMATOR-FIX：完整运行剖面合同

2026-10-26。入场 HEAD 与 GitHub master 均为 `4886c51875c720411aa5bdaf05c1831b4be3b446`，工作区、暂存区干净。本次仅修复冻结门禁估算器及定向测试/文档，不修改 AgentOS 业务源码。

**估算器合同自测通过；V1 继续 BLOCKED。** 未运行完整 300 秒正式门禁，不把本次定向测试当作正式冻结通过。历史正式失败 `tmp/freeze_gate/20261026T021224Z.json`（498 节点、300.79 秒、INCOMPLETE_TIMEOUT）及原缓存保留。

## 合同与发布边界

- 预检只使用**同一源码摘要、同一 node manifest**最近一次成功发布的完整剖面；按这两个摘要的组合键保存，各键之间不混用。
- 源码摘要覆盖 AgentOS src/tests aggregate 与原 external source snapshot（含门禁和 launcher）；manifest 使用实际固定 LF 文件内容的 SHA-256。剖面内保留两个完整摘要、节点数量、collection/执行数量、完整节点耗时映射、三阶段原始观测、进程耗时及 invocationId。
- 原 launcher 的选集与长度有界命令不变。新增 pytest observer 记录真实 collection 及 setup/call/teardown 的全精度 duration/outcome。结束观测在 `pytest.main()` 返回后写出，绑定本次 invocationId 与启动时 manifest 摘要，不从四舍五入的终端 duration 表拼接完整性。
- v1 发布合同：父进程和 pytest session 均正常 exit 0；collection 与 manifest 完全一致且无重复；每个必要节点三阶段各一次、全部 passed、无 expected-failure 标记，耗时有限且非负。失败、跳过/不完整节点不冒充完整成功剖面；退出码为 0 但证据不完整也 fail-closed。
- 父进程在发布前复核原基线、源码摘要及 manifest；超时、启动失败、非零退出、部分执行、观测缺失/陈旧 invocation、源码或 manifest 漂移不发布新完整剖面，不覆盖此前完整记录。
- 同目录临时文件写入、flush/fsync 后 `os.replace` 原子发布；发布前再次检查原预算 deadline。缓存写入使用非阻塞 OS 锁，避免并发发布丢失 max；异常/进程退出由 OS 释放锁，不引入业务恢复状态机。Windows 使用固定长度组合摘要文件名及短临时名。
- 节点耗时 = 三阶段之和；完整节点总和用 `math.fsum`。预算估计取 `max(节点总和, 实际测试进程墙钟耗时)`，包含进程启动/collection 等开销，不声称是未来运行的最坏情况保证。
- 缺失、损坏或不匹配剖面明确报告 `duration_estimate.status=UNKNOWN`、`seconds=null` 和原因；所有节点均标为估计未知，不能用旧 last 拼接，也不能将未知当作 0。匹配完整剖面估计超过剩余预算时仍在启动前 BLOCKED。

旧 `test_durations.json` 不迁移成剖面。平铺 max、字典 max/last 及附加字段均保留；后续合法完整运行只单调更新 max，旧 last 为档案字段、不刷新也不参与估算。无法解析的旧文件拒绝覆盖。完整剖面单文件原子提交与历史 max 文件不是跨文件事务；历史记录即使先写成功，也不会被当成完整剖面使用。

**超时不代表下次必然被预检阻断。** 超时不更新完整剖面；下次有匹配且超预算的完整记录才预检阻断，没有匹配记录则 UNKNOWN，仍由原 300 秒硬执行控制。原 CLOSEOUT/RC 中“最近完整 last”及“超时后必然阻断”错误说明已更正。

## 永久回归与真实测试

仅执行（cwd `C:\Users\LZX\Desktop\kinlin_ai`）：

```powershell
python -m pytest apps/agentOS/tests/storage/test_freeze_gate_integrity.py -q --disable-warnings --maxfail=1
```

最终结果：**70 passed，10.94 秒，真实退出码 0**；包装进程 12.434 秒。原有测试函数全部保留。新增/加强覆盖：

| 情况 | 预期证据 |
| --- | --- |
| A/B 来自不同运行的 last | UNKNOWN，不构成完整剖面 |
| 部分节点/缺少阶段/重复/多余节点/collection 不符 | 拒绝，旧剖面不变 |
| 非有限/负耗时、跳过、过期 invocation、错误退出 | 拒绝 |
| 源码或 manifest 变化 | 缓存不匹配则 UNKNOWN；运行中漂移不覆盖旧剖面 |
| 超时、启动失败、执行失败、预算在发布前耗尽 | 不发布，不改旧完整剖面 |
| 全部阶段完整 | 精确求和，计入进程开销；已有匹配超预算剖面时不启动 pytest |
| 原子替换失败、发布 deadline 到期 | 旧文件保留、临时文件清理 |
| 并发写入与异常退出 | 锁拒绝竞争，异常后可重新取得 |
| 真实 launcher/父进程集成 | 临时目录中真实执行单节点 pytest，生成、校验、发布并复用完整剖面 |

真实进程集成只运行临时 fixture 的单节点选集，不运行实际完整冻结选择集，不连接业务数据库。其余故障注入均写入 pytest `tmp_path`，不修改真实缓存或历史失败报告。

中间失败如实保留：首轮 38 passed/1 failed（测试 fixture 的 CRLF manifest 与生产固定 LF 合同不符）；第二轮 40 passed/1 failed（Windows 缓存路径过长）；第三轮 40 passed/1 failed（测试将新增 observation JSON 误选为报告）。分别修正 fixture 写法、固定长度键/短临时名、报告筛选；未降低断言。之后 67、69 项阶段性通过，追加发布 deadline 回归后最终 70 项通过。

## 完整性与复验材料

原缓存前后 SHA-256 均为：

`c02e3af5018b675ef6bb68fb60c0370aa1e21bd5017225afa33d0cb5a5970519`

历史失败报告前后字节一致，其 SHA-256：

`bb49c8114a58093824a7e1089ba4a6f870d9fc316cd8f18bff1394271a715fbd`

最终测试前后下列三个文件的工作区原始字节摘要分别一致；按路径排序 JSON 再 SHA-256 的复合摘要均为 `8168d31f23b6743f6f35bdd3b4e68469d213ea3a65564bc98bc7a95a66432bc1`。

| 文件 | 最终测试前 = 后 SHA-256 |
| --- | --- |
| scripts/freeze_gate.py | 7371a5af60ec652a48ff02d0b83886a3c641e6988859a30d27d08e20bfda9256 |
| scripts/freeze_gate_pytest_runner.py | 03bce25689a960b85eec4e718922f66060648036ae2b171d36b8a0a3851e39f6 |
| apps/agentOS/tests/storage/test_freeze_gate_integrity.py | 1555814d0f9b35838cd9c99944cd61d85e01e5fa1fc0266458d5eb91c6ad4bf7 |

与 `4886c518` 的 AST 常量对照：`SOURCE_TEST_RULES`、`DEFAULT_BUDGET_SECONDS=300`、`BASELINE_SHA256`、`BASELINE_AGGREGATE`、`BASELINE_COMMIT`、`EXTERNAL_BASELINE` 全部未变；没有删除原测试函数，没有改固定基线 manifest 或缩减选择。

本机独立复验材料在忽略目录 `.tmp-tests/int2e-estimator-fix/`：`before/` 原缓存及失败报告副本、`invariants.json` 常量/缓存证据、`baseline-source.json` 入场 Git blob 摘要、`verification.json` 完整命令/cwd/退出码/前后源码及缓存摘要、`gate-tests-final.log` 原始输出和中间失败日志。入场 Git blob 与工作区原始字节采用不同口径，Windows 换行差异不混作源码漂移；tmp/cache/log 不入库。

## 交付判断

本轮关闭估算器完整剖面合同的已知 P2，自测通过，等待独立复验。**V1 仍 BLOCKED**：未重新运行正式完整门禁，不能改变既有失败裁决，也不据此允许完整独立部署验收入场。保留原生产边界和大 Artifact 等限制。

本地源码/测试和文档按职责提交；源码提交为 `9087071f894a8cabaf29e93ccc0d087bd515d686`（`fix(freeze-gate): 绑定并原子发布完整运行耗时剖面`），文档另作提交，本报告不嵌入自身提交 SHA。不推送、不部署，不修改业务执行合同、真实数据库、compose 或生产开关。
