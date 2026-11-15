# Safe 本机生成与对照实验实施计划

> 执行方式：沿用已确认的 safe 分层与分阶段提交，在当前会话执行；用户已确认开始实施。采用测试驱动与完成前验证。

**Goal:** 将本机分词、前段KV、回执恢复与文本解码接到既有后段，并输出真实测量的对照实验图。

**Architecture:** 在既有 `application/inference.py` 实现注入式本机用例，在 `ports/model_runner.py` 增加本机端口，在既有tokenizer与bootstrap/cloud文件实现离线分词和明确命名的进程内JSON传输。HTTP、DP及产品入口继续保持独立范围。

**Tech Stack:** Pydantic、Transformers 4.46.3、Torch CPU FP32、Matplotlib；运行与绘图使用独立safe环境。

## 1. 本机生成闭环

- [x] 先在 `tests/safe/application/test_local_inference.py` 覆盖EOS/长度、128 token边界、回执身份、超时查询、未知结果拒绝重发、取消与双端清理，再运行并观察未配置接口失败。
- [x] `ports/model_runner.py` 定义 `PrefixRunner`、`LocalTokenizer`；`ports/remote_transport.py` 增加会话创建/关闭，保留连接关闭语义。
- [x] 在 `application/inference.py` 实现 `infer(request, *, cancelled=None)`：无配置仍拒绝；批准身份核验；单活动会话；128 token限额；只传激活；响应绑定请求；最多32次；完整本机解码。超时只查询一次，无法确认则结束，不盲目重发。
- [x] 在 `infrastructure/models/tokenizer.py` 实现固定模板、离线加载和完整EOS集合读取；不启用源generation配置中的随机采样或重复惩罚。
- [x] 在 `bootstrap/cloud.py` 装配 `InProcessTransport`，保证同一suffix用于句柄创建、执行和释放；JSON请求与回执实际往返。类名和文档明确其不提供认证网络能力。
- [x] 增加真实Qwen层集成，运行 `python -B -m pytest tests/safe tests/components/test_model_partition.py -q -p no:cacheprovider` 与轻量数据流脚本；完成一组功能后提交。

本机关键调用顺序：

```python
session = transport.create_session(approved_digest)
handle = prefix.create_kv(session.session_id)
activation, shape = prefix.prefill(token_ids, kv_handle=handle, session_id=session.session_id)
# 每步生成一个新request_id；同一步的激活在回执确定前保持不变。
receipt = transport.step(step_request)
# 发生结果不确定的传输错误时只query，不以查不到结果作为重算依据。
```

## 2. 实验、图像与证据

- [x] 在 `evals/safe/exam/benchmark_local_generation.py` 比较完整模型DynamicCache与实际本机用例，固定同一模型/revision、CPU FP32/eager、4线程、greedy、完整EOS集合和32 token上限。
- [x] 20条既有中英文合成输入，双方各预热2次；3轮重复，固定seed随机化样本和方法执行顺序。按会话记录原始CSV/JSON及每步测量，逐token与解码结果完全一致才通过。输出长度随EOS变化，TPOT明确排除首token。
- [x] 模型加载不计入稳态延迟；端到端时间包含分词/编解码、协议和资源清理，首token时间截至首回执。组件计时只作归因，同机循环传输不伪称真实网络性能。
- [x] 使用独立绘图脚本，导出至少三组300 DPI PNG与矢量PDF：配对延迟分布、prefill/decode耗时构成、激活上传量。固定颜色、中文字体、清晰单位与样本量；不绘制虚构训练曲线或隐私结果。
- [x] 检查生成图像文字和布局，报告试验协议、原始数据路径、聚合方式、结果及限制；更新模块README，验证后独立提交并同步两端。

首次实现不含流式UI、认证HTTP、跨进程、CUDA、压缩、正式DP或任务强制取消。所有原始结果保留版本与失败状态，不覆盖旧实验。
