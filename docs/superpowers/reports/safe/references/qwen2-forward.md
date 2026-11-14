# Qwen2 前向流程摘录（不参与运行）

来源：Hugging Face Transformers，固定 tag `v4.46.3`。
[原文件](https://github.com/huggingface/transformers/blob/v4.46.3/src/transformers/models/qwen2/modeling_qwen2.py)。
Copyright 2024 The Qwen team, Alibaba Group and the HuggingFace Inc. team（以原文件头为准）。
许可证：Apache-2.0，全文见同目录 `LICENSE.transformers.txt`。
以下为原样短摘录，未修改代码；中文说明为本项目新增。不可作为可直接启动的safe runner。

## decoder循环与最终norm（第870–916行）

```python
        # create position embeddings to be shared across the decoder layers
        position_embeddings = self.rotary_emb(hidden_states, position_ids)

        # decoder layers
        all_hidden_states = () if output_hidden_states else None
        all_self_attns = () if output_attentions else None
        next_decoder_cache = None

        for decoder_layer in self.layers:
            if output_hidden_states:
                all_hidden_states += (hidden_states,)

            if self.gradient_checkpointing and self.training:
                layer_outputs = self._gradient_checkpointing_func(
                    decoder_layer.__call__,
                    hidden_states,
                    causal_mask,
                    position_ids,
                    past_key_values,
                    output_attentions,
                    use_cache,
                    cache_position,
                    position_embeddings,
                )
            else:
                layer_outputs = decoder_layer(
                    hidden_states,
                    attention_mask=causal_mask,
                    position_ids=position_ids,
                    past_key_value=past_key_values,
                    output_attentions=output_attentions,
                    use_cache=use_cache,
                    cache_position=cache_position,
                    position_embeddings=position_embeddings,
                )

            hidden_states = layer_outputs[0]

            if use_cache:
                next_decoder_cache = layer_outputs[2 if output_attentions else 1]

            if output_attentions:
                all_self_attns += (layer_outputs[1],)

        hidden_states = self.norm(hidden_states)

        # add hidden states from the last decoder layer
```

## LM head（第1173–1183行）

```python
            return_dict=return_dict,
            cache_position=cache_position,
        )

        hidden_states = outputs[0]
        # Only compute necessary logits, and do not upcast them to float if we are not computing the loss
        logits = self.lm_head(hidden_states[:, -num_logits_to_keep:, :])

        loss = None
        if labels is not None:
            loss = self.loss_function(logits, labels, self.vocab_size, **loss_kwargs)
```

## 对应本模块的复用方式

- `infrastructure/models/qwen.py` 在固定版本原decoder语义上分别运行 `[:K]` 和 `[K:]`。
- 切口在decoder输出、最终norm之前；不能把前导激活交给完整 `Qwen2Model.forward` 重算。
- 保留原layer_idx、position_embeddings、cache_position；两角色的KV各自保存。
- 片段包含完整模型的调试/梯度分支；冻结推理不直接复制这些分支。先完成独立角色制品和logits对照，再移植必要逻辑。
- 此tag是源码研究基准，尚未确定实际运行依赖版本；不得由源码版本推导模型权重revision或许可证。
