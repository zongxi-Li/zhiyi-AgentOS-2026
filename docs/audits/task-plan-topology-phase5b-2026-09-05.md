# TaskPlan Topology Phase 5B

## 1. Baseline

Phase 5B started on `master` at `740f7cf`, with the dirty worktree preserved. The Phase 5A baseline was 70 Planner tests, 140 combined relevant tests, passing compileall, and passing `git diff --check`.

## 2. Files Changed

- Added `components/planner/acg_semantic_validator.py` and its Builder integration tests.
- Added `topology/audit.py` for safe summaries and stable SHA-256 fingerprints.
- Extended the existing topology gate/error carrier, Planner result, Runtime Trace projection, and graph-patch metadata.
- Made identity-only catalog context injectable while preserving an explicitly marked compatibility default.
- Added lowering, audit, trace, catalog-context, and custom-catalog patch tests.

No public TaskPlan schema, database schema, solver algorithm, repair policy, LLM call, Scheduler policy, Runtime state machine, or frontend was changed.

## 3. Semantic Lowering Contract

For every validated `depends_on` relation `source -> target`, the StepNode whose `metadata.taskPlanKey` is `source` must reach the StepNode mapped to `target` through one or more ACG `DEPENDENCY` edges. The project direction is prerequisite source to dependent target: Builder populates `data_dependencies[target]` from `source`, and ACGGraphCompiler turns `DEPENDENCY source -> target` into ready-set predecessors. Direct edges are not required because controls may be inserted.

## 4. Happens-Before Edge Classification

| Edge type | Happens-before proof | Evidence |
| --- | --- | --- |
| `DEPENDENCY` | Yes | ACGGraphCompiler selects only this type for `ACGExecutionGraph.edges`; ready-set reads those predecessors |
| `CONTROL_FLOW` | No for ordinary static dependency proof | Compiled into typed control rules/loop cases, not normal ready-set edges |
| `COMMUNICATION` | No | Defines producer/consumer channels and allowed fields |
| `READ` / `WRITE` | No | Memory access semantics |
| `SUPPORT` | No | Evidence access semantics |
| `EXECUTION` | No | Agent/skill resource binding to a StepNode |

Loop control is validated separately rather than treating `CONTROL_FLOW` as a static semantic predecessor.

## 5. ACG Preservation Validator

`validate_acg_semantic_preservation()` is a read-only guard. It verifies a one-to-one `taskPlanKey -> StepNode` mapping, checks every semantic dependency by deterministic DFS over `DEPENDENCY` edges, detects missing/reversed lowering, and checks that every VerificationLoopPolicy became a LOOP ControlNode. It is called after dynamic build validation and after template/finalize bindings. It does not duplicate Builder logic.

## 6. Parallel / Join Verification

The fork/join regression builds `A -> B`, `A -> C`, `B -> D`, and `C -> D`. All four semantic relations remain reachable across inserted parallel and consensus/join controls. The test also proves neither direct `B -> C` nor `C -> B` dependency is introduced, so the guard does not force false serialization.

## 7. Verification Loop Verification

The loop regression retains the static `draft -> verify` DAG relation and proves its execution reachability. A corresponding LOOP ControlNode must exist, while `verify -> draft` must not appear in TaskPlan relations. Feedback remains control topology only.

## 8. Compilation Audit Projection

Safe audit fields include compiler version, producer kind, catalog source/fingerprint, coverage mode, task/edge counts, topology fingerprint, capability requirements, selected bindings, bounded-search counters, repair attempt/operation summaries, status, and structured conflicts. Dynamic success is projected to TaskDecomposer audit, PlanResult decision, Blueprint metadata, Runtime execution state, and the existing Planner decision Trace. Patch success is projected to replacement-run execution state. Failure audit rides the existing exception/Planner-failed Trace route. No prompt, source material, raw model response, or exception text is included.

## 9. Topology Fingerprint

