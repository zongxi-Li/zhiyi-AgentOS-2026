# Node/Agent Resource Ledger Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Node/Agent ledgers the persistent source for resource scheduling while keeping old Resource responses as compatibility projections.

**Architecture:** Add SQLite stores for Node and Agent, reuse the existing HMAC resource signing protocol through a Node credential provider, make the scheduler evaluate Agent/Node pairs jointly, and upgrade leases to bind `agentId + nodeId` while preserving `resourceId` as a compatibility field.

**Tech Stack:** Python 3.11, FastAPI, Pydantic 2, SQLite, Redis Lua coordinator, pytest.

### 资源器实现说明

资源器由 Node、Agent 和调度器组成：Node 表示实际机器或服务节点，保存算力、模型、显存、隐私和心跳状态；Agent 表示可执行的能力角色，声明能力以及允许使用的节点。调度器把步骤要求、Agent 约束和 Node 状态联合筛选，选出 `agentId + nodeId`，再通过 Redis/CAS 租约占用容量；远程节点通过签名心跳更新状态，旧 Resource 接口仅作为兼容投影。

---

### Task 1: Persistent Node and Agent Stores

**Files:**
- Modify: `apps/agentOS/src/components/resource/node_store.py`
- Modify: `apps/agentOS/src/components/resource/agent_store.py`
- Modify: `apps/agentOS/src/components/resource/__init__.py`
- Modify: `apps/agent/app/execution/wiring.py`
- Test: `apps/agentOS/tests/components/resource/test_node_agent_store.py`
- Test: `apps/agent/tests/test_execution_runtime_application_wiring.py`

- [x] **Step 1: Write failing tests** proving SQLite Node/Agent stores persist profiles, snapshots, credentials and nonces across reopen.
- [x] **Step 2: Run the focused store tests and verify they fail because SQLite stores do not exist.**
- [x] **Step 3: Implement `SQLiteNodeStore` and `SQLiteAgentStore` using the existing JSON row/version pattern from `SQLiteResourceStore`.**
- [x] **Step 4: Export the stores and inject them from `wiring.py` with `AGENTOS_NODE_DB` and `AGENTOS_AGENT_DB`.**
- [x] **Step 5: Run focused store and wiring tests.**

### Task 2: Node Observation Signing Endpoint

**Files:**
- Modify: `apps/agentOS/src/components/resource/auth.py`
- Modify: `apps/agentOS/src/components/resource/node_service.py`
- Modify: `apps/agent/app/api/agentos_v2.py`
- Test: `apps/agent/tests/test_agentos_v2_api.py`

- [x] **Step 1: Write failing API tests** for signed `/nodes/{id}/observation`, nonce replay rejection, credential mismatch rejection and strict `observationSequence` increase.
- [x] **Step 2: Run the focused API tests and verify they fail because the endpoint is missing.**
- [x] **Step 3: Add a small Node authenticator that reuses canonical request signing and reads credentials/nonces from `NodeService`.**
- [x] **Step 4: Add `NodeService.observe_remote` requiring `observationSequence > current` and persisting health.**
- [x] **Step 5: Add the FastAPI endpoint and run focused API tests.**

### Task 3: Joint Agent/Node Scheduling

**Files:**
- Modify: `apps/agentOS/src/contracts/resource.py`
- Modify: `apps/agentOS/src/components/scheduler/two_layer_service.py`
- Test: `apps/agentOS/tests/components/scheduler/test_two_layer_joint_scheduling.py`

- [x] **Step 1: Write failing scheduler tests** for Agent allowed node IDs, required model IDs, GPU memory and privacy acting together on Node eligibility.
- [x] **Step 2: Run the focused scheduler tests and verify they fail because the current scheduler selects Agent and Node independently.**
- [x] **Step 3: Add `modelIds` to `NodeProfile` and make `TwoLayerSchedulerService.schedule` score legal `(Agent, Node)` pairs.**
- [x] **Step 4: Run focused scheduler tests and existing edge-cloud placement tests.**

### Task 4: Agent/Node Lease Binding

**Files:**
- Modify: `apps/agentOS/src/contracts/resource.py`
- Modify: `apps/agentOS/src/components/scheduler/leases.py`
- Test: `apps/agentOS/tests/components/scheduler/test_agent_node_leases.py`
- Test: `apps/agentOS/tests/components/scheduler/test_redis_leases.py`

- [x] **Step 1: Write failing lease tests** proving leases carry `agentId` and `nodeId`, capacity is keyed by the pair, idempotent retry returns the original lease, and Redis payload contains the pair.
- [x] **Step 2: Run focused lease tests and verify current code only keys by `resourceId`.**
- [x] **Step 3: Extend `ResourceLease` and both coordinators while keeping `resourceId` optional compatibility output.**
- [x] **Step 4: Run lease tests.**

### Task 5: Runtime Migration Slice

**Files:**
- Modify: `apps/agentOS/src/runtime/workflow_runtime.py`
- Modify: `apps/agentOS/src/adapters/resource_execution.py`
- Test: `apps/agentOS/tests/runtime/test_node_agent_runtime_migration.py`
- Test: `apps/agentOS/tests/runtime/test_resource_binding.py`

- [x] **Step 1: Write failing runtime tests** proving Runtime stores `nodeAgentBindings`, uses two-layer scheduling when a remote Node is registered, and projects old `resourceBindings` from the new binding.
- [x] **Step 2: Run the focused runtime tests and verify they fail on old scheduler/adapter paths.**
- [x] **Step 3: Add a guarded Runtime branch for Node/Agent scheduling and `build_node_execution_adapter`; keep compatibility projection only.**
- [x] **Step 4: Run runtime binding tests and API tests.**

### Task 6: Verification

**Files:**
- All changed backend files

- [x] **Step 1: Run focused resource, scheduler, API and runtime tests.**
- [x] **Step 2: Run `git diff --check`.**
- [x] **Step 3: Report remaining old Resource deletion work only after the new Runtime slice is verified.**
