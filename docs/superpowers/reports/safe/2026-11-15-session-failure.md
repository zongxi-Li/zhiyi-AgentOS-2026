# Safe 会话故障与 KV 失效保护

日期：2026-11-15。范围：在现有目录和端口内加固进程内会话事务与 Qwen2 双角色缓存，执行既有回归和真实模型验证。不新增网络服务、模型下载、隐私机制或产品入口。

## 发现并修复的问题

1. 回执写入在异常保护之外。模型状态可能已推进，但写入失败后会话仍为 ACTIVE，可再次执行相同步骤。现在写入属于受保护事务；写入前/写入后抛错都清除本次未确认回执、置 FAILED，并释放 KV。此前已提交的其他请求回执仍可查询和重试返回。
2. 同步回调抛出 `CancelledError` 时未进入原有 `except Exception` 分支。现在失败保护覆盖 `BaseException`，清理后重新抛出原错误；释放失败不覆盖原计算异常，保留句柄供显式清理重试。
3. 长前向超过绝对 TTL 后仍能发布 token。现在前向交还执行权后再次检查绝对 deadline，到达300秒边界便进入 EXPIRED，不提交迟到回执。计算期间不强行释放缓存；空闲 TTL 在成功完成后重新计时，查询或幂等重试不续期。
4. 使用可重入锁时，计算回调中的查询可能按空闲 TTL 释放自己正在使用的 KV。现在明确标记执行中状态，查询不做过期释放，同线程再次执行/关闭/失败请求被拒绝；其他线程仍由原有会话锁串行化。
5. 一份 KV 释放失败会中断整轮清理。现在继续尝试其他会话，最后向调用方报告首个异常；失败会话留待下一轮重试。
6. NaN/Inf TTL 可能绕过比较。现在配置只接受有限正浮点值，并保留 idle≤absolute 约束。
7. Qwen层前向可能已经更新部分KV，再因异常或非有限输出失败，但旧句柄仍可继续使用。现在缓存访问保护覆盖层执行、输出有限值校验和返回数据转换；发生错误使该句柄失效，不回滚缓存长度，也不影响其他会话。

## 测试

先添加故障测试并验证失败，再补实现。内存回执容器的写前/写后错误通过测试内部容器注入，不增加生产故障注入API；模型故障是在真实合成Qwen层更新KV后注入异常或NaN，分别覆盖prefix/suffix和prefill/decode。

从 `apps/agentOS` 使用 `.venv-safe/Scripts/python.exe` 执行：

```powershell
python -B -m pytest tests/safe tests/components/test_model_partition.py -q -p no:cacheprovider
python -B evals/safe/test/test_safe_data_flow.py -q
```

结果：联合回归 `78 passed`，其中safe测试74项、模型分区4项；数据流脚本18项通过。模型测试共20项、会话事务测试共20项，均包含在联合回归内，不重复计数。架构依赖和独立进程轻量导入守卫随联合回归执行。

## 真实模型与验证边界

最终代码实测：20条合成中英文输入×32步，640次全词表logits对照全部满足 `atol=1e-5, rtol=1e-4`，最大绝对误差为0，greedy `640/640` 一致。脚本总耗时约74.13秒，包含模型加载、完整模型oracle和被测角色，不是端到端产品延迟或性能提升基准。JSON证据位于被忽略的 `data/safe/evidence/qwen-kv-20x32-20261115-final.json`，SHA256为 `0e1afd1a374492be021505456c25e95156d54536d7c33636095069be0f6e9c24`。

复用已批准的Qwen2.5-0.5B角色制品，固定revision、K=2、CPU FP32/eager、4线程，按以下命令验证缓存oracle：

```powershell
python -B evals/safe/exam/verify_qwen_kv.py `
  --source ../../data/safe/source/qwen2.5-0.5b-instruct `
  --artifacts ../../data/safe/artifacts/qwen2.5-0.5b-k2 `
  --manifest-digest 154770d9c59c47a080def5294976308829bdb0f480afa5efd9ad96cb2fe88f3f `
  --report ../../data/safe/evidence/qwen-kv-20x32-20261115-final.json `
  --samples 20 --steps 32 --threads 4
```

该实验只比较固定token步数的logits/greedy，不测试EOS停止、文本增量解码、上传载荷、owner认证或故障后的跨端协商。同步CPU回调交还执行权之后清理，不构成异步GPU强制取消保证。两端真实runner、会话持有的KV与采样回执尚未装配为完整网络生成用例；DP和预算账本仍明确不可用。
