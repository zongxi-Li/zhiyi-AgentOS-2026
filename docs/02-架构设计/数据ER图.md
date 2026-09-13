# Kinlin 当前数据存储与 E-R 图

> 基于当前 `compose.yaml`、Spring Boot Flyway 迁移、JPA 实体，以及 AgentOS 的 SQLite Store 实现整理。
> 这是“代码定义的现状模型”；生产数据实际位于 Docker named volume，不是仓库根目录。

## 1. 存储边界总览

```mermaid
flowchart LR
    USER[用户 / 前端]
    BE[Spring Boot Backend<br/>认证、聊天、业务 API]
    AI[FastAPI + AgentOS<br/>规划、执行、投影]

    PG[(PostgreSQL<br/>postgres-data<br/>业务数据)]
    WF[(workflows.sqlite3<br/>ExecutionRuntime 真源)]
    ID[(identity_v2.sqlite3<br/>身份与查询投影)]
    AUX[(AgentOS 辅助 SQLite<br/>Checkpoint / Value / Memory / Audit 等)]
    REDIS[(Redis<br/>租约、Provider 状态)]
    UPLOADS[/backend-uploads<br/>Spring 上传文件/]
    ATTACH[/agentos/attachments<br/>AgentOS 输入附件/]

    USER --> BE
    BE --> PG
    BE --> AI
    BE --> UPLOADS
    AI --> WF
    WF -->|lifecycle events| ID
    AI --> ID
    AI --> AUX
    AI <--> REDIS
    AI --> ATTACH
    WF -. "mission_id / run_id：跨库逻辑 ID，无 SQL 外键" .-> ID
```

当前有两个主要业务边界：

- Spring Boot 业务库：PostgreSQL，保存用户、角色、对话、消息和反馈。
- AgentOS 执行库：多个 SQLite 文件，保存 Mission、Run、TaskPlan、ACG、Attempt、成果引用及恢复/审计数据。

Redis、上传目录和附件目录不是关系数据库，不能完整地表示为传统 E-R 表。

## 2. Spring Boot / PostgreSQL 业务库

```mermaid
erDiagram
    PG_USERS {
        uuid id PK
        varchar username UK
        varchar email UK
        varchar password_hash
        varchar avatar_url
        timestamp created_at
        timestamp updated_at
    }

    PG_ROLES {
        uuid id PK
        varchar name
        varchar role_type
        uuid user_id "nullable; logical reference"
        varchar stable_key UK
        text system_prompt
        jsonb dialogue_style
        jsonb personality
        jsonb avatar_config
        timestamp created_at
        timestamp updated_at
    }

    PG_CONVERSATIONS {
        uuid id PK
        uuid user_id "nullable; logical reference"
        uuid role_id "nullable; logical reference"
        varchar context_id UK
        varchar title
        varchar workspace_mode
        timestamp created_at
        timestamp updated_at
    }

    PG_MESSAGES {
        uuid id PK
        uuid conversation_id
        varchar role
        text content
        varchar message_type
        varchar file_url
        jsonb metadata
        timestamp created_at
    }

    PG_USER_FEEDBACK {
        uuid id PK
        uuid user_id
        uuid conversation_id "nullable; logical reference"
        uuid message_id "nullable; logical reference"
        uuid role_id "nullable; logical reference"
        varchar feedback_type
        integer rating
        varchar sentiment
        text content
        timestamp created_at
    }

    PG_USERS ||--o{ PG_ROLES : "user_id logical"
    PG_USERS ||--o{ PG_CONVERSATIONS : "user_id logical"
    PG_ROLES ||--o{ PG_CONVERSATIONS : "role_id logical"
    PG_CONVERSATIONS ||--o{ PG_MESSAGES : "conversation_id logical"
    PG_USERS ||--o{ PG_USER_FEEDBACK : "user_id logical"
    PG_CONVERSATIONS |o--o{ PG_USER_FEEDBACK : "conversation_id logical"
    PG_MESSAGES |o--o{ PG_USER_FEEDBACK : "message_id logical"
    PG_ROLES |o--o{ PG_USER_FEEDBACK : "role_id logical"
```

注意：这些关系目前主要由应用代码维护。Flyway SQL 只建立了主键、唯一约束和索引，没有为 `user_id`、`role_id`、`conversation_id` 等建立完整的 PostgreSQL `FOREIGN KEY`。

