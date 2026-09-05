# TaskPlan Topology Convergence Phase 5A

## 1. Baseline

The implementation started on branch `master` at `740f7cf`. The recorded Phase 4 baseline was 60 passing Planner tests and 97 passing combined Planner, Runtime ACG, and architecture tests. The pre-existing dirty worktree was preserved.

## 2. TaskPlan Producer Matrix

| Producer | Entry | Relation source | Capability completion before Phase 5A | Terminal completion before Phase 5A | Control policies | Validation before Phase 5A | LLM repair | Side effect / consumer |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Dynamic | `TaskDecomposer._to_plan()` | LLM proposal | Compiler | Compiler | LLM proposal | `TaskPlanTopologyCompiler` | One bounded proposal patch only | `ACGBuilder.build()` |
| Template | `SemanticPlanner.plan_template()` | Workflow declaration | None | None | None in current WorkflowDefinition | Public schema only | No | `ACGBuilder.build_template()` |
| Deterministic fallback | `TaskDecomposer._fallback()` | Capability catalog | Catalog relations | None | None | Public schema only | No | Dynamic Builder path |
| Compatibility | `SemanticPlanner.plan_capabilities()` | Capability catalog | Catalog relations | None | None | Public schema only | No | Component Builder consumers |
| Plan patch | `apply_task_plan_patch()` | Existing plan plus explicit patch | None | None | Existing plan | Public schema only | No | Runtime/identity persistence |
| Identity tree compatibility | `PlannerIdentityBridge.record_task_tree()` | Node sequence, no relations | None | None | None | Public schema only | No | TaskPlan persistence |

## 3. Files Changed

- Extended the existing topology model, compiler, solver exports, and tests.
- Added `topology/gate.py`, a thin shared ingestion boundary that delegates all semantics to the existing compiler.
- Routed template, fallback, compatibility, patch, and identity-tree production through that gate.
- Removed the now-unused duplicate dependency completion, path/cycle, reverse normalization, and terminal helpers from `TaskDecomposer`.
- Passed Runtime's injected capability catalog to graph-patch validation.

No public TaskPlan schema, DB schema, ACGBuilder lowering, Runtime/Scheduler execution semantics, frontend, Phase 3 repair contract, or Phase 4 solver algorithm changed.

## 4. Shared Semantic Validation Gate

`validate_task_plan_for_execution()` accepts plan fields before public `TaskPlan` construction, invokes `TaskPlanTopologyCompiler.validate_existing_plan()`, and constructs a TaskPlan only after successful compilation. This ordering is necessary because the public Pydantic model otherwise reduces a cycle to a generic validation error before topology provenance can be attached. Proposal and existing-plan entry points share `_compile()`, `CandidateTopology`, `CapabilityBindingSolver`, `validate_candidate()`, and `TopologyConflict`.

## 5. Dynamic Path

Dynamic planning remains proposal compilation through `TaskPlanTopologyCompiler.compile()`. Model relations remain `model/repairable`; direct reverse normalization, requirement materialization, bounded binding, terminal generation, final validation, and the existing one-shot structured LLM patch contract remain intact. It is not converted into an unvalidated TaskPlan followed by validation.

## 6. Template Path

`plan_template()` now sends declared nodes and relations through the shared gate before `PlanningEngine` can call `build_template()`. The current WorkflowDefinition has no template control-policy field. Declared relations are `template_declared/fixed`; conflicts propagate as `TopologyCompileError.conflict`, and no LLM repair path is available. Task identity is unchanged. Historical templates that omit a catalog prerequisite remain compatible: the gate binds requirements only when a producer task exists in the declared plan and never invents template tasks.

## 7. Fallback / Compatibility Path

Both the production degraded `_fallback()` and `plan_capabilities()` use `fallback_generated/fixed` relations and the shared compiler. `record_task_tree()` is also converged before persistence. These deterministic paths have no repair contract and make zero LLM calls. Nodes without `capabilityRequirements` still receive DAG/control/terminal validation but create no capability requirement.

## 8. TaskPlan Patch Path

