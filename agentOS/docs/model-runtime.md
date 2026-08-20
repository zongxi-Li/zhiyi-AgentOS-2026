# 模型运行时装配

AI Service 通过 `runtime.app_setup.ApplicationSetup` 装配 OpenAI Chat Completions
兼容模型。生产 composition root 把现有 `WorkflowRuntime.model_registry` 注入该对象，
所以模型配置、冻结绑定与节点执行共享一个注册表。

## 生命周期

```python
runtime = build_default_runtime()
model_setup = build_model_setup(runtime)

await model_setup.start()
# 启动现有 RunExecutionCoordinator

# 先停止 coordinator，再停止健康刷新
await model_setup.close()
close_runtime(runtime)
```

空 `AGENTOS_MODELS` 配置不会创建后台任务，也不会改变当前默认结构化生成网关。
非空配置会登记适配器、刷新 registry 的健康投影并启动定时刷新。当前兼容适配器没有
主动网络探针，因此该投影证明适配器可路由，不等同于供应商端点在线监测；真实连通性
仍由调用结果证明。

## 环境配置

`AGENTOS_MODELS` 是 JSON 数组。密钥正文不放在数组中，而由 `apiKeyEnv` 指向独立
环境变量：

```json
[
  {
    "capabilityId": "model.openai.primary",
    "provider": "openai_compatible",
    "models": ["gpt-4o-mini"],
    "baseUrl": "https://api.openai.com/v1",
    "apiKeyEnv": "OPENAI_API_KEY",
    "version": "1.0.0",
    "priority": 100,
    "requestTimeoutSeconds": 120
  }
]
```

`AGENTOS_MODEL_HEALTH_INTERVAL_SECONDS` 默认 30 秒。默认要求 HTTPS；只有明确可信的
本地端点才应设置 `allowInsecure: true`。同一个 `provider + model` 可登记多个实现，
`RegisteredModelRuntime` 按优先级选择，并对限流、超时或临时不可用执行受控候选切换。

## 流、工具与外部框架

`HttpJsonTransport.stream_json()` 解析 SSE `data:` 事件并识别 `[DONE]`；停止消费时
关闭底层响应。`OpenAICompatibleRuntime.astream()` 只向当前会话投影文本、工具调用
参数分片与完成事件，不把分片写入 ACG State、checkpoint 或 Trace。

真正的工具执行仍须经过节点的 `AuditedToolRuntime` 授权边界与
`GuardedToolRuntime` 并发、总超时边界。`FrameworkAgent` 则把已登记的外部框架限制
为一个 `BaseAgent` 节点；图执行、Memory、审核、调度、恢复与提交仍由现有 AgentOS
Runtime 持有。
