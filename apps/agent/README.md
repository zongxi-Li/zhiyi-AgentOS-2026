# 知弈 Python Agent

`agent/` 是 Python FastAPI 应用层，负责暴露 AI 服务入口、加载通用 Pack、承载 LLM Gateway、Evidence Retriever 和 AgentOS Core API。AgentOS Core 的源码位于 `apps/agentOS/src/`。

## 当前职责

- FastAPI 应用入口：`app/main.py`
- AgentOS Core API：`app/api/agentos_v2.py`
- 通用 Workspace Pack：`packs/workspace/`
- LLM Gateway：`app/llm/`
- Code index builder：`app/rag/code_index_builder.py`

AgentOS Core 提供任务、运行记录、Trace、Review、Checkpoint 与通用执行协议；通用任务由 Core Native ACG 执行。

## 启动

在 `apps/agent/` 目录运行：

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

健康检查：

```bash
curl http://localhost:8000/health
```

## 测试

在 `apps/agent/` 目录运行：

```bash
python -m pytest tests
```

## 主要 API

通过本地 TypeScript Gateway 访问时，前端主要使用 `/ai/core/**`。Python Agent 直接暴露同名 AgentOS Core API：

```text
POST /ai/core/tasks
GET  /ai/core/tasks
POST /ai/core/workflows/runs
POST /ai/core/workflows/start
GET  /ai/core/workflows/runs
GET  /ai/core/workflows/metrics
GET  /ai/core/workflows/runs/{runId}
GET  /ai/core/workflows/runs/{runId}/checkpoints
GET  /ai/core/workflows/runs/{runId}/trace
GET  /ai/core/workflows/runs/{runId}/reviews
POST /ai/core/workflows/runs/{runId}/reviews
POST /ai/core/workflows/runs/{runId}/resume
POST /ai/core/workflows/runs/{runId}/cancel
```

## 能力边界

### OScode 会话上下文与缓存统计

OScode 使用 SDK `SQLiteSession` 在数据目录的 `oscode_sessions.sqlite3` 保存完整模型协议消息，
按已认证用户、租户、对话、端点、模型和角色隔离。界面正文仅用于旧对话首次迁移，
以后从协议日志追加新用户消息，保留工具调用与已确认结果。中断回复明确标记未完成；
缺失的工具结果在投递视图中标为 `TOOL_OUTCOME_UNKNOWN`，不伪造成功、不自动重跑工具。
删除对话会同时清理协议日志；并发发送同一会话被拒绝。显式压缩仅改变发送视图，
保留原日志，并从日志恢复压缩后保留尾部的完整工具周期。

这里参考 DSH 固定版本 `fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159` 的
`core/session` 日志、surface、tool-history 和 repair 分层；没有引入第二套 Agent 调度器。
旧记录没有保存过的工具参数无法补回。会话延续不保证供应商缓存命中：
界面只显示供应商实际返回的 `cached_tokens`，缺失时显示未返回统计，不能当作零。
上下文窗口容量独立显示；本轮请求最终 usage 尚未返回时，显示完整协议请求的 UTF-8 大小估算并标明上界，
完成后使用最后一次模型调用用量，不拿多次工具循环的累计输入量充当窗口占用。

模型等待配置（秒）独立于 `TOOL_TIMEOUT_SECONDS`：

| 配置 | 默认值 | 含义 |
| --- | --- | --- |
| `MODEL_CONNECT_TIMEOUT_SECONDS` | 10 | OScode 模型连接、写请求及连接池等待 |
| `MODEL_FIRST_RESPONSE_TIMEOUT_SECONDS` | 300 | 等待供应商响应头及首段数据 |
| `MODEL_STREAM_IDLE_TIMEOUT_SECONDS` | 300 | 供应商原始数据流连续无数据的等待窗口 |
| `MODEL_REQUEST_TOTAL_TIMEOUT_SECONDS` | 900 | OScode 每次 HTTP 尝试上限；ACG 未显式指定预算时的默认值 |
| `MODEL_REQUEST_MAX_RETRIES` | 2 | OScode 响应开始前的 SDK 请求重试，限制为 0–5 次 |

思考、工具参数和供应商心跳都属于模型连接活动；发给界面的本地 SSE 心跳不算。
模型已开始输出后不自动重放该流或整轮工具循环，保留部分内容并报告中断。
工具执行、人工审批和 ACG 已显式指定的步骤总预算仍分别管理；
`AGENTOS_LLM_TIMEOUT_SECONDS` 显式配置继续优先，不配置时按模型首响应/空闲窗口设置传输等待。

- 不再内置律师、教师、程序员、作家、工业职业 Pack；这些目录已从当前树删除（git 历史仍可追溯）。
- 当前保留的唯一应用 Pack 是 `workspace`：在受审计的 Hands 资源中修改文件并运行真实测试。
- 通用任务通过 `native_acg_runtime_v1` 执行，不依赖职业专用 workflow。

## V1.0.6 代码边界

ACG 原生执行请求的共享前缀布局适用于所有供应商，不按供应商名称分支。
公共层按“固定运行规则 → 当前任务的公共材料 → 节点策略及输出契约 → 节点输入”组织消息；
材料仍为不可信 user 内容，权限和策略仍来自受信任的 system 内容。
供应商适配层分别处理 JSON Schema / JSON Object、思考参数等协议差异。
未使用受信任、版本化 ExecutionRequest 信封的请求保持原布局，避免改写自定义提示词。
实际命中以供应商返回的缓存 Token 为准；相同共享前缀哈希不构成命中证明。

- AgentOS Core 不直接 import 应用层业务模块。
- ACG 通过就绪集调度执行 Pack agents，并保留 Trace、Review、Checkpoint、数据血缘和自愈。
- Core 侧 `model_adapter.py` 只保留模型协议和注册入口，具体 `app.services.aiservice.AIService` 由 `app/integrations/model_adapter.py` 注册。
