# 模型运行时装配

应用进程通过 `runtime.app_setup.ApplicationSetup` 装配 OpenAI Chat Completions 兼容模型。ACG、通信器、记忆器和审计器不读取环境变量，也不保存端点或密钥；它们只经已冻结的模型绑定使用注册表。

## 启动与关闭

```python
from runtime.app_setup import ApplicationSetup

app = ApplicationSetup.from_environment()
await app.start()

# 将 app.dependencies 注入 WorkflowRuntime 的应用层装配。
# 应用退出时必须执行，停止健康刷新任务。
await app.close()
```

`start()` 会创建密钥提供器、HTTP 传输和 OpenAI 兼容运行时，登记到 `model_compatibility_registry`，立即刷新一次健康投影，再启动定时刷新。`close()` 只关闭后台刷新任务；正在执行的模型流由调用协程的取消和传输层的连接关闭负责终止。

## 环境配置

`AGENTOS_MODELS` 是 JSON 数组。密钥正文不放在数组中，而是用 `apiKeyEnv` 指向单独的环境变量。

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
  },
  {
    "capabilityId": "model.local.backup",
    "provider": "openai_compatible",
    "models": ["gpt-4o-mini"],
    "baseUrl": "http://127.0.0.1:8000/v1",
    "apiKeyEnv": "LOCAL_MODEL_KEY",
    "allowInsecure": true,
    "priority": 10
  }
]
```

`AGENTOS_MODEL_HEALTH_INTERVAL_SECONDS` 控制健康刷新周期，默认 `30` 秒。HTTP 默认被拒绝；仅本地可信端点可设置 `allowInsecure: true`。同一个 `provider + model` 可登记多个实现，优先级高的实现先调用；遇到限流、超时或临时不可用时，`RegisteredModelRuntime` 会在总超时预算内切换到备实现。

## 流与取消

`HttpJsonTransport.stream_json()` 原生读取 SSE 的 `data:` 事件并识别 `[DONE]`。`OpenAICompatibleRuntime.astream()` 只向当前调用会话投影文本增量、工具调用片段和完成事件，不写入 ACG State、checkpoint 或 Trace。消费方停止迭代或任务被取消时，传输层会关闭 HTTP 响应。

流式工具调用片段只是面向客户端的展示信号。实际工具执行仍必须由 ACG 节点内的受权限限制 `ToolRuntime` 发起；`AuditedToolRuntime.astream_execute()` 和 `GuardedToolRuntime.astream_execute()` 都保留取消异常，避免客户端断开后继续把工具结果当作成功提交。

## 外部 Agent 框架

`FrameworkAgent` 将已登记的 `AgentArchitectureAdapter` 包装成 `BaseAgent`。外部框架只得到当前节点的任务输入、已装配 ContextPack 和运行/工作流/步骤引用，不能取得 `ACGExecutionGraph`、checkpoint、其他步骤输出、MemoryStore 或工具权限。图执行、审核、记忆写入和提交仍由 AgentOS 控制。
