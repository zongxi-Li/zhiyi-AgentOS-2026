# safe 显式研究工具

已创建 `export_model.py`、`verify_split.py`、`benchmark.py` 和 `evaluation/README.md`。三个 Python 文件均是有中文 TODO 的工具入口；直接运行会以非零状态说明尚未实现，不下载模型、不连接远端、不写成功报告。

后续真实逻辑统一放在 `safe.application` 和 `safe.infrastructure`，工具仅调用 `safe.bootstrap.cli`，不在脚本里维护第二套模型/协议实现。

| 工具 | 后续职责 | 前置阶段 |
| --- | --- | --- |
| `export_model.py` | 固定 revision、角色权重、tied weights、哈希清单、离线导出 | P0/P2 |
| `verify_split.py` | CPU FP32/eager 基线、双进程 prefill/decode logits/token 对照 | P2/P3 |
| `benchmark.py` | 首 token、逐 token、编解码、网络、内存及隐私开销 | P6 |
| `evaluation/` | 获授权合成数据的激活反演、泄漏与质量权衡 | P4 |

对应架构见 [`safe/README.md`](../../../apps/agentOS/src/safe/README.md)。证据输出到显式指定的数据/报告目录，不写入 `src/safe`，不保存真实用户输入或密钥。
