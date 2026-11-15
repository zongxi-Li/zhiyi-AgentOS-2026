# safe 真实模型评估

此目录只放显式启用的真实模型实验，与 `../test/` 的轻量转换回归分开。

已实现 `verify_qwen_prefill.py`：20条固定中英文合成输入，每条进行16次greedy参考展开，比较完整Qwen2与独立prefix/suffix之间经过FP32信封和JSON字节往返后的全词表logits。为统一比较次数，固定执行16步，不使用EOS提前停止；这不是面向用户的生成API。

每步重算整个序列，`use_cache=False`；当前不测试双端KV、认证网络或DP。`prefix.prefill`最大128位置，因此本实验也会拒绝完整重算序列超限。

在仓库根目录运行（模型和角色制品须事先显式准备，不自动下载）：

```powershell
apps/agentOS/.venv-safe/Scripts/python.exe -B apps/agentOS/evals/safe/exam/verify_qwen_prefill.py `
  --source data/safe/source/qwen2.5-0.5b-instruct `
  --artifacts data/safe/artifacts/qwen2.5-0.5b-k2 `
  --manifest-digest 154770d9c59c47a080def5294976308829bdb0f480afa5efd9ad96cb2fe88f3f `
  --report data/safe/evidence/qwen-prefill-new-run.json --threads 4
```

摘要是2026-11-14这次实际导出的结果；重新导出后须使用自己核验并批准的新摘要，不能盲目固定示例值。报告已存在会拒绝覆盖，验证失败退出非零并写失败类型，不生成通过结论。

报告记录版本、上下文长度、每步greedy token、logits误差、JSON字节数、耗时、参数清单和进程内存观测，不保存真实用户输入。本机与云端参数清单只证明角色装载边界；本次同进程的内存高水位还包含完整模型oracle和库开销，不是独立设备内存基准。

固定来源和无KV结果见 `docs/superpowers/reports/safe/2026-11-14-qwen-prefill.md`。

`verify_qwen_kv.py` 已支持双角色独立KV逐token对照：使用完整Qwen2的 `DynamicCache` 作为oracle，固定合成输入、最多20条×32步，比较全词表logits和greedy。该脚本直接调用角色runner，不经过JSON/网络或会话服务；固定步数包含EOS之后的续算，不代表EOS停止和流式文本解码已验收。

```powershell
apps/agentOS/.venv-safe/Scripts/python.exe -B apps/agentOS/evals/safe/exam/verify_qwen_kv.py `
  --source data/safe/source/qwen2.5-0.5b-instruct `
  --artifacts data/safe/artifacts/qwen2.5-0.5b-k2 `
  --manifest-digest 154770d9c59c47a080def5294976308829bdb0f480afa5efd9ad96cb2fe88f3f `
  --report data/safe/evidence/qwen-kv-new-run.json --samples 20 --steps 32 --threads 4
```

运行前须核验制品和批准摘要，报告路径必须不存在。日志/报告只记录合成样本编号、长度、误差、匹配数与耗时，不记录prompt。KV和无KV全序列重算的矩阵形状不同，因此两种oracle结果分别保留，不能把某一路径的数值保证直接扩展为另一路径的保证。

后续仍需跨进程、认证HTTP、EOS/输出上限、取消和实际会话装配评估；不能将本实验通过等同于P2/P3完成。
