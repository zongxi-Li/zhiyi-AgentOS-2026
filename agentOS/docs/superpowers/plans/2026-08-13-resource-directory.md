# 统一资源目录 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可登记和识别 Agent、模型、Skill、Tool 的本地统一资源目录，并在 ACG 准备阶段冻结 Agent 绑定。

**Architecture:** `AgentRegistry` 继续保存可调用的 Agent 实例；`ResourceDirectory` 保存可审计资源元数据并按健康、scope、领域和能力选择稳定 Agent。`WorkflowRuntime.prepare_run` 保存冻结绑定，执行期据此解析，避免注册表变化造成资源漂移。

**Tech Stack:** Python 3.10、Pydantic 2、pytest、现有 AgentOS Resource / Agent / Workflow 合同。

---

### Task 1: 定义目录记录与本地选择规则

**Files:**

- Create: `src/components/resource/directory.py`
- Modify: `src/components/resource/__init__.py`
- Test: `tests/components/resource/test_directory.py`

- [ ] **Step 1: 写失败测试，覆盖登记、冲突、健康和稳定选择。**

```python
def test_directory_selects_healthy_scoped_agent_by_priority() -> None:
    directory = ResourceDirectory()
    directory.register_agent(profile=low_profile)
    directory.register_agent(profile=high_profile)
    directory.set_health("high", healthy=False)

    selected = directory.resolve_agent(
        domain="general", capability="analyse", allowed_agent_ids=["low", "high"]
    )

    assert selected.agent_id == "low"
```

- [ ] **Step 2: 运行测试，确认因目录尚不存在而失败。**

Run: `$env:PYTHONPATH='src;.'; pytest -q tests/components/resource/test_directory.py`

Expected: FAIL，提示 `ResourceDirectory` 尚不能导入。

- [ ] **Step 3: 最小实现目录和选择规则。**

```python
class ResourceDirectory:
    def register_agent(self, profile: AgentProfile) -> AgentResource: ...
    def register_capability(self, manifest: CapabilityManifest) -> CapabilityManifest: ...
    def set_health(self, resource_id: str, *, healthy: bool) -> None: ...
    def resolve_agent(self, *, domain: str, agent_name: str | None, capability: str | None,
                      allowed_agent_ids: Iterable[str] | None = None) -> AgentResource: ...
```

选择顺序为：scope / enabled / healthy → 精确名称 → capability → domain → priority → agentId。

- [ ] **Step 4: 重跑目录测试。**

Run: `$env:PYTHONPATH='src;.'; pytest -q tests/components/resource/test_directory.py`

Expected: PASS。

### Task 2: 接入 AgentRegistry 并冻结 ACG 绑定

**Files:**

- Modify: `service/agents/registry.py`
- Modify: `src/runtime/workflow_runtime.py`
- Test: `tests/runtime/test_resource_binding.py`

- [ ] **Step 1: 写失败测试，要求 prepare_run 保存每个 Step 的 agentId 绑定。**

```python
def test_prepare_run_freezes_resource_bindings() -> None:
    _, run = runtime.prepare_run(task.task_id)
    assert run.execution_state["resourceBindings"] == {"step": "agent-primary"}
```

- [ ] **Step 2: 运行测试，确认资源绑定尚不存在。**

Run: `$env:PYTHONPATH='src;.'; pytest -q tests/runtime/test_resource_binding.py`

Expected: FAIL，缺少 `resourceBindings`。

- [ ] **Step 3: 最小接线。**

```python
bindings = directory.freeze_bindings(blueprint.step_nodes(), domain=workflow.domain,
                                     allowed_agent_ids=scope.agent_ids)
run.execution_state["resourceBindings"] = bindings
```

执行期从冻结 `agentId` 解析，不再重新按照 capability 选择。

- [ ] **Step 4: 重跑 Runtime 绑定测试。**

Run: `$env:PYTHONPATH='src;.'; pytest -q tests/runtime/test_resource_binding.py`

Expected: PASS。

### Task 3: 保护执行期绑定不漂移

**Files:**

- Modify: `src/runtime/workflow_runtime.py`
- Test: `tests/runtime/test_resource_binding.py`

- [ ] **Step 1: 写失败测试，准备后新增更高优先级 Agent 不得改变既有 run 的绑定。**

```python
prepared_binding = run.execution_state["resourceBindings"]["step"]
registry.register(new_higher_priority_agent)
result = asyncio.run(runtime.execute_prepared_run(run.run_id))
assert invoked_agent_id == prepared_binding
```

- [ ] **Step 2: 运行测试，确认执行期仍可能按能力重新选择。**

Run: `$env:PYTHONPATH='src;.'; pytest -q tests/runtime/test_resource_binding.py`

Expected: FAIL，调用了新注册 Agent。

- [ ] **Step 3: 从冻结绑定解析 Agent，并校验名称一致性。**

```python
agent_id = bindings[step_id]
agent = self.agent_registry.resolve_by_id(agent_id, allowed_agent_ids=allowed_agent_ids)
```

- [ ] **Step 4: 重跑绑定测试。**

Run: `$env:PYTHONPATH='src;.'; pytest -q tests/runtime/test_resource_binding.py`

Expected: PASS。

### Task 4: 完整验证与文档状态更新

**Files:**

- Modify: `drafts/legacy_execution/MANIFEST.md`
- Test: 全部 tests

- [ ] **Step 1: 更新归档状态说明。**

明确新 Blueprint 已由融合执行底座接管；只有历史 `runtimeGraph` 不可执行和不可恢复。

- [ ] **Step 2: 运行完整验证。**

Run: `$env:PYTHONPATH='src;.'; pytest -q; $files = @(); $files += rg --files src -g '*.py'; $files += rg --files service -g '*.py'; python -m py_compile $files; git diff --check`

Expected: pytest 全部通过、编译通过、差异检查通过。

- [ ] **Step 3: 提交。**

```powershell
git add docs/superpowers/specs/2026-08-13-resource-directory.md docs/superpowers/plans/2026-08-13-resource-directory.md src/components/resource service/agents src/runtime/workflow_runtime.py tests/components/resource tests/runtime drafts/legacy_execution/MANIFEST.md
git commit -m "feat: 增加统一资源目录与 ACG 绑定"
```
