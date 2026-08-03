# ACG Appendix Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align AgentOS ACG public models with Appendix I without changing the current scheduler's behavior.

**Architecture:** Keep the current Pydantic ACG graph models and add read-only compatibility aliases for Appendix identifiers. Add a focused runtime-record module so Appendix runtime data is explicit rather than hidden in `WorkflowRun` and `RuntimeGraph`. Unsupported control semantics fail explicitly at validation.

**Tech Stack:** Python 3.10, Pydantic v2, pytest.

---

### Task 1: Static-node appendix aliases

**Files:**
- Modify: `agentOS/src/agentos/core/acg/nodes.py`
- Modify: `agentOS/tests/test_acg_model.py`

- [ ] Write tests that serialize every node with `by_alias=True` and assert `stepId`, `agentId`, `agentName`, `skillId`, `skillName`, `memoryId`, `memoryName`, `evidenceId`, `evidenceName`, and `controlId` map to the generic node identity.
- [ ] Run `agent/.venv/Scripts/python.exe -m pytest agentOS/tests/test_acg_model.py -q` and confirm the new assertions fail because aliases are absent.
- [ ] Add read-only Pydantic computed aliases backed by `node_id` and `name`; add `status` to StepNode and AgentNode, and `schema` dictionaries to MemoryNode and EvidenceNode.
- [ ] Re-run the same test command and confirm it passes.

### Task 2: Explicit Appendix runtime records

**Files:**
- Create: `agentOS/src/agentos/core/models/acg_runtime.py`
- Modify: `agentOS/src/agentos/core/models/__init__.py`
- Create: `agentOS/tests/test_acg_runtime_contracts.py`

- [ ] Write failing tests that instantiate and serialize `ACGTask`, `StepExecution`, `AgentInstance`, `EvidenceRecord`, `MemorySnapshot`, and `RecoveryCheckpoint` using every Appendix field.
- [ ] Run `agent/.venv/Scripts/python.exe -m pytest agentOS/tests/test_acg_runtime_contracts.py -q` and confirm collection fails because the module does not exist.
- [ ] Implement the six Pydantic contract records and their narrow status/type enums. Do not connect them to persistence or execution.
- [ ] Re-run the runtime-contract test command and confirm it passes.

### Task 3: Public API and unsupported controls

**Files:**
- Modify: `agentOS/src/agentos/core/acg/__init__.py`
- Modify: `agentOS/src/agentos/core/acg/graph_ops.py`
- Modify: `agentOS/tests/test_acg_model.py`

- [ ] Write tests that import the new runtime record types from `agentos.core.models`, and assert validation rejects both LOOP and CONSENSUS with an explicit unsupported-control error.
- [ ] Run the relevant test files and confirm they fail for the missing export and consensus behavior.
- [ ] Export the new contracts and generalize the unsupported-control validation to LOOP and CONSENSUS.
- [ ] Re-run the relevant tests and confirm they pass.

### Task 4: Regression verification

**Files:**
- Test: `agentOS/tests/test_acg_model.py`
- Test: `agentOS/tests/test_runtime_graph.py`
- Test: `agentOS/tests/test_runtime_graph_execution.py`
- Test: `agentOS/tests/test_runtime_events.py`
- Test: `agentOS/tests/test_acg_runtime_contracts.py`

- [ ] Run `agent/.venv/Scripts/python.exe -m pytest agentOS/tests/test_acg_model.py agentOS/tests/test_runtime_graph.py agentOS/tests/test_runtime_graph_execution.py agentOS/tests/test_runtime_events.py agentOS/tests/test_acg_runtime_contracts.py -q`.
- [ ] Inspect the exit code and report any failures or existing warnings without changing unrelated code.
