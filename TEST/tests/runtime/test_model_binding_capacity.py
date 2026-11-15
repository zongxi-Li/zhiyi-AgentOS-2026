"""Exercise model admission through the real parallel READY binding path."""

import asyncio
from collections import defaultdict

import pytest

from adapters.model_compatibility import ModelCompatibilityRegistry
from adapters.model_runtime import RegisteredModelRuntime
from components.memory.store import MemoryStore
from components.mission_manager.store import WorkflowRegistry
from contracts.capability import CapabilityKind, CapabilityManifest, ModelInvocationResponse
from contracts.planning import PlannedTask, TaskImplementationBinding, TaskPlan
from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition
from runtime.workflow_runtime import ExecutionRuntime
from service.agents import AgentOutput, AgentProfile, AgentRegistry, BaseAgent
from support.acg.models import ACGBlueprint, StepNode
from support.acg.planning import ACGResourcePlan, AgentBindingSpec
from support.stores.memory_workflow_store import MemoryWorkflowStore


class _Provider:
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self.active_by_model = defaultdict(int)
        self.max_by_model = defaultdict(int)

    @property
    def manifest(self):
        return CapabilityManifest(
            capabilityId="model.capacity.test", kind=CapabilityKind.MODEL,
            displayName="Capacity test", provider="capacity-test",
            capabilities=["shared", "other"],
        )

    def is_available(self):
        return True

    async def invoke(self, request):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.active_by_model[request.model] += 1
        self.max_by_model[request.model] = max(
            self.max_by_model[request.model], self.active_by_model[request.model]
        )
        try:
            await asyncio.sleep(0.01)
            return ModelInvocationResponse(
                requestId=request.request_id, content={"answer": "ok"},
                provider="capacity-test", model=request.model,
            )
        finally:
            self.active -= 1
            self.active_by_model[request.model] -= 1


class _Agent(BaseAgent):
    def __init__(self, profile, runtimes):
        super().__init__(profile)
        self.runtimes = runtimes

    async def run(self, context):
        self.runtimes.append(context.model_runtime)
        result = await context.model_runtime.generate_json(
            prompt="return json", schema={"type": "object"},
            commit_id=context.commit_id,
        )
        return AgentOutput(output=result.data)


def _runtime(*, different_models=False, concurrency=1):
    provider = _Provider()
    models = ModelCompatibilityRegistry()
    models.register(provider)
    registry = AgentRegistry()
    runtimes = []
    for name, model in (("first", "shared"), ("second", "other" if different_models else "shared")):
        registry.register(_Agent(AgentProfile(
            agentId=name, agentName=name, domain="general", capabilities=["analysis"],
            modelProvider="capacity-test", modelName=model,
        ), runtimes))
    workflows = WorkflowRegistry()
    workflows.register(WorkflowDefinition(
        workflowId="model-capacity", name="model capacity", domain="general", runtimeEngine="acg",
        steps=[WorkflowStepDefinition(stepId="placeholder", name="placeholder", agentName="first")],
    ))
    runtime = ExecutionRuntime(
        agent_registry=registry, workflow_registry=workflows,
        workflow_store=MemoryWorkflowStore(), memory_store=MemoryStore(),
        model_registry=models, model_max_concurrency=concurrency,
    )
    return runtime, provider, runtimes


def _prepare(runtime, *, model_demand=None):
    keys = ("first", "second")
    task = runtime.create_mission("parallel model capacity", workflow_id="model-capacity")
    graph = ACGBlueprint(
        graphId="model-capacity-graph",
        nodes=[StepNode(nodeId=key, capability="analysis") for key in keys],
        resourcePlan=ACGResourcePlan(bindings=tuple(
            AgentBindingSpec(stepId=key, plannedAgentId=key) for key in keys
        )), edges=[],
    )
    if model_demand is not None:
        from support.acg.planning import ModelRequirementSpec
        graph.resource_plan.models = tuple(ModelRequirementSpec(stepId=key, demand=model_demand) for key in keys)
    plan = TaskPlan(missionId=task.mission_id, nodes=tuple(
        PlannedTask(key="step:" + key, title=key, objective=key) for key in keys
    ))
    task.input.update({
        "acgBlueprint": graph.model_dump(by_alias=True, mode="json"),
        "taskPlan": plan.model_dump(by_alias=True, mode="json"),
        "taskBindings": [TaskImplementationBinding(
            planNodeKey="step:" + key, acgNodeId=key,
        ).model_dump(by_alias=True, mode="json") for key in keys],
    })
    runtime.workflow_store.save_mission(task)
    return runtime.prepare_run(task.mission_id)[1]