The fingerprint uses canonical JSON with sorted semantic task keys, internal semantic edges, control-policy identities, selected bindings, catalog fingerprint, and compiler version, then SHA-256. It never uses Python `hash()` and does not alter runId, taskId, graphVersion, or execution identity. Tests prove stability across reordered task input to the audit builder.

## 10. Catalog Context Matrix

| Producer | Catalog source | Injected | Default fallback | Auditable |
| --- | --- | --- | --- | --- |
| Dynamic | PlanningEngine/TaskDecomposer catalog | Yes | Engine construction only | fingerprint + `injected` |
| Template | SemanticPlanner catalog | Yes | Engine construction only | fingerprint + `injected` |
| Fallback/compatibility | SemanticPlanner/TaskDecomposer catalog | Yes | Engine construction only | fingerprint + `injected` |
| WorkflowRuntime patch | Runtime active catalog | Yes | No | fingerprint + `injected` |
| IdentityProjectionBridge patch | Constructor catalog | Optional | Yes | `injected` or `default_compatibility` |
| PlannerIdentityBridge | Constructor catalog | Optional | Yes | `injected` or `default_compatibility` |
| Direct compatibility `apply_task_plan_patch` | Function argument | Optional | Yes | `injected` or `default_compatibility` |

Catalog fingerprint covers capability ID, required dependencies, and optional dependencies—the fields that affect topology.

## 11. Existing-plan Compatibility Policy

Dynamic proposal mode records `capabilityCoverageMode=complete`. Existing template, fallback, patch, and identity ingestion records `declared_producers_only`: catalog requirements with no declared producer remain intentionally unmaterialized, preserving Phase 5A behavior and task identity. The shared authority is the IR, solver, validator, and conflict contract—not identical completeness policy.

## 12. Trace / Provenance Integration

The existing `TraceStore` Planner decision/failure events and existing Blueprint/Runtime metadata are used. There is no parallel provenance subsystem or DB migration. The Runtime event whitelist admits only the already-built topology audit object; its builder has a closed safe schema. Regular transient progress remains scalar-only.

## 13. Regression Tests

Tests cover direct dependency, transitive chain, parallel/join, verification loop, deliberately dropped dependency, stable fingerprints, successful audit contents, structured failure audit without raw model content, compatibility default marker, successful Runtime Trace projection, graph-patch audit projection, and Runtime patch validation against a custom injected catalog. Existing Planner, Builder, Runtime ACG, architecture, patch, and identity tests remain included.

## 14. Test Results

```text
Planner:                         78 passed
Combined relevant:             154 passed
Python compileall:             pass
git diff --check:              pass
```

Warnings are pre-existing legacy AgentNode deprecations.

## 15. Performance

The guard builds one adjacency map and runs one DFS per semantic dependency: `O(E_semantic * (V_acg + E_dependency))`, appropriate for current plans with tens of nodes. Fingerprinting is linearithmic due to canonical sorting. No transitive-closure framework or external solver was introduced.

## 16. Remaining Risks

- Explicit Blueprint compatibility input is not Builder output and therefore is not claimed as lowering proof; its separate binding validation remains unchanged.
- Identity-only constructors may still use the compatibility default, but this is now visible in audit instead of indistinguishable from injection.
- Failure audit can be persisted only when a caller has an existing Trace/run context; standalone component calls receive it on `TopologyCompileError.audit`.
- The safe audit is metadata rather than a new typed public contract to avoid TaskPlan/DB schema changes.

## 17. Final Architecture Verdict

`TaskPlanTopologyCompiler` remains semantic topology authority. `ACGBuilder` remains deterministic lowering. `validate_acg_semantic_preservation()` is the post-lowering correctness guard. Existing Trace/metadata explains compilation without retaining sensitive model content. Scheduler remains resource scheduling and Runtime remains execution state. All Phase 5B acceptance boundaries are satisfied without changing topology algorithms or execution semantics.
