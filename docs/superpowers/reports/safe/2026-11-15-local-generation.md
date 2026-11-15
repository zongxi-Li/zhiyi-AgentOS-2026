# Safe 本机生成用例验收

日期：2026-11-15。承接后段会话续算阶段，未改变既定模块分层。

## 功能与调用边界

`SplitInferenceService` 在显式注入前段runner、分词器、codec、传输端口及批准manifest后可用。无参构造保持原不可用行为；不自动下载、不回退到普通聊天。当前一实例只允许一个活动生成。

本机执行：固定chat template → 最多128个prompt token → 前段KV/prefill → 激活编解码与step → 前段逐token decode → 完整输出文本解码。每步回执核验request/session/step、词表和EOS语义，最多32次输出。首版非流式，不逐token拼接可能不完整的Unicode文本。

发生超时、连接丢失或 `TRANSPORT_UNAVAILABLE` 时，仅查询一次已提交回执；取得匹配回执后继续，否则终止。查不到回执不等于证明请求未执行，不盲目重发。生成成功、异常或协作取消均尝试关闭后段会话并释放本机KV；一个清理失败不跳过另一个，也不掩盖原始异常。跨网络清理失败仍须依靠远端TTL，不能保证立即撤销远端计算。

`HuggingFaceTokenizer` 只读取校验过的prefix角色制品，禁用在线下载与远程代码。EOS优先取generation配置的完整集合，再回退到模型配置；只读取EOS，不应用源文件中的temperature、top-p、随机采样或重复惩罚。

`bootstrap/cloud.py` 的 `InProcessTransport` 装配同一个suffix进行KV创建/续算/释放，并实际经过JSON/UTF-8请求和回执。owner由可信研究调用者注入；它没有网络认证、HTTP监听或TLS，不应发布为云端服务。连接关闭与单会话关闭分别定义，runner所有权属于调用者。

## 验证

从 `apps/agentOS` 使用独立safe环境执行：

```powershell
$env:OMP_NUM_THREADS='4'
$env:MKL_NUM_THREADS='4'
.venv-safe/Scripts/python.exe -B -m pytest tests/safe tests/components/test_model_partition.py -q -p no:cacheprovider
.venv-safe/Scripts/python.exe -B evals/safe/test/test_safe_data_flow.py
```

联合回归139项通过，退出0；相较上一阶段新增27项，包括20项本机事务测试、2项研究装配测试，以及小型真实Qwen层/有效分词器集成与非法EOS配置测试。新增接口先观察未实现失败，再补实现验证通过；模型集成使用合成权重，不能代称真实预训练模型性能验收。

轻量数据流仍保留无配置模型/隐私明确拒绝的断言。真实预训练模型的配对性能实验由独立显式脚本执行，后续报告另存原始数据和图像。

## 剩余工作

认证HTTP、跨进程断网/取消、deadline、全局会话/内存配额、产品接口、DP发布及预算账本尚未实现。当前取消在同步调用之间检查，不是强制终止在途GPU或远端任务。
