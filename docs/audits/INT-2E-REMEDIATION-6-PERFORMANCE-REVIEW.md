# INT-2E-REMEDIATION-6 正式门禁耗时收敛记录

结论：**BLOCKED**。已测量并隔离本地测试进程的代理初始化开销，修复嵌套 runner 测试覆盖外层观测文件的问题；原 566 节点正式门禁唯一一次复验仍超时，未取得完整执行证据。不得据此宣布 V1 冻结。

## 入场及现场保护

HEAD 为 `53eb030023dd2f2c631a222df3786dfd18fc1fa5`，暂存区为空。入场已有 `scripts/freeze_gate.py`、完整性测试文件的修改及五份未跟踪审查文档；全部保留。没有提交、推送、部署或修改生产数据库。

本次证据目录为 `.tmp-tests/int2e-remediation-6-cdd7de79da3e47c184b6ebb55dae6085/`。`history-before.json` 保存 116 个既有文件的路径、大小和 SHA-256，覆盖正式门禁目录、上一轮未完成证据和 remediation-5 采集目录。结束复核无文件缺失、无摘要改变，结果见 `verification.json`。未以当前报告覆盖旧报告。

历史 `tmp/freeze_gate/test_durations.json` 前后 SHA-256 均为 `c02e3af5018b675ef6bb68fb60c0370aa1e21bd5017225afa33d0cb5a5970519`。门禁源码和 runner 的字节均与入场一致，预算、固定基线和测试映射没有修改。

## 性能审计

`history-analysis.json` 区分历史 PASSED 报告和其他报告。历史 PASSED 不等于满足现行完整剖面合同：当前源码和 manifest 没有可用的匹配剖面，reader 返回 `UNKNOWN / NO_MATCHING_COMPLETE_PROFILE`。566 个节点中只有 210 个存在历史 max，另 356 个没有记录；不能把缺失当零，也不能把各次 max 相加称为同一次完整运行。

历史 max 按模块求和，仅用于选择诊断对象：Schema 完整性模块 113.52 秒、装配清理模块 63.51 秒、生产 Authority 装配模块 35.20 秒、Schema 升级模块 29.23 秒。不同历史运行的最大值混合，不能用这些数字推定本轮真实完成耗时或波动分布。

真实测量如下，原始命令、退出码和墙钟见对应 JSON 与日志：

| 诊断 | 继承环境 | 仅移除代理环境变量 | 证据 |
| --- | --- | --- | --- |
| 4 次空 HTTPX AsyncClient 构造和关闭，不发送请求 | 内部 25.4503 秒，进程墙钟 25.8527 秒 | 内部 3.7323 秒，进程墙钟 4.1251 秒 | `diagnostic-results.json` |
| 真实 transport 所有权和关闭测试，1 项通过 | 墙钟 21.1861 秒，退出码 0 | 墙钟 9.9369 秒，退出码 0 | `transport-comparison.json` 及两份 transport 日志 |
| 两个真实 Authority/Schema 热点测试，均开启同类 cProfile | 2 项通过，墙钟 43.6266 秒 | 2 项通过，墙钟 39.2988 秒 | `diagnostic-results.json`、`diagnostic-green-results.json` 和两份 profile |

两个热点测试的红侧 cProfile 显示：SQLite `execute` 11,973 次累计 9.162 秒，连接 2,803 次累计 1.750 秒，关闭 2,295 次累计 1.994 秒，提交 785 次累计 0.851 秒；生产装配重启测试 call 29.36 秒，Schema 测试 setup 7.57 秒。这些数据包含剖析器开销，不能直接外推整套门禁，也不能把两次剖析总耗时差全部归因于代理。没有发现足以安全删除正式持久化校验的证据，因此本轮未改事务、连接生命周期或 Runtime/Authority 共享方式。

本轮没有建立每个节点的多轮波动统计。重复 fixture 创建、CA 加载的独立成本、剩余节点完成成本仍未被完整分离测量；不将其写成已确认根因。

## 限定优化与永久反例

