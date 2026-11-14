# safe 参考资料与复用记录

检索/获取日期：2026-11-13。资料只用于开发参考，不是模型权重、依赖锁、运行插件或已复现结果。

## 已获取的代码材料

| 来源与固定 tag | 本地材料 | 许可证 | 当前使用方式 |
| --- | --- | --- | --- |
| Hugging Face Transformers `v4.46.3`，`modeling_qwen2.py` | [Qwen2 前向流程](qwen2-forward.md)、[原版权/许可头](NOTICE.transformers.txt)、[许可证全文](LICENSE.transformers.txt) | Apache-2.0 | 原样短摘录，说明 decoder/KV/RoPE/norm/lm head 的切分约束；尚未移入 runner。 |
| IBM differential-privacy-library `0.6.6`，`mechanisms/gaussian.py` | [高斯机制](gaussian-mechanism.md)、[原文件 MIT 许可头](LICENSE.diffprivlib.txt) | MIT | 原样短摘录，供校准与安全随机源评审；尚未移入发布机制。 |

源文件 URL、固定 tag、完整源文件文本 SHA256、摘录行号与修改说明保存在 [sources.json](sources.json)。本轮固定 tag 和获取内容摘要，**尚未解析上游 commit SHA**；实际依赖集成前还需固定 commit、制品哈希和依赖锁。不能用研究源码的版本替代模型权重的不可变 revision。

上游源码本身包含完整授权；保留的代码摘录仍适用其原许可。新增中文说明仅解释与本项目的关系。Qwen2 摘录同时保留原文件中关于 GPT-NeoX/OPT 来源的说明。IBM 顶层 `/LICENSE` 地址此次返回 404，因此没有把该响应保存成许可证，实际许可取自本次已取得的源文件完整 MIT 头。

### 哪些内容已经用于本项目

- `infrastructure/codecs/fp32.py`：本项目使用 Python 标准库 `struct`、`base64`、`hashlib` 独立实现，不是从论文复制的编解码算法。
- `infrastructure/privacy/clipping.py`：依据全局 L2 裁剪与敏感度思想独立实现数值裁剪；未复制 diffprivlib 代码，未提供 DP 发布保证。
- `domain/session_state.py`、`domain/idempotency.py`：本项目协议规则，尚不包含锁、模型前向或存储事务。
- Qwen2 / Gaussian 摘录：保存在资料文件中供后续适配；没有复制成当前可运行模型或 DP 代码，也不从资料目录动态 import。

## 已核验摘要的论文

本轮读取以下原始 arXiv 摘要页并作中文归纳；不搬运整篇文章，也不把论文中的实验结果当成本项目结果。

| 论文 | 核验的原始页面 | 可借鉴内容 | 应写入哪些位置 |
| --- | --- | --- | --- |
| Vepakomma et al., *Split learning for health: Distributed deep learning without sharing raw patient data* | [arXiv:1812.00564](https://arxiv.org/abs/1812.00564) | 原始数据留在客户端、前后段经中间表示协作的边界；该文主要讨论协作训练。 | `application/inference.py`、`continuation.py` 和角色 runner；首期冻结推理不复制训练流程。 |
| Vepakomma et al., *NoPeek: Information leakage reduction to share activations in distributed deep learning* | [arXiv:2008.09161](https://arxiv.org/abs/2008.09161) | 训练中约束原始输入与表示的距离相关性，并评估表示泄漏；摘要中的图像实验不能直接推出文本 LLM 保证。 | `ops/scripts/safe/evaluation/`；作为反演/泄漏评估和后续表示训练研究，不直接加在冻结模型上声称有效。 |
| Balle & Wang, *Improving the Gaussian Mechanism for Differential Privacy: Analytical Calibration and Optimal Denoising* | [arXiv:1805.06530](https://arxiv.org/abs/1805.06530) | 经典尾界校准有适用范围和紧致度限制；解析校准通过高斯 CDF 求解。 | `infrastructure/privacy/gaussian.py`、`accountant.py`；优先复用审核机制库，不手写未经验证的公式。 |

其余 SplitFed、Salted Inference、Petals、Opacus、OpenDP 等候选资料沿用 [safe README](../../../../../apps/agentOS/src/safe/README.md) 的索引。本轮没有下载这些项目实现或复现其结果，不能把索引链接描述为已接入的依赖。

## 后续复用检查

1. 先检查代码许可证、模型权重许可证和依赖许可证，三者不能互相替代。记录准确版本、文件和修改点。
2. 先比较数据对象、攻击者能力和邻接：图像/文本、训练/推理、梯度/激活、志愿节点/受控云端不同。
3. 先建立本项目边界测试，再将必要逻辑放入既定 `infrastructure` 适配器。不得绕过 manifest、owner、step、TTL、nonce 或预算事务。
4. 不复制不受控下载、`trust_remote_code`、任意反序列化、全模型跨角色加载和原文日志。上游开源不等于适合本项目部署。
5. 如新增上游实质代码或修改片段，同步本索引、许可文件、来源摘要和对应测试；论文中的想法与复制的代码分别记录。
