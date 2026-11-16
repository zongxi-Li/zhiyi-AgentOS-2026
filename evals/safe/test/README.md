# safe 第一阶段功能与数据转换测试

第一步先把激活数据边界验证清楚，再接真实模型：合成激活 → FP32 little-endian → base64信封 → step合同 → JSON/UTF-8字节 → 合同解析 → 还原激活。不能直接把前导激活当作完整模型的 `inputs_embeds` 重算前K层。

脚本为 [`test_safe_data_flow.py`](test_safe_data_flow.py)，依赖Python标准库测试运行器与项目当前使用的Pydantic。无需Torch、NumPy、模型权重或云端配置；使用合成数据，不发网络请求，不创建数据库或报告文件。

从仓库根目录运行：

```powershell
python -B evals/safe/test/test_safe_data_flow.py
```

也支持从任意工作目录通过脚本绝对路径运行。输出逐项测试名称与中文说明，全部通过退出码为0，断言失败或意外异常退出码非零。只运行JSON转换测试：

```powershell
python -B evals/safe/test/test_safe_data_flow.py SafeDataFlowTests.test_02_prefill_and_decode_json_byte_roundtrip
```

## 当前覆盖

| 类别 | 验证内容 |
| --- | --- |
| 字节与转换 | 独立已知字节/base64向量、FP32舍入、正负零与小数、可复现随机形状、prefill/decode的step JSON字节往返 |
| 数据边界 | 非法batch/维数/序列/字节数、元素数量错配、分配前拒绝、有界迭代器读取、8MiB精确边界的纯规则 |
| 恶意载荷 | 摘要/形状/长度/载荷篡改、非法及非规范base64、即使摘要匹配仍拒绝NaN/Inf、未知字段/类型/版本 |
| 基础功能 | 全局L2裁剪与JSON链路、零/大数值、终态不可重开、step顺序、幂等身份匹配 |
| 不可用语义 | 模型和隐私发布当前必须返回明确不可用错误，防止骨架被当成可用服务 |

Python浮点转换成FP32通常会舍入，因此使用独立FP32参考表示，不能要求所有输入浮点逐位不变。裁剪后FP32编码也可能有微小范数误差；此处用容差验证数值，正式DP机制还须分析有限精度对敏感度的影响。

`step`往返只传递合成激活，不进行网络传输。8MiB边界用例只检查形状规则，不分配最大张量，也不是峰值内存测试。协议摘要用于完整性，不代替认证。通过裁剪测试不等于满足DP。

## 后续顺序

1. **P1：** 在现有 `application/activation.py` 完善经codec端口注入的校验流程，冻结wire字段及错误语义，再增加用例层测试。
2. **P2：** 在既定runner/制品层实现固定模型、固定切点、CPU FP32的单步prefill，比较完整模型与前后段logits。真实模型评估放到 `../exam/`，单独启用，不混入当前轻量测试。
3. **P3：** 接上双端KV、逐token、会话事务和取消，覆盖重复请求、乱序、结果不确定与过期。
4. **P4：** 机制校准和持久预算完成后，增加隐私发布事务与恢复测试。

本脚本作为手动功能回归入口；既有单元/架构测试继续保留在 `TEST/tests/safe/`。当前不包含真实模型、认证HTTP、KV、TTL、SQLite预算、噪声校准或完整DP验收，后续实现后再更新相关测试，不能删除不可用断言后直接宣称能力完成。