## 3. AgentOS Identity V2 / `identity_v2.sqlite3`

Identity V2 是查询投影和身份一致性边界，不是实际调度节点的执行真源。

```mermaid
erDiagram
    ID_MISSIONS {
        text mission_id PK
        text user_id "cross-store logical ID"
        text goal
        text status
        text metadata_json
        text created_at
        text updated_at
    }

    ID_INPUT_ATTACHMENTS {
        text attachment_id PK
        text owner_user_id
        text storage_key UK
        text original_filename
        text status
        integer size_bytes
        text sha256
        text extracted_content_ref
    }

    ID_MISSION_ATTACHMENTS {
        text mission_id PK, FK
        text attachment_id PK, FK
        integer ordinal
    }

    ID_SEMANTIC_TASKS {
        text task_id PK
        text mission_id FK
        text parent_task_id FK
        text semantic_key
        text title
        text objective
        text status
    }

    ID_TASK_PLANS {
        text mission_id PK, FK
        integer plan_version PK
        text content_hash
        text payload_json
    }

    ID_TASK_PLAN_NODES {
        text mission_id PK, FK
        integer plan_version PK, FK
        text semantic_key PK
        text task_id FK
        text payload_json
    }

    ID_TASK_PLAN_RELATIONS {
        text mission_id PK, FK
        integer plan_version PK, FK
        text source_key PK
        text target_key PK
        text relation_type PK
    }

    ID_ACG_BLUEPRINTS {
        text blueprint_id PK
        text mission_id FK
        integer version
        text graph_id
        text graph_json
    }

    ID_WORKFLOW_RUNS {
        text run_id PK
        text mission_id FK
        text blueprint_id FK
        integer graph_version
        text status
        text checkpoint_json
        text created_at
        text updated_at
    }

    ID_RUN_ATTACHMENTS {
        text run_id PK, FK
        text attachment_id PK, FK
        integer ordinal
    }

    ID_ATTEMPTS {
        text attempt_id PK
        text run_id FK
        text task_id FK
        integer attempt_number
        text status
        text failure_reason
    }

    ID_STEP_EXECUTIONS {
        text step_execution_id PK
        text attempt_id FK
        text run_id FK
        text task_id FK
        text input_json
        text output_json
        text status
    }

    ID_TASK_BINDINGS {
        text binding_id PK
        text task_id FK
        text blueprint_id FK
        text acg_node_id
        text binding_type
    }

    ID_BLUEPRINT_NODE_BINDINGS {
        text binding_id PK
        text blueprint_id FK
        text source_node_id
        text target_node_id
        text relation_type
    }

    ID_EXECUTION_BINDINGS {
        text binding_id PK
        text attempt_id FK
        text acg_node_id
        text resource_id
        text agent_id
        text model_id
    }

    ID_ARTIFACTS {
        text artifact_id PK
        text mission_id FK
        text origin_run_id FK
        text task_id FK
        text producer_attempt_id FK
        text artifact_key
        text content_ref UK
        text checksum
    }

    ID_RUN_ARTIFACT_BINDINGS {
        text binding_id PK
        text run_id FK
        text task_id FK
        text artifact_id FK
        text source_run_id FK
        text disposition
    }

    ID_PROVENANCE_LINKS {
        text source_id PK
        text target_id PK
        text relation_type PK
        text metadata_json
    }

    ID_LIFECYCLE_EVENTS {
        text event_id PK
        text event_type
        text aggregate_id
        text status
        integer attempts
    }

    ID_LIFECYCLE_INBOX {
        text event_id PK
        text event_type
        text aggregate_id
        text status
        integer attempts
    }

    ID_MISSIONS ||--o{ ID_SEMANTIC_TASKS : mission_id
    ID_SEMANTIC_TASKS |o--o{ ID_SEMANTIC_TASKS : parent_task_id
    ID_MISSIONS ||--o{ ID_TASK_PLANS : mission_id
    ID_TASK_PLANS ||--o{ ID_TASK_PLAN_NODES : plan_version
    ID_TASK_PLANS ||--o{ ID_TASK_PLAN_RELATIONS : plan_version
    ID_SEMANTIC_TASKS |o--o{ ID_TASK_PLAN_NODES : task_id
    ID_MISSIONS ||--o{ ID_ACG_BLUEPRINTS : mission_id
    ID_MISSIONS ||--o{ ID_WORKFLOW_RUNS : mission_id
    ID_ACG_BLUEPRINTS ||--o{ ID_WORKFLOW_RUNS : blueprint_id
    ID_MISSIONS ||--o{ ID_MISSION_ATTACHMENTS : mission_id
    ID_INPUT_ATTACHMENTS ||--o{ ID_MISSION_ATTACHMENTS : attachment_id
    ID_WORKFLOW_RUNS ||--o{ ID_RUN_ATTACHMENTS : run_id
    ID_INPUT_ATTACHMENTS ||--o{ ID_RUN_ATTACHMENTS : attachment_id
    ID_WORKFLOW_RUNS ||--o{ ID_ATTEMPTS : run_id
    ID_SEMANTIC_TASKS ||--o{ ID_ATTEMPTS : task_id
    ID_ATTEMPTS ||--o| ID_STEP_EXECUTIONS : attempt_id
    ID_SEMANTIC_TASKS ||--o{ ID_TASK_BINDINGS : task_id
    ID_ACG_BLUEPRINTS ||--o{ ID_TASK_BINDINGS : blueprint_id
    ID_ACG_BLUEPRINTS ||--o{ ID_BLUEPRINT_NODE_BINDINGS : blueprint_id
    ID_ATTEMPTS ||--o| ID_EXECUTION_BINDINGS : attempt_id
    ID_MISSIONS ||--o{ ID_ARTIFACTS : mission_id
    ID_WORKFLOW_RUNS ||--o{ ID_ARTIFACTS : origin_run_id
    ID_SEMANTIC_TASKS ||--o{ ID_ARTIFACTS : task_id
    ID_ATTEMPTS ||--o{ ID_ARTIFACTS : producer_attempt_id
    ID_WORKFLOW_RUNS ||--o{ ID_RUN_ARTIFACT_BINDINGS : run_id
    ID_SEMANTIC_TASKS ||--o{ ID_RUN_ARTIFACT_BINDINGS : task_id
    ID_ARTIFACTS ||--o{ ID_RUN_ARTIFACT_BINDINGS : artifact_id
    ID_WORKFLOW_RUNS |o--o{ ID_RUN_ARTIFACT_BINDINGS : source_run_id
```