@pytest.mark.parametrize("concurrency", [1, 2])
def test_parallel_ready_steps_share_model_capacity(concurrency):
    runtime, provider, wrappers = _runtime(concurrency=concurrency)
    run = _prepare(runtime)

    result = asyncio.run(runtime.execute_prepared_run(run.run_id))

    assert result.status.value == "completed"
    assert provider.max_by_model["shared"] == concurrency
    assert len(wrappers) == 2 and wrappers[0] is not wrappers[1]


def test_different_model_routes_can_execute_in_parallel():
    runtime, provider, _ = _runtime(different_models=True)
    run = _prepare(runtime)

    asyncio.run(runtime.execute_prepared_run(run.run_id))

    assert provider.max_active == 2
    assert dict(provider.max_by_model) == {"shared": 1, "other": 1}


def test_concurrent_runs_share_model_capacity():
    runtime, provider, _ = _runtime()
    runs = [_prepare(runtime), _prepare(runtime)]

    async def execute():
        return await asyncio.gather(*(runtime.execute_prepared_run(run.run_id) for run in runs))

    results = asyncio.run(execute())

    assert all(result.status.value == "completed" for result in results)
    assert provider.max_by_model["shared"] == 1


def test_same_runtime_can_reuse_model_capacity_across_sequential_event_loops():
    runtime, provider, _ = _runtime()
    for _ in range(2):
        run = _prepare(runtime)
        assert asyncio.run(runtime.execute_prepared_run(run.run_id)).status.value == "completed"

    assert provider.max_by_model["shared"] == 1


def test_binding_metadata_and_provider_spelling_do_not_split_model_capacity():
    runtime, provider, _ = _runtime()
    service = runtime.acg_execution_service
    wrappers = [service._model_runtime_from_binding(binding) for binding in (
        {"provider": "capacity-test", "model": "shared", "streamingCapability": False},
        {"provider": " Capacity-Test ", "model": " shared ", "streamingCapability": True},
    )]

    async def execute():
        await asyncio.gather(*(wrapper.generate_json(prompt="json", schema={}) for wrapper in wrappers))

    asyncio.run(execute())
    assert wrappers[0] is not wrappers[1]
    assert provider.max_by_model["shared"] == 1


@pytest.mark.parametrize("same_endpoint", [True, False])
def test_resource_model_capacity_follows_the_bound_endpoint(monkeypatch, same_endpoint):
    runtime, provider, _ = _runtime()
    runtime.resource_plane.sync_model_endpoints([
        {"provider": "capacity-test", "model": "shared", "endpointId": "endpoint:first"},
        {"provider": "capacity-test", "model": "shared", "endpointId": "endpoint:second"},
    ])
    service = runtime.acg_execution_service
    monkeypatch.setattr(service, "_resource_model_runtime", lambda _: RegisteredModelRuntime(
        registry=runtime.model_registry, provider="capacity-test", model="shared",
    ))
    wrappers = [service._model_runtime_from_binding({
        "provider": "capacity-test", "model": "shared", "endpointId": endpoint,
    }) for endpoint in ("endpoint:first", "endpoint:first" if same_endpoint else "endpoint:second")]

    async def execute():
        await asyncio.gather(*(wrapper.generate_json(prompt="json", schema={}) for wrapper in wrappers))

    asyncio.run(execute())
    assert wrappers[0] is not wrappers[1]
    assert provider.max_by_model["shared"] == (1 if same_endpoint else 2)


