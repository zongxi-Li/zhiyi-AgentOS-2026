# safe 阶段提交：manifest身份与激活校验

日期：2026-11-14。分支：C4。阶段：P1可独立验收子功能；不表示P0/P1整阶段完成。

## 完成行为

- `ManifestService` 统一严格重校验、canonical JSON SHA256和全字段兼容比较。digest由受信配置注入；不能用客户端自报digest代替批准。
- `ActivationService` 注入codec，在读取出站值或解码入站值之前核实manifest、session、step、phase、position、hidden size和首期160上下文上限。
- `ActivationContext` 代表受信会话管理器保存的预期边界；不能从远端请求复制后用于自证。`StepRequest` 增加位置偏移，prefill从0开始、decode仅单位置。
- 基础公开门面仍只依赖合同/用例/端口；没有加载模型、网络或存储。

## 验证

在 `apps/agentOS` 执行：

```powershell
python -B -m pytest tests/safe tests/components/test_model_partition.py evals/safe/test -q -p no:cacheprovider
```

结果：54 passed、45 subtests passed。新增用例验证全字段身份、合法prefill/decode、模型错配、上下文绕过、边界长度及错误请求不能进入codec。

manifest-v1规范为严格重校验后包含默认字段的JSON对象，键排序、无空白、UTF-8、ensure_ascii=False、allow_nan=False，然后SHA256。所有声明字段参与摘要，配置摘要需绑定完整RoPE/模型配置。这是本协议固定格式，不声称实现通用RFC8785。

## 保持待办

- 实际磁盘权重哈希与角色制品校验仍由后续ArtifactStore负责；摘要比较不是权重认证。
- owner认证、nonce、会话锁、KV、TTL、网络body上限和隐私发布未由本子功能实现。
- 当前数据转换和边界规则为本项目实现；参考论文/Transformers只提供分层与模型语义依据，未声称新算法或DP完成。
