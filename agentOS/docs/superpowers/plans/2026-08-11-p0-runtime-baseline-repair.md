# P0 Runtime Baseline Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the current AgentOS source importable and ensure the default pytest command only collects AgentOS tests.

**Architecture:** Remove public exports for adapter packages that were intentionally removed, while retaining the active model and federated adapter exports. Use the current `components.planner.service` package path for runtime lazy construction. Constrain pytest collection to `tests/`, which excludes vendored open-source snapshots without changing their files.

**Tech Stack:** Python 3.10, pytest, Pydantic v2.

---

### Task 1: Lock the runtime public-import boundary

**Files:**
- Create: `tests/test_runtime_import_boundary.py`
- Modify: `src/adapters/__init__.py:15-18`
- Modify: `src/runtime/workflow_runtime.py:186,1236`

- [x] **Step 1: Write the failing regression test**

```python
from runtime.workflow_runtime import WorkflowRuntime


def test_runtime_constructs_the_current_planning_engine() -> None:
    runtime = WorkflowRuntime()

    assert runtime.planning_engine.__class__.__name__ == "PlanningEngine"
```

- [x] **Step 2: Run the test to verify it fails**

Run: `PYTHONPATH=src pytest -q tests/test_runtime_import_boundary.py`

Expected: FAIL during import because `adapters.__init__` imports the removed `adapters.remote_agent` package.

- [x] **Step 3: Remove stale adapter exports and use the current planner package**

```python
# src/adapters/__init__.py
from .model import ModelProvider

__all__ = [
    "AIService", "FederatedAdapter", "ModelAdapter", "ModelProvider",
    "ModelService", "ModelServiceFactory", "StructuredGenerationError",
    "StructuredGenerationResult", "StructuredGenerationRuntime",
    "clear_model_service_factory", "register_model_service_factory",
]

# src/runtime/workflow_runtime.py
from components.planner.service import PlanningEngine
```

- [x] **Step 4: Run the regression test to verify it passes**

Run: `PYTHONPATH=src pytest -q tests/test_runtime_import_boundary.py`

Expected: PASS.

### Task 2: Remove the stale retrieval adapter import

**Files:**
- Modify: `src/adapters/retrieval_adapter.py:1-18`
- Test: `tests/test_runtime_import_boundary.py`

- [x] **Step 1: Write the failing import regression test**

```python
def test_retrieval_adapter_does_not_require_the_removed_retrieval_package() -> None:
    adapter = importlib.import_module("adapters.retrieval_adapter")

    assert adapter.__all__ == []
```

- [x] **Step 2: Run the test to verify it fails**

Run: `pytest -q tests/test_runtime_import_boundary.py::test_retrieval_adapter_does_not_require_the_removed_retrieval_package`

Expected: FAIL because the module imports the removed top-level `retrieval` package.

- [x] **Step 3: Replace legacy re-exports with an import-safe Adapter boundary**

```python
"""检索外部实现的预留适配边界。"""

# TODO: 在定义检索 Adapter 协议后接入 Chroma、向量库和领域索引；不得恢复对已删除
# ``retrieval`` 包的直接导入，所有读写必须经 components.memory.service。

__all__: list[str] = []
```

- [x] **Step 4: Run both runtime import regressions**

Run: `pytest -q tests/test_runtime_import_boundary.py`

Expected: PASS.

### Task 3: Make the default test command collect only AgentOS tests

**Files:**
- Create: `pytest.ini`
- Test: `tests/test_runtime_import_boundary.py`

- [x] **Step 1: Verify the default command currently fails during third-party test collection**

Run: `PYTHONPATH=src pytest -q`

Expected: collection errors from `references/open-source/`.

- [x] **Step 2: Configure local test discovery**

```ini
[pytest]
testpaths = tests
pythonpath = src
```

- [x] **Step 3: Verify default collection and runtime regression pass together**

Run: `pytest -q`

Expected: PASS with only tests under `tests/` collected.

### Task 4: Correct documentation entry links

**Files:**
- Modify: `src/README.md:3`

- [x] **Step 1: Replace links relative to `src/`**

```markdown
当前实现状态、未接入边界与可迁移开源组件见 `../docs/current_implementation_review.md`；可验收的后续工作见仓库根目录 `../TODOS.md`。
```

- [x] **Step 2: Verify the files resolve from `src/README.md`**

Run: `python -c "from pathlib import Path; assert Path('src/../docs/current_implementation_review.md').is_file(); assert Path('src/../TODOS.md').is_file()"`

Expected: command exits with status 0.

### Task 5: Perform final baseline verification

**Files:**
- Test: `tests/`

- [x] **Step 1: Compile all AgentOS production modules**

Run: `python -m py_compile $(rg --files src -g '*.py')`

Expected: command exits with status 0.

- [x] **Step 2: Import every AgentOS module**

```python
from pathlib import Path
import importlib

for path in Path("src").rglob("*.py"):
    if path.name != "__init__.py":
        importlib.import_module(".".join(path.relative_to("src").with_suffix("").parts))
```

Run: `PYTHONPATH=src python <the script above>`

Expected: command exits with status 0.

- [x] **Step 3: Run the full local test suite and inspect the scoped diff**

Run: `pytest -q && git diff --check -- pytest.ini tests/test_runtime_import_boundary.py src/adapters/__init__.py src/runtime/workflow_runtime.py src/README.md`

Expected: tests pass and the scoped diff has no whitespace errors.
