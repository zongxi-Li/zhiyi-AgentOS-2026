# safe 真实模型评估

此目录只放显式启用的真实模型实验，与 `../test/` 的轻量转换回归分开。

已实现 `verify_qwen_prefill.py`：20条固定中英文合成输入，每条进行16次greedy参考展开，比较完整Qwen2与独立prefix/suffix之间经过FP32信封和JSON字节往返后的全词表logits。为统一比较次数，固定执行16步，不使用EOS提前停止；这不是面向用户的生成API。

每步重算整个序列，`use_cache=False`；当前不测试双端KV、认证网络或DP。`prefix.prefill`最大128位置，因此本实验也会拒绝完整重算序列超限。

在仓库根目录运行（模型和角色制品须事先显式准备，不自动下载）：

```powershell
apps/agentOS/.venv-safe/Scripts/python.exe -B evals/safe/exam/verify_qwen_prefill.py `
  --source data/safe/source/qwen2.5-0.5b-instruct `
  --artifacts data/safe/artifacts/qwen2.5-0.5b-k2 `
  --manifest-digest 154770d9c59c47a080def5294976308829bdb0f480afa5efd9ad96cb2fe88f3f `
  --report data/safe/evidence/qwen-prefill-new-run.json --threads 4
```

摘要是2026-11-14这次实际导出的结果；重新导出后须使用自己核验并批准的新摘要，不能盲目固定示例值。报告已存在会拒绝覆盖，验证失败退出非零并写失败类型，不生成通过结论。

报告记录版本、上下文长度、每步greedy token、logits误差、JSON字节数、耗时、参数清单和进程内存观测，不保存真实用户输入。本机与云端参数清单只证明角色装载边界；本次同进程的内存高水位还包含完整模型oracle和库开销，不是独立设备内存基准。

固定来源和无KV结果见 `docs/superpowers/reports/safe/2026-11-14-qwen-prefill.md`。

`verify_qwen_kv.py` 支持双角色独立KV逐token对照：使用完整Qwen2的 `DynamicCache` 作为oracle，固定合成输入、最多20条×32步，比较全词表logits和greedy。默认模式直接调用角色runner，不经过JSON或会话服务，固定步数包含EOS之后的续算。

```powershell
apps/agentOS/.venv-safe/Scripts/python.exe -B evals/safe/exam/verify_qwen_kv.py `
  --source data/safe/source/qwen2.5-0.5b-instruct `
  --artifacts data/safe/artifacts/qwen2.5-0.5b-k2 `
  --manifest-digest 154770d9c59c47a080def5294976308829bdb0f480afa5efd9ad96cb2fe88f3f `
  --report data/safe/evidence/qwen-kv-new-run.json --samples 20 --steps 32 --threads 4
```

运行前须核验制品和批准摘要，报告路径必须不存在。日志/报告只记录合成样本编号、长度、误差、匹配数与耗时，不记录prompt。KV和无KV全序列重算的矩阵形状不同，因此两种oracle结果分别保留，不能把某一路径的数值保证直接扩展为另一路径的保证。

新增 `--continuation` 模式：在上述命令末尾添加该选项，并使用一个新的报告路径。此模式通过真实 `ContinuationService` 执行JSON/UTF-8激活 → 会话绑定KV → suffix → greedy → token回执；每步重复发送相同请求，检查回执相等、采样次数和step不额外推进。后段只接收激活，完整模型oracle及tokenizer仅存在于评估脚本。

此模式从已验证的角色tokenizer读取EOS；遇EOS提前结束，或达到 `--steps` 输出上限关闭会话。`steps_per_case`是上限，实际比较次数取各case的 `checked_steps` 之和；它不同于默认固定步数实验。评估并未装配完整generation配置的多EOS策略，正式装配须批准并传入完整EOS集合。报告不存储完整logits、激活、KV或输入文本。

此后本机非流式生成与EOS文本解码已接通，见下节；仍需跨进程、认证HTTP、取消协商和生产装配评估，不能将进程内实验通过等同于P2/P3全部完成。

## 本机生成配对实验与图像