以下三类表保留在图中，但它们是事件/图谱式的 ID 记录，不具备完整的 SQL 外键关系：

- `provenance_links`：任意 source/target 引用的血缘边。
- `lifecycle_projection_events`：投影事件及失败重试状态。
- `lifecycle_inbox`：Identity 投影消费幂等记录。

## 4. AgentOS Workflow Store / `workflows.sqlite3`

```mermaid
erDiagram
    WF_TASKS {
        text mission_id PK
        text payload
        text updated_at
    }

    WF_RUNS {
        text run_id PK
        text mission_id
        text payload
        text status
        text owner_user_id
        text owner_tenant_id
        text workflow_id
        text current_step_id
        text updated_at
    }

    WF_LIFECYCLE_OUTBOX {
        text event_id PK
        text event_type
        text aggregate_id
        text payload
        text status
        integer attempts
        text created_at
    }

    WF_TASKS ||--o{ WF_RUNS : mission_id
    WF_RUNS ||--o{ WF_LIFECYCLE_OUTBOX : aggregate_id logical
```

`WF_RUNS` 是执行运行时的权威记录；`ID_WORKFLOW_RUNS` 是同一 `run_id` 的身份/查询投影。两张表位于不同 SQLite 文件，没有数据库级外键。

## 5. 辅助 SQLite 存储

