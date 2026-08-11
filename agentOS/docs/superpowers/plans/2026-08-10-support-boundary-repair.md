# Support Boundary Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the support-layer ACG and workflow-store boundaries importable, single-sourced, and regression-tested.

**Architecture:** `support.acg` remains the temporary canonical ACG package while all consumers use that path. Legacy domain models are removed because the versioned contracts are the only active model source. Store adapters share pure policy functions and enforce the same parent-run invariant.

**Tech Stack:** Python 3.10, Pydantic v2, pytest, SQLite.

---

### Task 1: Lock the ACG import and enum boundary

**Files:**
- Create: `tests/support/test_acg_boundary.py`
- Create: `src/support/acg/__init__.py`
- Modify: `src/support/acg/models.py`
- Modify: direct `ACG.models` consumers under `src/`

- [ ] Write tests proving `StepNode.node_type` is an instance of the exported `NodeType`, that the package has an explicit public import, and that `runtime.workflow_runtime` imports with `PYTHONPATH=src`.
- [ ] Run the tests and confirm they fail because the duplicate enum definitions and obsolete `ACG.models` path remain.
- [ ] Keep one enum declaration, remove intra-module self-imports, add the package export, and replace all consumer imports with `support.acg.models`.
- [ ] Run the boundary tests again and confirm they pass.

### Task 2: Unify workflow-store policy

**Files:**
- Create: `tests/support/test_workflow_store_contract.py`
- Create: `src/support/stores/_policy.py`
- Modify: `src/support/stores/memory_workflow_store.py`
- Modify: `src/support/stores/sqlite_workflow_store.py`

- [ ] Write a test requiring both stores to reject a run whose parent task is absent.
- [ ] Run the test and confirm the memory store fails it.
- [ ] Move shared filtering/order/terminal-overwrite functions to `_policy.py` and make the memory store enforce the parent-task invariant.
- [ ] Run the contract test for both adapters and confirm it passes.

### Task 3: Remove obsolete models and document deferred migrations

**Files:**
- Delete: `src/support/domain/agent.py`, `step.py`, `task.py`, `workflow.py`, `__init__.py`
- Create: `TODOS.md`

- [ ] Confirm there are no production imports of `support.domain`.
- [ ] Remove the unused legacy package.
- [ ] Document remaining ACG module splitting, plugin-loader relocation, and persistent-store performance/concurrency work with owner boundary, acceptance criteria, and dependency information.
- [ ] Run the focused test suite and Python compile check.