def test_declared_model_endpoints_share_quota_across_independent_runtimes():
    from contracts.resource import ModelDemand, ModelQuotaPolicy
    from runtime.model_quota import ModelCallQuota
    from TEST.tests.runtime.test_resource_binding import _register_remote

    first, provider, _ = _runtime(concurrency=4)
    second, _, _ = _runtime(concurrency=4)
    # Separate execution services share the same configured lease authority;
    # independent local semaphore caches therefore cannot enforce this limit.
    second.model_registry = first.model_registry
    second.resource_binder.coordinator = first.resource_binder.coordinator
    _register_remote(first.resource_plane, "worker:without-model-contract", latency_ms=0)
    demand = ModelDemand(allowedModels=["other"])
    policy = ModelQuotaPolicy(scope="account:shared", maxConcurrency=1)
    for runtime in (first, second):
        runtime.resource_plane.sync_model_endpoints([{"provider": "capacity-test", "model": "other", "quota": policy}])
    runs = [(runtime, _prepare(runtime, model_demand=demand)) for runtime in (first, second)]

    async def execute():
        return await asyncio.gather(*(runtime.execute_prepared_run(run.run_id) for runtime, run in runs))

    results = asyncio.run(execute())
    assert all(result.status.value == "completed" for result in results)
    assert provider.max_by_model["other"] == 1 and provider.max_by_model["shared"] == 0
    for runtime, result in zip((first, second), results):
        for binding in result.execution_state["executionBindings"].values():
            assert binding["modelBinding"]["model"] == "other"
            assert binding["modelBinding"]["quota"]["scope"] == policy.scope
        resource_id = ModelCallQuota(coordinator=runtime.resource_binder.coordinator, policy=policy).resource_id
        assert runtime.resource_binder.coordinator.active_slots(resource_id) == 0
        assert runtime.resource_plane.audit_counts(resource_id)["model_quota_settled"] == 2
    remote = next(candidate for candidate in results[0].execution_state["schedulingDecisions"][0]["candidates"]
                  if candidate["resourceId"] == "worker:without-model-contract")
    assert "MODEL_DEMAND_UNSUPPORTED_REMOTE" in remote["reasons"]


def test_unsatisfied_compiled_model_demand_never_falls_back_to_agent_profile():
    from contracts.resource import ModelDemand
    from components.executor.graph import ACGSuperstepError

    runtime, provider, _ = _runtime()
    runtime.resource_plane.sync_model_endpoints([{"provider": "capacity-test", "model": "shared"}])
    run = _prepare(runtime, model_demand=ModelDemand(requiredFeatures=["tools"]))
    with pytest.raises(ACGSuperstepError):
        asyncio.run(runtime.execute_prepared_run(run.run_id))
    assert provider.max_active == 0


def test_provider_failover_settles_each_adapter_attempt_and_releases_capacity():
    from adapters.openai_runtime import ModelInvocationError
    from components.resource.scheduler.leases import InMemoryLeaseCoordinator
    from contracts.resource import ModelQuotaPolicy
    from runtime.model_quota import ModelCallQuota

    class Adapter(_Provider):
        def __init__(self, primary):
            super().__init__()
            self.primary = primary

        @property
        def manifest(self):
            return super().manifest.model_copy(update={
                "capability_id": "model.primary" if self.primary else "model.backup",
                "metadata": {"priority": 100 if self.primary else 10},
            })

        async def invoke(self, request):
            if self.primary:
                raise ModelInvocationError("MODEL_TEMPORARY_UNAVAILABLE", "unavailable", usage={"total_tokens": 3})
            return (await super().invoke(request)).model_copy(update={"usage": {"total_tokens": 7}})

    registry = ModelCompatibilityRegistry()
    for primary in (True, False):
        registry.register(Adapter(primary))
    records = []
    leases = InMemoryLeaseCoordinator()
    quota = ModelCallQuota(coordinator=leases,
        policy=ModelQuotaPolicy(scope="account:failover", maxConcurrency=1, requestsPerMinute=2, tokensPerMinute=10000),
        audit=lambda resource_id, record: records.append(record))
    runtime = RegisteredModelRuntime(registry=registry, provider="capacity-test", model="shared", call_quota=quota)
    result = asyncio.run(runtime.generate_json(prompt="json", schema={}, max_output_tokens=10))
    assert result.data == {"answer": "ok"}
    assert [record["actualTokens"] for record in records] == [3, 7]
    assert all(record["status"] == "settled" for record in records)
    assert len({record["reservationId"] for record in records}) == 2
    assert leases.active_slots(quota.resource_id) == 0
