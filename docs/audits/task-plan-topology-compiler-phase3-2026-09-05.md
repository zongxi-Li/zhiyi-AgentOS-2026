# TaskPlan Topology Compiler Phase 3

## 1. Baseline

Phase 3 builds on the Phase 1-2 internal CandidateTopology boundary. Planner baseline was 51 passing tests; the combined Planner, Runtime ACG, and architecture baseline was 88. Existing working-tree changes were preserved.

## 2. Files Changed

- Extended topology `errors.py` with typed conflict codes, categorized mutable edges, repair attempts, and eligibility policy.
- Added topology `repair.py` with a patch response contract, structured conflict serialization, and deterministic patch application.
- Added internal compilation audit data to `model.py` and `compiler.py`.
- Updated staged `TaskDecomposer` repair to consume `TopologyConflict` directly and fully recompile patched proposals.
- Expanded topology and staged Planner tests.

No public TaskPlan schema, database schema, Runtime, Scheduler, frontend, or ACGBuilder behavior was changed.

## 3. Structured Conflict Codes

`TopologyConflictCode` now defines dependency cycle, capability binding conflict, invalid control policy, terminal connection conflict, unknown task reference, and self dependency. The formal dynamic topology repair path checks the enum and structured edge fields rather than exception text.

## 4. Repair Eligibility

`is_model_repair_eligible()` permits one LLM repair only for `DEPENDENCY_CYCLE` conflicts whose cycle contains at least one `model/repairable` edge. Fixed-only cycles are ineligible and are returned immediately as structured failures.

## 5. Full Constraint Repair Context

The repair prompt contains frozen tasks, current model relations, current control policies, full cycle nodes, every concrete cycle edge, origin, mutation policy, reason, requirement ID, original model relation index, and all materialized capability requirements. It explicitly forbids removing catalog requirements or changing task identity, capability, source references, or material identity.

## 6. Patch Contract

The model returns operations only: remove/add/replace relation, remove invalid feedback relation, or add verification loop. Existing model relations are addressed by `originalRelationIndex`; multiple removals use stable original slots so earlier removals cannot shift later indexes. Patch validation rejects unknown task references and invalid indexes.

## 7. Full Recompile Flow

Patch application changes only the model relation/control proposal. It does not mutate the failed CandidateTopology. `_to_plan()` is called again with frozen detailed tasks and patched proposals, which redoes normalization, capability requirement materialization, concrete binding, terminal generation, and global validation. A test proves the second compile can select P2 where the first selected P1.

## 8. Case A

The staged direct-cycle regression now uses a patch response: it removes the indexed feedback relation while keeping frozen task identities. Verification-loop operations are separately tested and never become static back edges.

## 9. Case B

The real storage-planning cycle remains covered. Repair context can see `implementation-schedule-30weeks -> storage-sizing-calculation` as `capability_catalog/rebindable`, while the other cycle edges are `model/repairable`. The patch contract cannot address or delete the catalog edge because it only accepts original model relation indexes.

## 10. Immutable Conflict

A fixed-only dependency cycle is explicitly tested as not model-repair eligible. Therefore LLM repair call count is structurally zero for that class of conflict.

## 11. Repair Budget

The staged flow contains one conditional repair call followed by one unconditional full recompile. A second compile failure exits to the outer structured-failure wrapper; there is no loop or recursive repair path.

## 12. Audit Trail

The compiler returns an internal audit containing original model relations, normalized model edges, materialized capability requirements, selected concrete bindings, and terminal edges. Staged repair stores compile #1 conflict, repair patch, repair count, and compile #2 result in `last_audit`. Final structured failure is retained in `TaskDecompositionError.metadata.topology`. No DB change was introduced.

## 13. Test Results

```text
Planner baseline:                         51 passed
Planner after Phase 3:                    55 passed
Planner + Runtime ACG + architecture:     92 passed
```

Eight warnings are existing legacy AgentNode deprecation warnings. Python compilation and diff checks passed.

## 14. Remaining Legacy Logic

The old `_is_dependency_cycle_error()` string adapter was unused after the structured branch replaced it and has been removed. Template, fallback, patch migration, and public audit persistence remain intentionally outside Phase 3. Capability binding remains the Phase 1-2 greedy heuristic.

## 15. Risks

- The provider must correctly produce patch operations; invalid patches fail closed.
- Public/historical TaskPlan snapshots intentionally do not contain provenance.
- Structured failure is nested in the existing TaskDecompositionError metadata because public error APIs were out of scope.
- The current patch schema permits adding model relations; compiler validation remains the authority that prevents unsafe success.

## 16. Phase 4 Recommendation

Phase 4 should implement stable capability-candidate scoring and bounded backtracking, then persist a safe compiler audit through an existing trace extension point. The obsolete string compatibility helper was already removed in Phase 3.
