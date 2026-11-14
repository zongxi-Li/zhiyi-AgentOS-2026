"""完整模型与端云两进程数值对照工具预留，当前没有可执行运行能力。

TODO：只用批准制品与合成prompt，固定CPU FP32/eager/greedy。
TODO：分别记录prefill和连续decode的logits误差、token一致性与双端KV。
TODO：真实模型不可得明确非零退出；不能把函数自测写成模型对齐通过。
验收：没有模型/端口时不生成成功结果，不触发下载、连接或写入。
"""

if __name__ == "__main__":
    raise SystemExit("工具尚未实现，请先完成 safe README 对应阶段；未执行任何任务。")