`apply_task_plan_patch()` first applies retirement, replacement, additions, and relations to local collections. It then invokes the gate with the resulting fields and the prior control policies. Patch relations and surviving prior relations are intentionally classified `plan_patch/fixed`: this records the candidate revision boundary and ensures none can be silently removed or reversed. Runtime supplies its active catalog; compatibility callers use the default catalog.

## 9. Provenance Policies by Producer

| Source | Origin | Mutation policy | Reason |
| --- | --- | --- | --- |
| Dynamic proposal | `model` | `repairable` | Only Phase 3's bounded proposal repair may edit it |
| Template declaration | `template_declared` | `fixed` | Author-authored business dependency |
| Deterministic fallback/compatibility | `fallback_generated` | `fixed` | Deterministic output has no legal repair protocol |
| Patched semantic revision | `plan_patch` | `fixed` | Explicit plan revision must fail rather than be rewritten |
| Selected requirement binding | `capability_catalog` | `rebindable` | Concrete producer choice remains solver-owned |
| Generated sink connection | `terminal_connector` | `regenerable` | Compiler-owned derived connector |

## 10. Structured Conflict Propagation

All converged paths preserve `TopologyConflictCode`, cycle nodes and edges, provenance/mutation classifications, capability requirements, binding rejections and paths, and search counters. Missing dynamic prerequisites, terminal connection failures, static cycles, and binding failures no longer need generic invalid-plan classification. Template/fallback/patch conflicts contain no repairable model edge, so they are ineligible for Phase 3 repair.

## 11. Atomic Patch Validation

Validation happens before a revised immutable TaskPlan is returned. Therefore WorkflowRuntime cannot construct or publish a replacement run from an invalid candidate, `IdentityProjectionBridge` cannot enter its persistence transaction with it, and `PlannerIdentityBridge.record_task_plan_patch()` cannot call `persist_task_plan()`. Tests verify that cycle and binding-conflict patches raise while the original V1 object remains unchanged. Existing persistence transactions remain unchanged.

## 12. Architecture Guard

A parameterized spy test exercises dynamic, template, fallback/compatibility, and patch producers and proves that every route reaches the same compiler-level `validate_candidate()` twice (pre-binding and final). Repository audit found one compiler, one candidate validator, and one binding solver. The duplicate legacy topology helpers in `TaskDecomposer` were removed.

## 13. Regression Tests

Coverage includes fixed existing-plan cycles, template structured failure before build, valid compatibility binding without duplicate public edges, valid V1 `A -> B` plus patch `B -> C`, direct-cycle patch rejection, capability-conflict patch evidence, original-version immutability, all-producer convergence, existing valid template-to-Builder behavior, and Runtime/identity graph-patch transactions.

## 14. Test Results

```text
Planner:                                      70 passed
Planner + Runtime/patch/architecture/v2:       140 passed
Python compileall:                            pass
git diff --check:                             pass
```

The final combined count is recorded after the final validation run. Warnings are existing legacy AgentNode deprecations.

## 15. Remaining Legacy Paths

`TaskPlan` remains directly constructible by tests and external callers; Phase 5A can govern repository production paths but cannot prevent arbitrary public contract construction without changing the public schema. `PlannerIdentityBridge.record_task_plan()` deliberately consumes an already-materialized plan and does not recompile it; formal production is gated at its producer or patch boundary. Existing-plan mode skips catalog dependencies whose producer capability is absent to preserve template identity and historical compatibility.

## 16. Risks

- Existing-plan provenance is internal and not persisted in the public TaskPlan.
- Patch callers that omit an injected custom catalog use the default catalog; Runtime uses the correct injected catalog.
- Terminal completion can add compiler-owned edges to an existing plan when a declared verification/artifact sink exists; explicit fixed edges are never removed.
- Plans with no declared capability cannot receive capability coverage analysis.

## 17. Phase 5B Recommendation

Phase 5B should verify that ACGBuilder lowering preserves every validated semantic dependency and control policy, persist a compact topology audit through existing trace metadata without changing TaskPlan/DB schemas, and add an explicit catalog-provider dependency to identity-only patch services so custom catalogs never rely on the compatibility default.
