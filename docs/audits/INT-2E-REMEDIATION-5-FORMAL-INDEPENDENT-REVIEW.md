# INT-2E-REMEDIATION-5 正式冻结门禁独立复验

结论：**BLOCKED**。原 300 秒预算耗尽，不能证明全部节点完成；本次没有发布完整剖面和回执。V1 不可据此冻结，等待最终架构裁决。

## 入场与源码

- HEAD `53eb030023dd2f2c631a222df3786dfd18fc1fa5`，暂存区为空；原有两份源码修改及四份未跟踪审查文档均保留。
- `scripts/freeze_gate.py` SHA-256 `fb834c0ad42dcfa9c51e1a1dc0ad879f13d4de1493988ab85e6523cd01e96484`；`scripts/freeze_gate_pytest_runner.py` `03bce25689a960b85eec4e718922f66060648036ae2b171d36b8a0a3851e39f6`；完整性测试文件 `0b73609e2d6dc8d1729628ca0d3e725aad69b0811112a5aa852b86548101d5c7`。均与先前 110 项测试的结束快照一致，本轮未重复定向测试。
- 运行前后 `source_snapshot()` 和 `external_snapshot()` 内容相同；合并快照文件 SHA-256 均为 `60d18a4587319700aa98a9c439933209cdcd568a5206a0e533408d41c60129a8`。门禁源码聚合摘要为 `be8ef516c23743eccb6cc6093eb766323e940eb2747a0e46c49ae5ccb487bb65`。
- 执行前 Windows 报告 AC Online、充电中；包装进程临时请求阻止休眠，退出时恢复线程执行状态，未修改持久电源计划。

## 执行结果

- 仓库根目录原样执行 `python scripts/freeze_gate.py` 一次。外层采集器直接等待子进程，合并保存 stdout/stderr；真实退出码 **1**，完整墙钟 **300.5700242 秒**。
- 2026-10-27 16:14:15 至 16:19:15（UTC+8）；报告 `elapsed_seconds=300.361791`、`budget_seconds=300`、`timed_out=true`、`status=INCOMPLETE_GATE_BUDGET_EXCEEDED`、`pytest_exit_code=1`。
- artifact ID `20261027T081415Z-bedef045933c477b87117956bfa38531`。manifest 含 566 个唯一节点，与报告的 566 个收集节点按顺序一致，SHA-256 `a863a6369314a23a476e8c30a7b68195547b4093d09a792239d5d0a56fe0ee7e`。
- pytest 日志有 535 个进度点，但不能证明逐节点身份或完整通过。观测文件的 `collectedNodeIds` 和 `reports` 为空，`sessionExitCode` 和 `processExitCode` 均为 4，其 manifest 摘要也不同于正式 manifest，不能用于证明节点完成身份。
- `complete_profile_published=null`，`profile_publication_confirmed=false`；报告列出的 receipt 路径不存在，无法核验新回执的 `profileSha256`。

## 证据与保护

- 采集目录 `.tmp-tests/int2e-remediation-5-be0d9a9ce2144477bcb60246a26ed702/` 包含合并输出、真实退出码和墙钟、源码前后快照、Git 入场状态、历史文件清单及缓存原始副本。
- 正式报告 `tmp/freeze_gate/20261027T081415Z-bedef045933c477b87117956bfa38531.json` SHA-256 `5456130537fc790aaaf045144d452516b7dbf7148de4902b0d388a875ad020cb`。
- 同名 `.log` SHA-256 `a54df4ad4187f966db9cbf14c69747942ecd7ddc27e915925e7364e9e910a425`；同名 `.nodeids` 摘要见上；同名 `.observation.json` SHA-256 `832fc698bc4684706d89d29dc54452f01f32ed5bb52af45e4bdabf2f75669830`。
- 外层 `gate-stdout-stderr.log` SHA-256 `02c8b36c1765baeb867a91d8532797186e863bc5c73f2c617583ead816920cfb`；`exit.json` SHA-256 `b584b038db7595ca7369338f65374ed4ab2cda9129b1b293627ed0d1c3278f93`。
- 入场清点的 121 个历史文件均存在且摘要不变。历史 `test_durations.json` 前后 SHA-256 均为 `c02e3af5018b675ef6bb68fb60c0370aa1e21bd5017225afa33d0cb5a5970519`。
- `git diff --check HEAD` 退出码 0，仅提示既有修改文件未来 Git 换行转换。未修改预算、基线、测试映射、生产代码或数据库；未提交、推送或部署。