本地采集器只对测试子进程移除 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`；未改机器环境、生产配置、TLS 参数、CA 配置或业务执行代码。`tls-check.json` 记录默认 SSL context 仍为 `CERT_REQUIRED`、`check_hostname=true`，加载 119 个 CA。没有使用 `verify=False`。所测客户端构造基准不发送网络请求；它不构成真实 Provider/TLS 网络验收。

另外，源码审计确认现有 `test_manifest_runner_executes_exactly_the_listed_nodes_and_propagates_exit_status` 的失败分支未传独立 env，会继承外层正式门禁的观测路径。上一轮磁盘观测出现错误 manifest、空节点和 exit 4，与该路径存在明确关联风险。本轮用哨兵文件构造反例，旧调用在实际子进程结束后覆盖哨兵，产生 1 failed，退出码 1。

限定修复仅修改这个既有测试：失败子进程使用独立 observation 路径和 invocation；新增断言验证父观测原始字节不变、成功分支观测不变、失败分支的 invocation/manifest/退出码正确。保留全部既有断言，未增加或删除测试节点。`remediation-6-only.diff` 是相对本轮入场源码的精确差异。

## 定向验证

所有工作目录均为仓库根目录；完整命令参数保存在以下 JSON。运行器为 `run_focused.py`，不更改 pytest 节点或断言，只记录源码、退出码及墙钟，并隔离上述三个代理变量。

| 证据 | 实际 pytest 选择 | 数量与结果 | 真实退出码 | 外层墙钟 |
| --- | --- | --- | --- | --- |
| `isolation-red.json/.log` | 完整性模块中的 manifest runner 测试 | 1 failed，父观测文件被覆盖 | 1 | 6.0956 秒 |
| `isolation-green.json/.log` | `apps/agentOS/tests/storage/test_freeze_gate_integrity.py -q --disable-warnings --durations=10` | 110 passed | 0 | 15.7821 秒 |
| `diagnostic-results.json` | 装配重启与 Schema checkpoint 两个热点 | 2 passed | 0 | 43.6266 秒 |
| `diagnostic-green-results.json` | 同一两个热点 | 2 passed | 0 | 39.2988 秒 |
| `transport-comparison.json` | 装配清理模块的 owning-loop transport 测试 | 两次各 1 passed | 两次均 0 | 21.1861 / 9.9369 秒 |

这些是定向诊断结果，不能替代正式门禁。

## 选择集与正式门禁

`selection-check.json` 记录通过现有 resolver 和 collector 得到 566 个唯一节点，身份和顺序均与 remediation-5 manifest 一致，未覆盖源码为空。manifest SHA-256 为 `a863a6369314a23a476e8c30a7b68195547b4093d09a792239d5d0a56fe0ee7e`。固定基线文件 SHA-256 为 `54ccc02a3d0ba550fffff8dd23f259460977ae0a75f3d8eea4d7c1848ce1a591`。

AC 电源 Online；定向诊断进程结束后，仅执行一次原始命令 `python scripts/freeze_gate.py`，无附加参数。包装器临时阻止系统休眠并在退出后恢复线程状态，不修改持久电源计划。测试子进程按上述方式隔离代理变量。

- artifact ID：`20261027T083554Z-7b89cb194251490a98afea49c06b4edd`。
- 北京时间：2026-10-27 16:35:54 至 16:40:54。
- 真实门禁进程退出码：**1**；外层完整墙钟：**300.8095783 秒**。
- 正式报告：`INCOMPLETE_GATE_BUDGET_EXCEEDED`，内部 elapsed **300.640971 秒**，预算仍为 **300 秒**。
- 566 个收集节点与磁盘 manifest 按顺序一致；pytest 日志有 547 个进度点，但不能将其当作 547 个已证明的通过结果。
- 完整逐节点 observation 不存在；完整剖面未发布，publication receipt 不存在，无法核验新的 `profileSha256`。未伪造缺失产物。
- 正式门禁前后 source/external 快照字节相同，SHA-256 均为 `d32b30c7cf28bd9c4020b61005d695434318e238ab086abbb1eb1cf0535102c2`。

原始 stdout/stderr 合并保存在 `formal-stdout-stderr.log`，真实进程返回值在 `formal-exit.json`。外层采集器本身正常退出，不应将其退出码 0 当作门禁进程的退出码。

正式产物：`tmp/freeze_gate/20261027T083554Z-7b89cb194251490a98afea49c06b4edd` 的 `.json`、`.log`、`.nodeids`。报告 SHA-256 `761744b69098a3d39be16f6fd7d0af26be57efbfe28aa0d7b1ed90aa58159ca0`；pytest 日志 `b7aaba23e863e72e90ba2b659599f739b710a0b777eba659a639acfa2e4fca0e`。其他原始产物的摘要和大小见 `verification.json`。

## 源码与剩余边界

- `scripts/freeze_gate.py` 本轮前后均为 `fb834c0ad42dcfa9c51e1a1dc0ad879f13d4de1493988ab85e6523cd01e96484`。
- `scripts/freeze_gate_pytest_runner.py` 本轮前后均为 `03bce25689a960b85eec4e718922f66060648036ae2b171d36b8a0a3851e39f6`。
- 完整性测试入场为 `0b73609e2d6dc8d1729628ca0d3e725aad69b0811112a5aa852b86548101d5c7`，限定修复后为 `06d23d14368d2a35a197e9ff886142b8cb0d4167f29b525adb168a244f9a0f83`；最终定向测试及正式运行期间无漂移。
- `git diff --check HEAD` 返回 0，仅有既有文件未来 Git 换行转换提示。暂存区仍为空。

代理初始化是已确认、已限定优化的成本，不能据此宣称整体耗时问题已解决。SQLite 查询和反复权威校验是实测剩余成本，但安全的跨测试复用或减少重复读取需要进一步限定设计，当前没有实施或验收。完整节点耗时与波动仍未知，本轮不追加正式门禁碰运气。

最终裁决保持 **BLOCKED**。需要新的限定任务补充完整模块级诊断，才能判断剩余初始化是否可在不改变隔离性、持久化和恢复合同的前提下复用；本轮结束，等待独立架构裁决。
