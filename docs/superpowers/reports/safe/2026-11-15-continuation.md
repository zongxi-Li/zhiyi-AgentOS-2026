# Safe 后段会话续算闭环验收

日期：2026-11-15。本阶段保持既定分层，接通进程内 `ContinuationService`，暂不提供认证网络服务。

## 已实现行为

```text
本机prefix → 激活编码 → JSON/UTF-8 → StepRequest
    → 会话owner/manifest/step/phase/位置校验
    → 锁内提供可信ActivationContext与本会话KV
    → ActivationService解码校验 → suffix prefill/decode
    → GreedySampler → 提交StepReceipt → 推进位置或关闭/释放KV
```

- `ports/session_store.py` 新增 `ContextStepRunner` 与 `execute_with_context`；旧 `execute` 保留原回调签名。
- `MemorySessionStore` 从存储记录构造位置，禁止直接信任请求自报位置。prefill为首步，decode每次一个位置；最多32次输出、160个已处理位置。只有回执提交成功才推进位置。
- `ports/model_runner.py` 定义 `SuffixRunner`、`TokenSampler`，接口不含Torch对象、原文或可传输KV。wire合同保持不变。
- `GreedySampler` 校验完整词表长度、严格float和有限值；并列最大值选最小索引。EOS集合由可信装配传入，默认空集合；不加载配置、不产生随机状态。
- `ContinuationService` 核验批准manifest与runner身份，接受单步激活并返回单token。EOS、输出上限或位置边界结束会话；重试在回调之前返回原回执，包含终态请求。
- 激活校验、模型执行、采样、回执提交任一失败都会使会话进入失败/过期终态并释放或隔离KV。已有成功回执仍可查询，失败请求不能重算已推进状态。

同一会话使用锁串行执行；这只保证当前进程内模型事务的幂等，不构成跨进程持久事务或GPU任务强制取消。

## 装配方式

以下为受信进程内调用示例，假设已创建验证制品的 `suffix`、批准 `manifest` 和 `digest`，并从批准配置取得 `vocab_size`、`eos_ids`：

```python
from safe.application.continuation import ContinuationService
from safe.application.session import SessionService
from safe.infrastructure.codecs.fp32 import FP32Codec
from safe.infrastructure.models.sampling import GreedySampler
from safe.infrastructure.storage.memory_sessions import MemorySessionStore

sessions = SessionService(MemorySessionStore(runner=suffix))
cloud = ContinuationService(
    sessions=sessions,
    runner=suffix,
    codec=FP32Codec(),
    sampler=GreedySampler(vocab_size=vocab_size, eos_token_ids=frozenset(eos_ids)),
    manifest=manifest,
    approved_digest=digest,
    max_new_tokens=32,
)
view = cloud.create(authenticated_owner_id)
receipt = cloud.step(authenticated_owner_id, parsed_step_request)
```

**必须向会话存储与用例注入同一个suffix实例**，使句柄分配、续算和释放属于同一资源域；目前由可信装配保证，没有通用的运行时实例身份检查。真实Qwen runner会拒绝其他实例注册表中的句柄。`authenticated_owner_id` 由上层认证提供，当前没有可用认证路由，不能从请求体自报owner建立信任。

## 测试与真实权重结果

| 验证 | 本轮结果 | 覆盖边界 |
| --- | --- | --- |
| `tests/safe` + model_partition | 112 passed，退出0 | 原有合同/分层/制品/故障用例，新增可信位置、采样、后段事务、并发重复请求与回执提交失败；含小型随机权重的真实Qwen层集成。 |
| 轻量数据流脚本 | 18 passed，退出0 | FP32、base64、JSON、篡改与边界；不加载模型。 |
| Qwen2.5-0.5B-Instruct会话闭环 | 20条，382步，greedy 382/382一致，logits最大误差0，退出0 | JSON激活、真实双角色KV、采样回执、EOS/32步停止；每步重试一次，共382次幂等验证。 |
| 既有直接runner模式冒烟 | 1条×2步，greedy 2/2一致，logits最大误差0，退出0 | 新增命令选项后检查未启用 `--continuation` 的原模式仍可运行；[独立报告](2026-11-15-qwen-direct-smoke.json)。 |

真实评估使用CPU、FP32、eager、4线程，完整模型 `DynamicCache` 为oracle，容差 `atol=1e-5, rtol=1e-4`。15条输入遇EOS停止，5条达到32步上限，总耗时约56.01秒（包含模型加载和oracle）。`steps_per_case=32` 是上限，**本轮是382步，不是640步**；上一阶段固定20×32直接runner结果单独保留，不合并计数。

- 模型revision：`7ae557604adf67be50417f59c2c2f167def9a775`。
- 制品manifest digest：`154770d9c59c47a080def5294976308829bdb0f480afa5efd9ad96cb2fe88f3f`。
- Python 3.10.11、Torch 2.11.0+cpu、Transformers 4.46.3、safetensors 0.4.5。
- EOS取自已校验角色tokenizer，本次为151645；尚未装配完整generation配置的多EOS集合，不宣称与所有 `generate()` 选项等价。
- [成功原始报告](2026-11-15-qwen-continuation-verified.json)只记录合成样本编号、长度、比较数、误差、版本和耗时。进程内存观测包含两角色、完整oracle和运行库，不是独立设备内存基准。
- 首次从 `apps/agentOS` 执行时误用了相对根目录的制品路径，未进入模型执行；[失败记录](2026-11-15-qwen-continuation-results.json)保留 `FileNotFoundError`。修正工作目录后生成独立成功报告，未覆盖失败证据。

单元回归从 `E:\Project\Kinlin_AI\apps\agentOS` 执行：

```powershell
.venv-safe/Scripts/python.exe -B -m pytest tests/safe tests/components/test_model_partition.py -q -p no:cacheprovider
.venv-safe/Scripts/python.exe -B evals/safe/test/test_safe_data_flow.py
```

真实权重命令从**仓库根目录**执行，模型事先准备，脚本不下载文件；报告路径须不存在：

```powershell
apps/agentOS/.venv-safe/Scripts/python.exe -B apps/agentOS/evals/safe/exam/verify_qwen_kv.py `
  --source data/safe/source/qwen2.5-0.5b-instruct `
  --artifacts data/safe/artifacts/qwen2.5-0.5b-k2 `
  --manifest-digest 154770d9c59c47a080def5294976308829bdb0f480afa5efd9ad96cb2fe88f3f `
  --report data/safe/evidence/continuation-new-run.json `
  --samples 20 --steps 32 --threads 4 --continuation
```

## 后续TODO

1. 在现有bootstrap层固定同一runner的装配与资源关闭生命周期，批准完整EOS/generation配置；增加会话总数、并发和内存配额。
2. 实现既定本机 `SplitInferenceService`：tokenizer/128-token限制、前段KV、回执查询优先、端侧decode、EOS文本解码、双端关闭与不确定结果处理。
3. 在专用传输端口接入认证、owner注入、消息限额与deadline，验证跨进程断网/取消；保持后段没有原文入口。
4. 按原计划实现DP机制、持久预算与发布事务、反演/效用评估。当前裁剪、哈希或不传原文均不等于DP保证。

`SplitInferenceService` 和隐私发布入口依然明确不可用；本轮没有修改它们的拒绝行为，也没有开放网络服务。
