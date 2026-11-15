"""Run two heterogeneous review Agents through the production ACG execution path.

PowerShell, from the repository root (AGENTOS_MODELS uses the existing app format)::

    py -3 ops/scripts/heterogeneous_execution_trial.py --env-file apps/agent/.env --dry-run
    py -3 ops/scripts/heterogeneous_execution_trial.py --env-file apps/agent/.env --execute

The default is a network-free dry run. ``--execute`` sends the two small, bundled
review materials to configured real models. No external tool is invoked. Compare
``--model-concurrency 1`` and ``2`` in separate runs to inspect shared model quota.
Each execution writes report.json and isolated Runtime SQLite stores beneath its
output directory. Provider invocation observation is local to this trial script.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from time import monotonic
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
for root in (PROJECT_ROOT / "apps/agentOS", PROJECT_ROOT / "apps/agentOS/src"):
    sys.path.insert(0, str(root))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Validate configuration and show the graph; never contact models (default).")
    mode.add_argument("--execute", action="store_true", help="Run the existing Runtime against configured real model endpoints.")
    parser.add_argument("--env-file", type=Path, help="Optional dotenv file; its values override the inherited environment for model setup.")
    parser.add_argument("--first-route", help="Configured provider/model for the requirements Agent; defaults to the highest priority route.")
    parser.add_argument("--second-route", help="Configured provider/model for the delivery Agent; defaults to the first route.")
    parser.add_argument("--quota-scope", default="trial:shared-model-account", help="Shared quota identity for both selected model endpoints.")
    parser.add_argument("--model-concurrency", type=int, default=1, help="Maximum concurrent model calls across both endpoints (default: 1).")
    parser.add_argument("--requests-per-minute", type=int, help="Optional shared rolling request limit.")
    parser.add_argument("--tokens-per-minute", type=int, help="Optional shared rolling token limit; include enough room for both prompts and output reservations.")
    parser.add_argument("--max-output-tokens", type=int, default=900, help="Per-call output reservation (default: 900).")
    parser.add_argument("--output-dir", type=Path, help="Execution artifacts directory; defaults to data/heterogeneous-trials/<timestamp>.")
    return parser.parse_args()


def _configuration(args: argparse.Namespace):
    from runtime.app_setup import ApplicationSetup

    values = dict(os.environ)
    if args.env_file:
        if not args.env_file.is_file():
            raise ValueError("TRIAL_ENV_FILE_MISSING: the requested environment file does not exist")
        from dotenv import dotenv_values
        values.update({key: value for key, value in dotenv_values(args.env_file).items() if value is not None})
    for name in ("model_concurrency", "max_output_tokens", "requests_per_minute", "tokens_per_minute"):
        value = getattr(args, name)
        if value is not None and value < 1:
            raise ValueError(f"TRIAL_ARGUMENT_INVALID: --{name.replace('_', '-')} must be positive")
    if not args.quota_scope.strip():
        raise ValueError("TRIAL_ARGUMENT_INVALID: --quota-scope must not be blank")
    # Reuse the application's validated ModelSetup parser instead of maintaining
    # a trial-only model configuration or silently loading a mock provider.
    setups = ApplicationSetup._read_setups(values)
    if not setups:
        raise ValueError("TRIAL_MODELS_REQUIRED: configure AGENTOS_MODELS using the existing application format")
    ordered = sorted(setups, key=lambda setup: (-setup.priority, setup.provider, setup.models[0], setup.version))
    routes = {f"{setup.provider}/{model}": {"provider": setup.provider, "model": model, "version": setup.version}
              for setup in reversed(ordered) for model in setup.models}
    default = f"{ordered[0].provider}/{ordered[0].models[0]}"
    selected = (args.first_route or default, args.second_route or args.first_route or default)
    if any(route not in routes for route in selected):
        raise ValueError("TRIAL_ROUTE_NOT_CONFIGURED: select provider/model entries declared in AGENTOS_MODELS")
    return values, tuple(routes[route] for route in selected)


def _blueprint(routes, args):
    from contracts.resource import ModelDemand
    from support.acg.models import ACGBlueprint, StepNode
    from support.acg.planning import ACGResourcePlan, AgentBindingSpec, ModelRequirementSpec

    common = {"type": "object", "additionalProperties": False, "required": ["summary", "findings"],
              "properties": {"summary": {"type": "string"}, "findings": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False,
                  "required": ["issue", "evidence", "recommendation"], "properties": {
                      field: {"type": "string"} for field in ("issue", "evidence", "recommendation")}}}}}
    materials = (
        ("requirements", "review.requirements", "需求评审", "需求评审材料：为客户增加账单导出功能。范围为近三个月账单；要求两周内上线。材料只写了“导出应当很快”，未约定最大数据量、可接受耗时、访问权限或验收负责人。"),
        ("delivery", "review.delivery", "交付评审", "交付评审材料：账单导出已完成开发，测试覆盖正常下载和空账单。计划周五直接向全部客户发布；未提供大数据量测试、失败告警、灰度方案、回滚步骤和生产值守安排。"),
    )
    return ACGBlueprint(graphId="heterogeneous-review-trial", nodes=[
        StepNode(nodeId=key, name=title, goal=f"审查{title}材料，提取最多三个有原文依据的问题及建议",
                 capability=capability, inputSpec={"material": material}, outputSpec=common)
        for key, capability, title, material in materials
    ], edges=[], resourcePlan=ACGResourcePlan(
        bindings=tuple(AgentBindingSpec(stepId=key, plannedAgentId=f"trial:{key}") for key, *_ in materials),
        models=tuple(ModelRequirementSpec(stepId=key, demand=ModelDemand(
            allowedEndpointIds=[f"trial:model:{index}"], preferredModelIds=[f"{route['provider']}/{route['model']}"]
        )) for index, ((key, *_), route) in enumerate(zip(materials, routes))),
    ))


def _agents(calls, max_output_tokens):
    from service.agents import AgentOutput, AgentProfile, AgentRegistry, BaseAgent

    class RequirementsReviewer(BaseAgent):
        instruction = "你是需求评审员。关注范围、可测量的验收标准及责任边界。只返回符合给定 JSON schema 的对象。"

        async def run(self, context):
            started = monotonic()
            call = {"stepId": context.step.step_id, "attemptId": context.attempt_id,
                    "commitId": context.commit_id, "agentRegistration": context.agent_registration.model_dump(by_alias=True, mode="json")}
            calls.append(call)
            try:
                result = await context.model_runtime.generate_json(
                    prompt=context.step.input["material"], schema=context.step.output_spec,
                    system_prompt=self.instruction, commit_id=context.commit_id,
                    max_output_tokens=max_output_tokens,
                )
                call.update(status="completed", audit=result.audit_record())
                return AgentOutput(output=result.data, summary=result.data["summary"], modelInvocations=[result.audit_record()])
            except BaseException as exc:
                call.update(status="failed", errorCode=getattr(exc, "code", type(exc).__name__))
                raise
            finally:
                call["elapsedMs"] = round((monotonic() - started) * 1000)

    class DeliveryReviewer(RequirementsReviewer):
        instruction = "你是发布交付评审员。按照测试证据、发布风险、监控和回滚四项检查材料。只列原文能支持的缺口，只返回符合给定 JSON schema 的对象。"

    registry = AgentRegistry()
    for implementation, key in ((RequirementsReviewer, "requirements"), (DeliveryReviewer, "delivery")):
        registry.register(implementation(AgentProfile(
            agentId=f"trial:{key}", agentName=f"trial-{key}", domain="general",
            definitionVersion="1.0.0", executionMode="stateless", capabilities=[f"review.{key}"],
        )))
    return registry


def _observe_adapters(setup, routes, observations):
    """Observe exact adapter entries, including retries, without changing routing."""
    started = monotonic()
    active = 0
    seen = set()
    for route in routes:
        for adapter in setup.model_registry.resolve_candidates(**route):
            if id(adapter) in seen:
                continue
            seen.add(id(adapter))
            invoke = adapter.invoke
            provider = adapter.manifest.provider
            capability_id = adapter.manifest.capability_id

            async def observed(request, _invoke=invoke, _provider=provider, _capability=capability_id):
                nonlocal active
                active += 1
                call = {"ordinal": len(observations) + 1, "requestId": request.request_id,
                        "provider": _provider, "model": request.model, "capabilityId": _capability,
                        "startedMs": round((monotonic() - started) * 1000), "activeAtStart": active}
                observations.append(call)
                try:
                    response = await _invoke(request)
                    call.update(status="completed", usage=dict(response.usage))
                    return response
                except BaseException as exc:
                    call.update(status="failed", errorCode=getattr(exc, "code", type(exc).__name__))
                    raise
                finally:
                    active -= 1
                    call["finishedMs"] = round((monotonic() - started) * 1000)

            adapter.invoke = observed


async def _execute(args, environment, routes, blueprint, quota, output_dir):
    from adapters.model_compatibility import ModelCompatibilityRegistry
    from components.memory.store import MemoryStore
    from components.mission_manager.store import WorkflowRegistry
    from contracts.planning import PlannedTask, TaskImplementationBinding, TaskPlan
    from contracts.resource import ModelEndpointProfile
    from contracts.workflow import WorkflowDefinition, WorkflowStepDefinition
    from runtime.app_setup import ApplicationSetup
    from runtime.workflow_runtime import ExecutionRuntime
    from support.acg.capabilities import PlanningCapabilityDescriptor
    from support.acg.native_capabilities import build_default_capability_catalog
    from support.stores.sqlite_workflow_store import SQLiteWorkflowStore

    output_dir.mkdir(parents=True, exist_ok=False)
    # Isolate every default Runtime persistence port from the user's application.
    for name, filename in {
        "AGENTOS_LANGGRAPH_CHECKPOINT_DB": "checkpoints.sqlite3", "AGENTOS_EXECUTION_VALUE_DB": "values.sqlite3",
        "AGENTOS_CONTENT_MANIFEST_DB": "content.sqlite3", "AGENTOS_PROVENANCE_DB": "provenance.sqlite3",
        "AGENTOS_AUDIT_DB": "audit.sqlite3", "AGENTOS_COMMUNICATION_DB": "communication.sqlite3",
    }.items():
        os.environ[name] = str(output_dir / filename)
    calls, observations = [], []
    workflows = WorkflowRegistry()
    workflows.register(WorkflowDefinition(workflowId="heterogeneous-trial", name="异构执行实测", domain="general",
        runtimeEngine="acg", steps=[WorkflowStepDefinition(stepId="placeholder", name="placeholder", agentName="trial-requirements")]))
    capabilities = build_default_capability_catalog()
    for node in blueprint.nodes:
        capabilities.register(PlanningCapabilityDescriptor(capabilityId=node.capability, displayName=node.name,
            description=node.goal, outputContract=node.output_spec))
    runtime = ExecutionRuntime(agent_registry=_agents(calls, args.max_output_tokens), workflow_registry=workflows,
        workflow_store=SQLiteWorkflowStore(output_dir / "workflow.sqlite3"), memory_store=MemoryStore(),
        capability_catalog=capabilities, model_registry=ModelCompatibilityRegistry(), model_max_concurrency=max(4, args.model_concurrency))
    setup = ApplicationSetup.from_environment(environment, model_registry=runtime.model_registry)
    report = {"mode": "real-model-execution", "quota": quota.model_dump(by_alias=True, mode="json", exclude_none=True),
              "graph": blueprint.model_dump(by_alias=True, mode="json"), "logicalModelCalls": calls,
              "adapterInvocations": observations}
    run = None
    try:
        await setup.start()
        _observe_adapters(setup, routes, observations)
        for index, route in enumerate(routes):
            runtime.resource_plane.upsert_model_endpoint(ModelEndpointProfile(
                endpointId=f"trial:model:{index}", provider=route["provider"], model=route["model"],
                modelVersion=route["version"], quota=quota))
        mission = runtime.create_mission("分别审查需求和交付材料，给出有依据的问题和改进建议", workflow_id="heterogeneous-trial")
        plan = TaskPlan(missionId=mission.mission_id, nodes=tuple(PlannedTask(
            key=f"step:{node.node_id}", title=node.name, objective=node.goal,
            capabilityRequirements=(node.capability,)) for node in blueprint.nodes))
        mission.input.update(acgBlueprint=blueprint.model_dump(by_alias=True, mode="json"),
            taskPlan=plan.model_dump(by_alias=True, mode="json"), taskBindings=[TaskImplementationBinding(
                planNodeKey=f"step:{node.node_id}", acgNodeId=node.node_id
            ).model_dump(by_alias=True, mode="json") for node in blueprint.nodes])
        runtime.workflow_store.save_mission(mission)
        _, run = runtime.prepare_run(mission.mission_id)
        await runtime.execute_prepared_run(run.run_id)
    except Exception as exc:
        report["errorCode"] = getattr(exc, "code", type(exc).__name__)
    finally:
        await setup.close()
        if run is not None:
            saved = runtime.workflow_store.get_run(run.run_id)
            report.update(runId=saved.run_id, missionId=saved.mission_id, status=saved.status.value,
                bindingRequirements=saved.execution_state.get("bindingRequirements", {}),
                executionBindings=saved.execution_state.get("executionBindings", {}), outputs={
                    step: runtime.execution_value_store.get_output(run_id=saved.run_id, output_ref=ref)
                    for step, ref in saved.execution_state.get("outputRefs", {}).items()})
        report["observedPeakAdapterConcurrency"] = max((call["activeAtStart"] for call in observations), default=0)
        report["quotaSettlements"] = [dict(event.metadata, resourceId=event.resource_id,
            occurredAt=event.occurred_at.isoformat()) for event in runtime.resource_plane.audit_events(limit=100)
            if event.kind == "model_quota_settled"]
        (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report.get("status", "failed"), "report": str(output_dir / "report.json"),
                      "adapterInvocations": len(observations), "observedPeakAdapterConcurrency": report["observedPeakAdapterConcurrency"],
                      "errorCode": report.get("errorCode")}, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "completed" and "errorCode" not in report else 1


def main() -> int:
    args = _arguments()
    try:
        from contracts.resource import ModelQuotaPolicy

        environment, routes = _configuration(args)
        quota = ModelQuotaPolicy(scope=args.quota_scope.strip(), maxConcurrency=args.model_concurrency,
            requestsPerMinute=args.requests_per_minute, tokensPerMinute=args.tokens_per_minute)
        blueprint = _blueprint(routes, args)
        if not args.execute:
            print(json.dumps({"mode": "dry-run", "networkRequests": 0, "selectedRoutes": routes,
                "quota": quota.model_dump(by_alias=True, mode="json", exclude_none=True),
                "graph": blueprint.model_dump(by_alias=True, mode="json")}, ensure_ascii=False, indent=2))
            return 0
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        output_dir = (args.output_dir or PROJECT_ROOT / "data/heterogeneous-trials" / stamp).resolve()
        return asyncio.run(_execute(args, environment, routes, blueprint, quota, output_dir))
    except Exception as exc:
        # Config and runtime errors are reduced to stable codes: never echo a
        # dotenv line, URL, credential, provider response or arbitrary exception.
        code = str(exc).split(":", 1)[0] if str(exc).split(":", 1)[0].isupper() else type(exc).__name__
        print(json.dumps({"status": "failed", "errorCode": code}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
