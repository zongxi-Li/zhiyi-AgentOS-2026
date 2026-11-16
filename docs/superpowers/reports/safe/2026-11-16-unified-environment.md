# Safe 目录整合与 AgentOS 统一环境验收

日期：2026-11-16。功能分支：`feat/safe-unified-env-20261116`。

## 变更

- 基于架构分支 `1c63269b`，合入 `master` 的 `33476e08`：持久 SQLite nonce、认证线程池及相关测试保留原有行为；统一到 `components.safe`、根 `TEST/tests/safe`，修复新增多进程测试的源码定位。
- 八份环境配置收敛到 `apps/agentOS/requirements.txt`。基础运行、本地文档工具、Safe 模型、HTTP/TLS、绘图与测试一次安装；83 个直接/传递依赖均为精确版本和实际 wheel SHA256，无嵌套安装入口。
- 保留原有 Safe 模型/HTTP/绘图精确版本；原有范围依赖解析为明确版本，其中 `pytest==8.3.5` 与 `pytest-asyncio==1.3.0` 已联合验证。
- 三个旧 Safe 锁按本机原始字节归档至 [历史依赖证据](dependencies/2026-11-15/README.md)，历史报告、测量数据及其哈希不修改。新的 HTTPS 报告使用 `dependency_file` / `dependencies_sha256` 标识统一配置；绘图继续读取历史报告。
- 更新安装说明、测试缺依赖提示、工具启动错误和评估脚本的配置引用。SQLite 文档明确：能检测时钟回拨，不能仅靠文件内状态检测合法备份回滚；后者需要轮换凭据或外部可信状态。

## 验证结果

参考平台为 Windows x64 / CPython 3.10.11 / CPU。从全新 venv 使用
`--no-index --find-links ... --require-hashes` 安装全部 83 个下载 wheel，安装退出码为 0。
统一配置 SHA256 为 `5e4f4f1e82d821deeeb343c7a9e4fd884a9afe47bcc50df125d122a2f0b6a56f`。

| 检查 | 结果 |
| --- | --- |
| 下载 wheel 与统一清单的版本/实际哈希/传递闭包核查 | 83 项一致，无缺项和版本冲突 |
| 全新环境 `pip check` | No broken requirements found |
| 全部直接依赖导入 | 成功，Torch `2.11.0+cpu` |
| 迁移后的 Safe + model_partition，原环境基线 | 457 passed |
| 新环境 Safe + model_partition + 真实本地文档工具/目录安装测试 | 476 passed |
| 新环境数据转换脚本 | 18 项通过 |
| 新环境独立 suffix 进程真实 HTTPS 回环 | 2 条合成输入 × 2 轮 × 最多 4 token；4/4 序列、16/16 token 一致 |
| 回环资源清理 | 后段 KV 创建 6、释放 6、活跃 0；前段 KV 清空 |
| 回环认证与协议负例 | 回执查询、业务幂等、重放拒绝、正文篡改拒绝、跨 owner 隔离、不受信证书拒绝、停机回收通过 |
| 新环境绘图 | 对本轮回环数据完成校验，生成两组 PNG / PDF 和 analysis.json |
| 独立规格/质量审查 | 无阻断问题；已修复发现的文档链接和导入示例 |
| Git 暂存差分检查 | 无未解决合并冲突或 whitespace 错误 |

新环境完整回归命令（仓库根目录；`python` 指向新 venv）：

```powershell
python -X utf8 -m pytest -c apps/agentOS/pytest.ini TEST/tests/safe TEST/tests/components/test_model_partition.py TEST/tests/components/marketplace/test_builtin_tools.py TEST/tests/components/marketplace/test_builtin_catalog.py -q
python -X utf8 evals/safe/test/test_safe_data_flow.py
```

本机验收日志、下载 wheel、新 venv 和回环原始数据位于隔离工作树的
`.tmp-tests/unified-env/`，未作为源码依赖提交。此次回环在提交前运行，报告的
`runtime_commit` 为基线 `1c63269b`，实际执行的是该基线上本分支的待提交变更；
脚本与统一配置另有实际文件 SHA256，不将基线提交冒充最终运行快照。

## 能力边界

本轮证明统一环境可安装且现有功能回归成立，不声称已支持 Linux、CUDA、其他 Python
版本、公网性能、跨主机 nonce 一致性、激活 DP 或隐私预算账本。小规模 HTTPS 回环用于
安装/迁移验收，不据此给出性能优势结论。主工作区存在其他并行架构修改，本分支保留隔离，
不将那些未提交内容纳入本次提交，也不将整个架构迁移自动发布到 `master`。