`benchmark_local_generation.py` 已接入真实本机用例和完整EOS集合，对完整模型与进程内拆分生成进行20条输入×3轮配对实验。先预热，再按固定seed随机化输入和方法顺序；逐token序列、文本和停止原因一致才通过。模型加载不计入稳态延迟，记录首token、排除首步的TPOT、端到端时间、组件耗时与激活字节。它使用同机JSON循环，不含真实网络或DP。

`gen_fig_local_generation.py` 读取通过且哈希匹配的CSV，输出中文300 DPI PNG和矢量PDF：配对延迟、步骤耗时构成、激活上传量。先将重复测量汇总到输入级，再画跨输入分布；IQR不作为置信区间。脚本拒绝覆盖旧目录，不绘制失败或未配对结果。

本次1,146个token全部匹配，图像、原始数据、依赖锁及完整命令见[实验报告](../../../docs/superpowers/reports/safe/experiments/2026-11-15-local-generation/README.md)。从2026-11-16起，绘图依赖已包含在 AgentOS 统一 `requirements.txt` 中。

同日新增网络敏感性分析：`analyze_network_sensitivity.py` 复用已验证的60组计算路径，按显式256 B回执假设叠加RTT和带宽，输出360条情景记录；`gen_fig_network_sensitivity.py` 生成延迟对比和带宽×RTT热力图。两者校验数据哈希、配对与步骤完整性、情景覆盖、公式和汇总一致性，拒绝覆盖旧目录。它是串行通信分析模型，不是公网实测；完整公式、情景参数、脚本哈希和复现命令见[网络敏感性报告](../../../docs/superpowers/reports/safe/experiments/2026-11-15-network-sensitivity/README.md)。

## 独立后段进程的真实 HTTPS 回环

`verify_https_transport.py` 使用本机已有真实Qwen权重，启动独立suffix子进程和实际TCP/TLS监听，父进程持有prefix及仅用于评估的完整模型oracle。每次运行生成临时证书与随机实验凭据，客户端显式信任临时CA并校验主机名；另用默认信任库确认未信任证书被拒绝。进程退出后删除证书和凭据，不写入报告。

固定合成输入经过真实HMAC、HTTPS、JSON、会话、后段KV与token回执链路；先预热并完成回执查询、业务幂等、nonce重放、篡改和跨owner检查，再做固定seed的配对实验。后段forward次数必须等于实际生成token数，重复请求不能额外进入模型；最后故意留下未执行会话，验证应用停机释放KV。

```powershell
apps/agentOS/.venv-safe/Scripts/python.exe -m pip install --require-hashes -r apps/agentOS/requirements.txt
apps/agentOS/.venv-safe/Scripts/python.exe -B evals/safe/exam/verify_https_transport.py `
  --source data/safe/source/qwen2.5-0.5b-instruct `
  --artifacts data/safe/artifacts/qwen2.5-0.5b-k2 `
  --manifest-digest 154770d9c59c47a080def5294976308829bdb0f480afa5efd9ad96cb2fe88f3f `
  --output data/safe/evidence/https-new-run --samples 20 --repeats 3 --max-new-tokens 16 --threads 4
apps/agentOS/.venv-safe/Scripts/python.exe -B evals/safe/exam/gen_fig_https_transport.py `
  --input data/safe/evidence/https-new-run
```

生成 `runs.csv`、`http.csv`、`report.json`；HTTP表记录实际请求/响应正文的字节数、完整调用耗时、实际step/phase/position和激活字节，不含载荷或凭据。绘图前核验哈希、配对、覆盖、控制流、步骤连续性、位置、长度、停止规则、时间一致性和KV计数，输出中文300 DPI PNG/矢量PDF。统一依赖已包含绘图库，无需另装附加环境。

延迟是同机独立进程的回环结果，竞争同一CPU，不能据此推断公网/异构设备性能；字节只含正文，不含HTTP头、TLS记录、握手、TCP或重传。完整oracle也在父进程，不得把父进程内存解释为纯prefix需求。没有DP、反演攻击或产品入口验收。

本次20×3实验共792个token一致，后段62个KV全部释放；原始CSV、两组中文图像及详细统计见[HTTPS回环报告](../../../docs/superpowers/reports/safe/experiments/2026-11-15-https-loopback/README.md)。
