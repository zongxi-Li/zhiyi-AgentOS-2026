# safe 阶段交付：真实Qwen2.5无扰动前后段续算

日期：2026-11-14。分支：C4。范围：P0模型可行性中的真实数值对照和角色制品、P1前置数据边界；P2远程执行与P3双端KV仍未完成。

## 复刻依据与实际实现

沿用SplitNN的客户端前段/服务器后段边界，按Transformers `v4.46.3` Qwen2原始decoder/RoPE/norm/LM head语义调用库API，不引入新算法，不复制上游网络服务。旧研究摘录和许可见[资料索引](references/README.md)。

- 真实模型：`Qwen/Qwen2.5-0.5B-Instruct`，固定revision `7ae557604adf67be50417f59c2c2f167def9a775`，Apache-2.0。
- 实际源权重988097824字节，SHA256 `fdf756fa7fcbe7404d5c60e26bff1a0c8b8aa1f72ced49e7dd0210fe288fb7fe`，已与固定revision的官方LFS元数据对照。
- 固定K=2，24层，hidden=896；prefix为embedding和0/1层；suffix为2–23层、最终norm及LM head。
- 角色权重独立导出FP32，分别携带相同manifest/config及模型许可证；tokenizer/template只进入prefix目录。tied LM head显式从embedding复制，因此两角色参数总量包含重复权重。
- runner使用meta构造本角色Module，再strict assign角色权重；不创建完整模型后删层。完整模型仅在显式评估脚本作为oracle加载。
- 导出前核对完整参数名、shape、FP32和有限值；缺失、多余、错误shape、NaN/Inf或冲突tied head均拒绝，失败不发布目标目录。header、路径、文件大小和内容哈希独立校验。

来源、许可摘要和实际manifest见[来源记录](2026-11-14-qwen-source.json)。本次manifestDigest为 `154770d9c59c47a080def5294976308829bdb0f480afa5efd9ad96cb2fe88f3f`；哈希是内容身份，批准仍需操作者基于可信来源完成。

## 环境与可复现安装

Windows x64、Python3.10.11、Torch2.11.0+cpu、Transformers4.46.3、Safetensors0.4.5，CPU FP32/eager，4线程。开发环境为被Git忽略的 `apps/agentOS/.venv-safe/`；未修改原Agent解释器。

`apps/agentOS/requirements.safe.lock` 根据实际下载的35个wheel读取METADATA并逐个计算SHA256生成。已在全新 `data/safe/env-check/` 中用 `--no-index --require-hashes` 离线安装，pip check无依赖错误，并重跑完整本阶段测试与真实模型参考。此锁只针对Windows x64/CPython3.10，不能声称Linux/CUDA已验收。

从根目录建立环境：

```powershell
python -m venv apps/agentOS/.venv-safe
apps/agentOS/.venv-safe/Scripts/python.exe -X utf8 -m pip install --require-hashes -r apps/agentOS/requirements.safe.lock
```

已保存的wheel可用于离线安装：

```powershell
python -m venv data/safe/env-check
data/safe/env-check/Scripts/python.exe -X utf8 -m pip install --no-index --find-links data/safe/wheels --require-hashes -r apps/agentOS/requirements.safe.lock
```

模型下载仅在本轮明确的制品准备操作中进行；运行和导出不自动下载。源模型、角色权重、wheel和环境都在忽略目录，不进入Git提交。

## 实际验收

在全新锁环境执行：

```powershell
cd apps/agentOS
../../data/safe/env-check/Scripts/python.exe -B -m pytest tests/safe tests/components/test_model_partition.py evals/safe/test -q -p no:cacheprovider
```

结果：**65 passed**。包含9项真实Torch小型随机Qwen2结构/导出测试，以及原合同、转换、边界、不可用和架构守卫。随机小模型只验证适配器语义，不用于质量结论。

真实模型命令与参数见 `apps/agentOS/evals/safe/exam/README.md`。全新锁环境的实测：

- 20条固定中英文合成输入，每条16步，共320次比较，greedy token全部一致。
- 每步全词表最后位置logits满足 `atol=1e-5, rtol=1e-4`；本机最大绝对误差为0。
- 使用FP32 codec、StepRequest和JSON/UTF-8字节往返，不跳过转换边界。
- 本次参考约104.1秒；进程工作集高水位约5.82GB，包含两角色及完整模型oracle，不代表生产部署或独立角色峰值。
- 无KV、无网络、无DP，固定16步且不按EOS提前停止；此数字对照不等于真实聊天会话完成。

可核验的逐样本结果、参数名和内存观测见[原始证据](2026-11-14-qwen-prefill-evidence.json)。正确性小样本不代表任务质量、泛化效果或隐私保证。

## 后续阶段

1. 接入既有AgentOS模型分区计划，冻结完整wire字段/错误矩阵，保持轻量公开入口。
2. 在runner端口明确prefix/suffix执行与opaque KV句柄，增加双端独立KV、位置推进、EOS和32步上限。
3. 完成会话事务、认证/nonce、TLS、独立进程与真实网络测试，再进入P2/P3整阶段验收。
4. 最后才接P4的机制校准、持久预算与反演评估；当前隐私发布服务保持不可用。

目前安装目录仍假设受管理员控制、读取期间不被并发篡改；生产须以只读/不可变制品安装限制TOCTOU。当前没有远程服务，不把该限制隐藏成已完成的公网安全保证。
