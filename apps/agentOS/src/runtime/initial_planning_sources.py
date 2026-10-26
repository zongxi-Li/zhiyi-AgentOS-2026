"""Bounded, read-only capture of initial compiler inputs; no registry authority."""
import hashlib
import json
from pathlib import Path

from contracts.initial_planning import InitialCompilationPolicy, InitialPlanningSourceProvenance
from contracts.mission_semantic import run_intent_basis
from components.planner.topology import TOPOLOGY_COMPILER_VERSION
from components.executor.compiler import ACGGraphCompiler


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _check_snapshot_content(value):
    """Reject credential-bearing configuration rather than silently redacting semantics."""
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).replace("_", "").replace("-", "").lower()
            if normalized in {"apikey", "accesstoken", "refreshtoken", "authorization", "password",
                              "clientsecret", "privatekey", "credentials"}:
                raise ValueError("credential-bearing compilation source is unsupported")
            _check_snapshot_content(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_snapshot_content(item)


def compilation_policy():
    # Version labels plus implementation identities: a forgotten version bump
    # must not make changed compiler code equivalent to accepted input.
    from components.planner.topology.binding_solver import CapabilityBindingSolver
    root = Path(__file__).resolve().parents[1]
    paths = {"topology": "components/planner/topology/compiler.py",
        "bindingSolver": "components/planner/topology/binding_solver.py",
        "lowerer": "components/planner/acg_lowerer.py",
        "graphCompiler": "components/executor/compiler.py",
        "routing": "components/planner/cognitive_router.py",
        "loweringInput": "components/planner/lowering_input.py"}
    groups = {name: [root / path] for name, path in paths.items()}
    groups["topology"] = sorted((root / "components/planner/topology").rglob("*.py"))
    groups["graphCompiler"].append(root / "contracts/compiled_acg.py")
    groups["lowerer"].extend([root / "support/acg/schema.py", root / "support/acg/planning.py"])
    groups["routing"].extend([root / "components/planner/algorithms.py", root / "support/acg/semantic_profile.py"])
    identities = {name: digest({path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in files}) for name, files in groups.items()}
    return InitialCompilationPolicy(versions={"topology": TOPOLOGY_COMPILER_VERSION,
        "bindingSolver": f"capability-binding-v1:{CapabilityBindingSolver().max_search_states}",
        "lowerer": "taskplan-lowering-v1", "graphCompiler": str(ACGGraphCompiler.package_version),
        "routing": "cognitive-routing-v1", "acceptance": "initial-acceptance-v1"},
        implementations=identities)


def capture_initial_sources(provider, runtime_fingerprint):
    runtime, run = provider.runtime, provider.run()
    basis, scope = run_intent_basis(run), run.execution_scope
    if basis is None or scope is None or basis.source_type != "SEMANTIC":
        raise ValueError("initial capture requires formal basis and scope")
    runtime.plugin_scope_resolver.validate_snapshot(scope)
    workflow = runtime._workflow_for_run(run).model_copy(deep=True)
    from service.agents.base import AgentProfile
    profiles = [AgentProfile.model_validate(a.profile.model_dump(mode="json", by_alias=True))
                for a in runtime.plugin_scope_resolver.scoped_agents(scope).all()]
    catalog = runtime.plugin_scope_resolver.scoped_catalog(scope)
    from runtime.human_review_policy import review_policy
    review = review_policy(run.review_mode)
    repositories = getattr(runtime.identity_lifecycle, "repositories", None)
    if repositories is None:
        raise ValueError("trusted Identity repository required for initial capture")
    identity = repositories.task_plans.latest(run.mission_id)
    identity_body = identity.model_dump(mode="json", by_alias=True) if identity is not None else None
    body = dict(sourceRunId=run.run_id, missionId=run.mission_id, missionRevision=basis.source_revision,
        basis=basis, scope=scope, workflow=workflow, runDomain=run.domain,
        semanticProfile=(provider.initial_provenance.semantic_profile.model_copy(deep=True)
            if provider.initial_provenance is not None and provider.initial_provenance.semantic_profile is not None else None),
        agentProfiles=[p.model_dump(mode="json", by_alias=True) for p in profiles],
        catalog=[d.model_copy(deep=True) for d in catalog.available()],
        validationCatalog=[d.model_copy(deep=True) for d in runtime.capability_catalog.available()],
        identitySnapshot=identity_body, identityFingerprint=digest(identity_body),
        materialRefs=run.input.get("materialRefs") or (), inputFingerprint=digest(run.input),
        runtimeFingerprint=runtime_fingerprint,
        loweringOptions={"planningSeed": run.planning_seed, "planningDiversity": run.planning_diversity,
                         "capabilityProfile": run.execution_state.get("requestedCapabilityProfile"),
                         **({'reviewPolicy': review} if review else {})},
        policy=compilation_policy(), staticFingerprint="0" * 64)
    # Compute over the canonical typed representation, then validate the seal.
    # model_construct is never returned and never crosses the service boundary.
    from pydantic import TypeAdapter
    fields = {name: TypeAdapter(field.annotation).validate_python(body[field.alias or name])
              for name, field in InitialPlanningSourceProvenance.model_fields.items() if name != "version"}
    provisional = InitialPlanningSourceProvenance.model_construct(**fields)
    serialized = provisional.model_dump(mode="json", by_alias=True)
    if len(json.dumps(serialized, ensure_ascii=False)) > 2_000_000:
        raise ValueError("initial source exceeds bounded snapshot policy")
    _check_snapshot_content(serialized)
    return InitialPlanningSourceProvenance.model_validate({**serialized,
        "staticFingerprint": provisional.content_fingerprint()})
