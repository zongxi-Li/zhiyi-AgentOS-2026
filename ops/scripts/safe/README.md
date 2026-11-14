# safe 显式研究工具

`export_model.py` 已实现显式离线角色导出；`verify_split.py`、`benchmark.py` 仍是非零拒绝的TODO入口。真实模型同进程验证位于 `apps/agentOS/evals/safe/exam/verify_qwen_prefill.py`；独立双进程/远程verify工具仍待实现。所有入口不自动下载模型。

后续真实逻辑统一放在 `safe.application` 和 `safe.infrastructure`，工具仅调用 `safe.bootstrap.cli`，不在脚本里维护第二套模型/协议实现。

| 工具 | 后续职责 | 前置阶段 |
| --- | --- | --- |
| `export_model.py` | 固定 revision、角色权重、tied weights、哈希清单、离线导出 | P0/P2 |
| `verify_split.py` | CPU FP32/eager 基线、双进程 prefill/decode logits/token 对照 | P2/P3 |
| `benchmark.py` | 首 token、逐 token、编解码、网络、内存及隐私开销 | P6 |
| `evaluation/` | 获授权合成数据的激活反演、泄漏与质量权衡 | P4 |

离线导出示例（从根目录，source须已核验，destination须不存在）：

```powershell
apps/agentOS/.venv-safe/Scripts/python.exe -B ops/scripts/safe/export_model.py --source data/safe/source/qwen2.5-0.5b-instruct --destination data/safe/artifacts/qwen2.5-0.5b-k2 --model-id Qwen/Qwen2.5-0.5B-Instruct --revision 7ae557604adf67be50417f59c2c2f167def9a775 --cut-layer 2 --license-id Apache-2.0
```

输出摘要需核实后显式批准到配置；源码/权重许可分别保留。完整实测见 `docs/superpowers/reports/safe/2026-11-14-qwen-prefill.md`。

对应架构见 [`safe/README.md`](../../../apps/agentOS/src/safe/README.md)。证据输出到显式指定的数据/报告目录，不写入 `src/safe`，不保存真实用户输入或密钥。