```mermaid
erDiagram
    EXT_RUN_REF {
        text run_id PK
        text note "logical reference to workflows.sqlite3 / identity_v2.sqlite3"
    }

    CHECKPOINTS {
        text thread_id PK
        text checkpoint_id PK
        text state_json
        integer version
        text created_at
    }

    EXECUTION_VALUES {
        text reference PK
        text run_id
        text step_id
        text kind
        text payload_json
        real created_at
    }

    NODE_EXECUTIONS {
        text operation_id PK
        text run_id
        text payload_json
        text phase
    }

    NODE_COMMITS {
        text commit_id PK
        text run_id
        text payload_json
        text stage
    }

    PROVENANCE_EVENTS {
        text run_id PK
        text event_id PK
        text event_json
    }

    AUDIT_DECISIONS {
        text decision_id PK
        text run_id
        text step_id
        text decision_json
        text decision_hash
    }

    COMMUNICATION_MESSAGES {
        text message_id PK
        text run_id
        text producer_step_id
        text consumer_step_id
        text artifact_ref
        text status
    }

    BLACKBOARD_ENTRIES {
        text run_id PK
        text partition_id PK
        text entry_key PK
        integer version PK
        text artifact_ref
    }

    CONTENT_MANIFESTS {
        text manifest_id PK
        text owner_type
        text owner_id
        text kind
        text checksum
        integer sealed
    }

    CONTENT_FRAGMENTS {
        text manifest_id PK, FK
        integer sequence PK
        text fragment_id UK
        text checksum
        blob content
    }

    EXT_RUN_REF ||--o{ CHECKPOINTS : "thread_id = run_id logical"
    EXT_RUN_REF ||--o{ EXECUTION_VALUES : "run_id logical"
    EXT_RUN_REF ||--o{ NODE_EXECUTIONS : "run_id logical"
    EXT_RUN_REF ||--o{ NODE_COMMITS : "run_id logical"
    EXT_RUN_REF ||--o{ PROVENANCE_EVENTS : "run_id logical"
    EXT_RUN_REF ||--o{ AUDIT_DECISIONS : "run_id logical"
    EXT_RUN_REF ||--o{ COMMUNICATION_MESSAGES : "run_id logical"
    EXT_RUN_REF ||--o{ BLACKBOARD_ENTRIES : "run_id logical"
    CONTENT_MANIFESTS ||--o{ CONTENT_FRAGMENTS : manifest_id
```

当前辅助文件及用途：

| 文件 | 主要表 | 用途 |
|---|---|---|
| `langgraph_checkpoints.sqlite3` | `acg_execution_checkpoints` | 重启恢复的 checkpoint |
| `execution_values.sqlite3` | `execution_values`、`acg_node_executions`、`acg_node_commits` | 输出正文、ContextPack、图补丁和提交状态 |
| `content_manifests.sqlite3` | `content_manifests`、`content_fragments` | 分片内容正文及校验和 |
| `execution_memory.sqlite3` | `execution_memory` | 通过准入的执行记忆 JSON |
| `provenance.sqlite3` | `acg_provenance_events` | 血缘事件及哈希链 |
| `audit_decisions.sqlite3` | `acg_audit_decisions` | 审计/审核决定 |
| `communication.sqlite3` | `communication_messages`、`blackboard_entries` | 可靠通信和黑板引用 |
| `resources.sqlite3` | `resources`、`resource_credentials`、`resource_auth_nonces` | Agent/模型资源目录和凭据 |
| `resource_health.sqlite3` | `resource_health`、`resource_health_events` | 资源健康状态历史 |
| `evolution.sqlite3` | `evolution_policy_versions`、`evolution_policy_state`、proposal/trajectory/evaluation 表 | 演化策略版本和提案 |

其中大部分生产路径在 `/app/data/agentos/`。当前 `AGENTOS_RESOURCE_HEALTH_DB` 和 `AGENTOS_COMMUNICATION_DB` 没有在 Compose 中显式设置，代码默认使用相对路径；容器 `WORKDIR` 为 `/app`，因此它们实际可能落在 `/app/data/` 下，而不是 `/app/data/agentos/`。这是当前配置中值得后续统一的路径问题。

## 6. 阅读这张图时最重要的结论

1. 用户/聊天数据和 AgentOS Mission/Run 数据分属 PostgreSQL 与 SQLite，不能把它们当作同一数据库里的外键关系。
2. `workflows.sqlite3.runs` 是运行时执行真源；`identity_v2.sqlite3.workflow_runs_v2` 是查询投影。
3. AgentOS 将 checkpoint、正文、记忆、血缘、审核决定和通信拆成独立存储，很多表只保存 `run_id`/`step_id`/引用，不保存大段正文。
4. `artifact.content_ref`、`input_attachments.storage_key` 和消息 `file_url` 指向内容/文件存储，不等于数据库表中的正文。
5. `TraceStore` 当前是进程内存结构，Trace 会随 Runtime Run 记录/投影链路保存或传递，不是一个独立的 `trace.sqlite3` 表。
