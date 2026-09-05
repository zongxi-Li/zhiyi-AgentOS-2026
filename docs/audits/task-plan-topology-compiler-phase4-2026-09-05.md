# TaskPlan Topology Compiler Phase 4

## 1. Baseline

Phase 4 began from 55 passing Planner tests and 92 passing combined Planner, Runtime ACG, and architecture tests. Repository search confirmed `_is_dependency_cycle_error` and string-driven topology repair were already removed; the Phase 3 report recommendation was corrected to match code.

## 2. Files Changed

- Added `topology/binding_solver.py`.
- Extended internal models and structured conflicts for binding candidates, scores, rejections, solver audit, search exhaustion, and search counters.
- Replaced the compiler's first-feasible binding loop with one bounded solver call.
- Extended topology compiler tests and this report.

No public TaskPlan or DB schema, Runtime, Scheduler, frontend, ACGBuilder, repair policy, or Phase 3 patch contract changed.

## 3. Previous Greedy Algorithm

The old compiler selected the nearest preceding producer that did not immediately close a reverse path, then accepted that local decision permanently. It had no requirement ordering, downstream feasibility check, or backtracking. That path has been removed from `TaskPlanTopologyCompiler`; final assignment now has one solver implementation.

## 4. Capability Binding Candidate Model

Internal models now include `CapabilityBindingCandidate`, `CapabilityBindingScore`, `CapabilityBindingRejection`, and `CapabilityBindingAudit`. `CapabilityRequirement` remains immutable and separate from selected concrete `TopologyEdge` bindings.

## 5. Stable Candidate Scoring

Candidates use an ordered dataclass tuple: explicit model dependency rank, preceding rank, ordinal distance, and producer semantic key. No task-title similarity, embedding, LLM judgment, or float score is used. Candidate input collection order and catalog-map insertion order cannot decide the result because every list is explicitly sorted. Explicit task ordinal remains a legitimate input signal.

## 6. Global Binding Solver

The solver materializes all ordered candidates, orders requirements using MRV (number of currently viable base-graph candidates, consumer key, requirement ID), and performs deterministic DFS. Every tentative catalog edge is incrementally cycle-pruned. If a later requirement has no assignment, DFS removes the prior edge and tries its next stable candidate. The complete CandidateTopology still passes the authoritative global validator afterward.

## 7. Search Budget

Default `max_search_states` is 512. Every tentative partial assignment consumes a state. Exceeding the budget raises `CAPABILITY_BINDING_SEARCH_EXHAUSTED`; there is no greedy fallback. The bound is injectable for tests without adding environment configuration.

## 8. Binding Conflict Model

When every requirement has producers but no global DAG-preserving assignment exists, the solver raises `CAPABILITY_BINDING_CONFLICT`, not `DEPENDENCY_CYCLE`. Conflict data contains requirements, candidate producer lists, candidate-level rejection reason/path, representative cycle edges with provenance, and explored-state count. Phase 3 repair eligibility remains unchanged, so binding conflicts do not invoke LLM repair.

## 9. Audit Extension

`CapabilityBindingAudit` records stable candidate order and score per requirement, selected bindings, rejected candidates, states explored, and backtrack count. It is nested in the existing Planner-internal compilation audit; no persistence schema was changed. Successful catalog edges retain `capability_catalog/rebindable/requirement_id` provenance.

## 10. Greedy Trap Regression

A regression constructs two requirements where the first locally preferred assignment makes every candidate for the second cyclic. The solver records downstream unsatisfied, backtracks, chooses the alternate producer, and returns a global solution.

## 11. Determinism / Ordering Tests

Tests verify reversed candidate collection order produces the same binding and five repeated compiles produce an identical `(requirement_id, producer, consumer)` fingerprint. Cycle-path traversal also uses stable successor ordering. Task ordinal is intentionally not shuffled because it is a declared score input.

## 12. No-solution Conflict

The no-solution test returns `CAPABILITY_BINDING_CONFLICT` with a rejection for every producer and a concrete reverse path explaining each rejection. No partial binding is returned as success.

## 13. Search Exhaustion

An injected one-state budget forces the second attempted partial assignment to raise `CAPABILITY_BINDING_SEARCH_EXHAUSTED`, reporting two explored states and never falling back.

## 14. Case B

The industrial storage Case B now explores all eligible producer instances. If none can satisfy the requirement without closing the model path, the structured binding conflict includes the rejected catalog candidate edge and the complete model path with original provenance. The former generic `cannot bind required capability dependency` outcome is gone from the active compiler.

## 15. Test Results

```text
Planner baseline:                         55 passed
Planner after Phase 4:                    60 passed
Planner + Runtime ACG + architecture:     97 passed
```

Final exact counts are recorded from the validation run; existing warnings are legacy AgentNode deprecations.

## 16. Performance Observations

Simple single-producer requirements explore one state each and do not backtrack. The greedy-trap regression explores a small bounded search and records at least one backtrack. The hard ceiling of 512 prevents combinatorial runaway for larger plans. No benchmark or external solver was introduced.

## 17. Remaining Risks

- Ordinal distance remains a heuristic and deliberately affects results.
- Scope, branch, stage, and material compatibility are not explicit enough in the current Task model to score safely.
- The fixed search budget may require Planner-level configuration after production telemetry exists.
- Compilation audit remains internal rather than persisted.
- Binding conflicts remain ineligible for LLM relation repair by Phase 4 design.

## 18. Next Phase

The next phase should be convergence: route template, fallback, and `apply_task_plan_patch()` through the same topology validation contract, persist a safe compilation audit using existing trace facilities, and verify ACGBuilder preserves every validated semantic dependency during lowering.
