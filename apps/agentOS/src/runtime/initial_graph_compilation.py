"""Pure reconstruction from an accepted Record. No Runtime or mutable registry reads."""
from datetime import datetime, timezone
import random
import hashlib
from pathlib import Path
from types import SimpleNamespace

from contracts import stable_checksum
from contracts.graph_materialization import InitialGraphContent
from contracts.initial_planning import InitialPlanningSourceProvenance
from contracts.planning import TaskPlan
from components.planner.topology import validate_task_plan_for_execution, EdgeOrigin
from components.planner.acg_lowerer import ACGLowerer
from components.planner.lowering_input import build_template_lowering_input, build_acg_lowering_input
from components.planner.cognitive_router import CognitiveRouter
from components.planner.algorithms import PlanningVariantGenerator
from components.planner.service import PlanningEngine
from service.agents import AgentRegistry
from service.agents.base import AgentProfile
from support.acg.capabilities import CapabilityCatalog
from runtime.human_review_policy import review_lowering_input


INITIAL_MATERIALIZATION_POLICY = "initial-materialization-v1"


def initial_recipe_fingerprint():
    """Identify this stage's derivation/projection in addition to sealed C2A-1 compilers."""
    root = Path(__file__).resolve().parents[1]
    paths = ("runtime/initial_graph_compilation.py", "runtime/graph_materialization.py",
             "runtime/graph_activation.py", "runtime/workflow_runtime.py", "components/planner/service.py",
             "runtime/human_review_policy.py")
    return stable_checksum({path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths})


def compile_initial_content(record, *, timestamp=None):
    """Only clock metadata is supplied by the host, then retained in the journal.

    The caller must revalidate current authority/sources before persisting this
    result. This function cannot issue a receipt or mutate any official state.
    """
    recipe = initial_recipe_fingerprint()
    origin = InitialPlanningSourceProvenance.model_validate_json(record.source_provenance.model_dump_json(by_alias=True))
    plan = TaskPlan.model_validate_json(record.proposal_payload.model_dump_json(by_alias=True))
    catalog = CapabilityCatalog(d.model_copy(deep=True) for d in origin.catalog)
    plan = validate_task_plan_for_execution(capability_catalog=catalog, mission_id=plan.mission_id,
        nodes=plan.nodes, relations=plan.relations, control_policies=plan.control_policies,
        expected_artifacts=plan.expected_artifacts, metadata=plan.metadata,
        plan_version=plan.plan_version, relation_origin=EdgeOrigin.PLAN_PATCH)
    # Initial activation is deliberately limited to the same no-control DAG
    # contract as the existing revision materialization.
    if plan.control_policies:
        raise ValueError("initial control graph materialization is unsupported")
    if origin.semantic_profile is None:
        lowering = build_template_lowering_input(workflow=origin.workflow, task_plan=plan)
        lowering = review_lowering_input(lowering, origin.lowering_options.get('reviewPolicy'))
        blueprint = ACGLowerer().lower(lowering)
    else:
        agents = AgentRegistry()
        for profile in origin.agent_profiles:
            agents.register(SimpleNamespace(profile=AgentProfile.model_validate(profile)))
        router = CognitiveRouter(agents, catalog)
        # Reuse the existing pure final-plan rebinding method; no engine/model
        # construction, parser or decomposer is involved.
        profile, _ = PlanningEngine._rebind_profile_to_task_plan(
            SimpleNamespace(capability_catalog=catalog, cognitive_router=router),
            profile=origin.semantic_profile, task_plan=plan, domain=origin.workflow.domain)
        options = origin.lowering_options
        variants = PlanningVariantGenerator(capability_catalog=catalog, cognitive_router=router).generate(
            profile=profile, domain=origin.workflow.domain,
            diversity=options["planningDiversity"], seed=options["planningSeed"])
        candidates = []
        for variant in variants.variants:
            if variant.network.unresolved_capabilities or variant.network.over_budget:
                continue
            lowering = build_acg_lowering_input(mission_id=record.mission_id, profile=profile,
                network=variant.network, task_plan=plan, capability_catalog=catalog, variant_id=variant.variant_id)
            lowering = review_lowering_input(lowering, origin.lowering_options.get('reviewPolicy'))
            candidate = ACGLowerer().lower(lowering)
            candidates.append((PlanningEngine._score_candidate(plan, candidate), candidate, lowering))
        if not candidates:
            raise ValueError("no legal frozen initial binding candidate")
        best = max(item[0] for item in candidates)
        tied = [item for item in candidates if item[0] == best]
        _, blueprint, lowering = random.Random(options["planningSeed"]).choice(tied) if len(tied) > 1 else tied[0]
    if any(node.node_type.value == "control" for node in blueprint.nodes):
        raise ValueError("initial control graphs require a later contract")
    by_id = {p.get("agentId") or p["agentName"]: p for p in origin.agent_profiles}
    for binding in blueprint.resource_plan.bindings:
        agent = by_id.get(binding.planned_agent_id)
        if agent is None or not agent["enabled"] or not set(binding.required_capabilities) <= set(agent["capabilities"]):
            raise ValueError("initial logical binding exceeds frozen profiles")
    blueprint.graph_id = "initial_" + stable_checksum({"commit": record.commit_id,
        "source": origin.static_fingerprint, "policy": INITIAL_MATERIALIZATION_POLICY, "recipe": recipe})[:40]
    blueprint.version = 1
    # Edges and metadata are compiler outputs, never new planning decisions.
    for edge in blueprint.edges:
        edge.edge_id = "initial_edge_" + stable_checksum({"graph": blueprint.graph_id,
            "source": edge.source_id, "target": edge.target_id, "type": edge.edge_type.value})[:32]
    blueprint.created_at = blueprint.updated_at = timestamp or datetime.now(timezone.utc)
    blueprint.metadata["initialCommitId"] = record.commit_id
    blueprint.metadata["initialSourceFingerprint"] = origin.static_fingerprint
    blueprint.metadata["initialMaterializationPolicy"] = INITIAL_MATERIALIZATION_POLICY
    blueprint.metadata["initialCompilationRecipe"] = recipe
    return InitialGraphContent(plan=plan, bindings=lowering.implementation_bindings, blueprint=blueprint)
