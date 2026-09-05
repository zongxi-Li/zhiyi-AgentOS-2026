# TaskPlan Topology Compiler Phase 1-2

## 1. Baseline

Implementation was based on `task-plan-topology-final-source-audit-2026-09-05.md`. Baseline Planner result was 47 passing tests. The working tree already contained the earlier concurrency, secret-mount, and bounded relation-repair changes; those changes were preserved.

## 2. Files Changed

- Added `components/planner/topology/model.py`, `compiler.py`, `validator.py`, `errors.py`, and package exports.
- Updated `TaskDecomposer._to_plan()` to delegate dependency topology concerns to `TaskPlanTopologyCompiler`.
- Added `test_topology_compiler.py` with internal provenance and real Case B coverage.
- Added this implementation report.

No public API, persistent TaskPlan schema, database schema, ACGBuilder, Runtime, Scheduler, or frontend contract was changed in this phase.

## 3. New Internal Topology IR

The internal IR contains `TopologyEdge`, `CapabilityRequirement`, `CandidateTopology`, and `TopologyCompileResult`. `EdgeOrigin` distinguishes model, capability catalog, terminal connector, and reserved user-declared sources. `EdgeMutationPolicy` distinguishes fixed, repairable, rebindable, and regenerable edges.

This provenance is Planner-internal. `TopologyEdge.to_relation()` deliberately strips provenance when creating the unchanged public `TaskPlanRelation`.

## 4. Compiler Boundary

The dynamic planning path is now:

```text
TaskDecomposer normalizes tasks
  -> parses relation/control proposals
  -> TaskPlanTopologyCompiler.compile
       -> derive every semantic edge
       -> CandidateTopology
       -> unified validation
       -> strip provenance
  -> TaskPlan (second contract guard)
```

`_to_plan()` retains task/content normalization but no longer independently calls reverse normalization, capability completion, or terminal completion. The legacy helpers remain temporarily for compatibility/reference but are not a second active dynamic topology path.

## 5. Capability Requirement Representation

Each catalog dependency is first materialized as `CapabilityRequirement`, including producer/consumer capability, consumer task key, stable requirement ID, and all candidate producer task keys. The existing binding heuristic remains: preceding candidates, nearest preceding first, remaining candidates, first feasible candidate. A selected binding becomes a rebindable capability-catalog `TopologyEdge`.

## 6. Edge Provenance

- Model proposal: `origin=model`, `mutation_policy=repairable`, original relation index retained.
- Catalog concrete binding: `origin=capability_catalog`, `mutation_policy=rebindable`, requirement ID retained.
- Terminal connection: `origin=terminal_connector`, `mutation_policy=regenerable`.

Duplicate edges are normalized before final validation. Cycle paths map back to concrete `TopologyEdge` objects, so error handling can inspect origin and mutation policy.

## 7. Candidate Topology Validation

Validation occurs after model, catalog, and terminal edges all exist. It checks node existence, self-dependency, one global static DAG, and control-policy references. TaskPlan validation remains as a second public-contract guard. Closed cycle paths are rotated to a stable lexicographically smallest task-key origin for deterministic audit output.

## 8. Case A Regression

Existing staged direct-cycle repair remains active. `TopologyCompileError` is accepted by the short-term compatibility adapter that recognizes dependency-cycle failures, so the flow remains first compile, bounded relations cycle repair, then full recompile. Frozen task identities are unchanged.

## 9. Case B Regression

Tests cover both the abstract `A -> B -> C -> A` scenario and the real storage-planning path. The resulting `TopologyConflict` contains the catalog edge as `capability_catalog/rebindable` and every original relation as `model/repairable`. The error is no longer limited to an unstructured `cannot bind` message.

## 10. Test Results

```text
Planner baseline:                         47 passed
Planner after Phase 1-2:                  51 passed
Planner + Runtime ACG + architecture:     88 passed
```

The eight warnings are pre-existing legacy AgentNode deprecation warnings.

## 11. Remaining Legacy Logic

The old `_complete_capability_dependencies`, `_connect_terminal_results`, `_find_dependency_path`, and `_find_dependency_cycle` helpers remain in `TaskDecomposer` but are no longer invoked by `_to_plan()`. Template, fallback, and `apply_task_plan_patch` were intentionally not migrated in this phase. The existing string compatibility check for `dependency cycle` remains and now also accepts `TopologyCompileError`; a later phase should drive repair directly from `TopologyConflict.code`.

## 12. Risks

- Capability binding remains greedy and task-order-sensitive; no backtracking was introduced.
- When no candidate binding avoids a reverse path, the compiler materializes the preferred concrete binding so unified validation can return the complete provenance-bearing cycle. It does not silently accept that topology because validation immediately fails.
- Public TaskPlan snapshots do not retain internal provenance by design; compilation audit persistence is a later phase.
- Template, fallback, and patch paths still rely on the TaskPlan contract rather than this compiler.
- ACGBuilder continues to project semantic dependencies into execution controls and communication edges; its semantics were not changed.

## 13. Next Phase Recommendation

Phase 3 should replace string-driven repair with `TopologyConflict.code`, include immutable/repairable/rebindable edge details in the bounded repair prompt, and persist a safe compilation audit. Phase 4 can then introduce stable candidate scoring and bounded backtracking without changing the Phase 1-2 compiler boundary.
