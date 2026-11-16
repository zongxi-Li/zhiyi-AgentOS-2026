# AgentOS Architecture Convergence Implementation Plan

> **For agentic workers:** Use the dispatching-parallel-agents workflow for disjoint migrations; the primary agent owns import integration and final verification. Execute all tasks without a further approval gate: the user has approved the architecture and requested implementation.

**Goal:** Place current AgentOS implementations under the approved 13-component architecture, remove duplicated authorities, and repair source, test, and launch paths after the user's existing moves.

**Architecture:** Preserve one canonical Python module per implementation. Move code by responsibility, update callers instead of adding parallel implementations, retain a thin runtime facade, and keep transactional cross-component coordination distinct from component rules. Shared contracts and domain interfaces remain lightweight; database schemas stay isolated.

**Tech Stack:** Python (verified with 3.13.3), Pydantic 2, pytest 8.4.2, independent TypeScript Hands/compact engines on Node 24.11.1.

## Baseline and constraints

- Snapshot committed as `faf7ba8a` on `refactor/agentos-architecture-20261115` before implementation.
- The user's tests now live at repository-root `TEST/tests/`; evaluations live at `evals/`.
- Existing pytest paths and several source imports are already broken. Capture baseline collection errors, then repair paths before assessing regressions.
- Do not discard safe HTTP/authentication implementations, merge independent database schemas, copy singleton brokers/locks, or equate renamed directories with completed features.
- Parent owns git operations. Migration workers own disjoint source areas and emit old-to-new module maps; global caller updates occur once after those maps are combined.

## Tasks

### 1. Repair test discovery and canonical imports

- [x] Update `apps/agentOS/pytest.ini` to root-relative absolute-resolvable source/test locations; add shared `TEST/tests/conftest.py` repository discovery.
- [x] Replace obsolete `components.mission_manager`, `contracts.mission_semantic`, `contracts.mission_revision`, `components.content`, `storage.v2`, and fully qualified duplicate `apps.agentOS.src.*` imports with canonical paths.
- [x] Repair test filesystem roots by locating `apps/agentOS/src` from repository markers; preserve existing assertions and monkeypatch semantics.
- [x] Record a fresh pytest collection result and retain all moved tests.

### 2. Converge components

- [x] Move `src/safe` as one package to `src/components/safe`, preserving its lightweight public facades, HTTP/authentication, model runners and privacy rejection semantics.
- [x] Restore the deleted partition-validation boundary from the snapshot's parent under safe; share its public contract, do not fabricate a model executor.
- [x] Move `components/marketplace` into `components/resource/catalog`; preserve installation and resource-qualification boundaries.
- [x] Extract graph dependency-ready selection into `components/scheduler`; executor consumes that public selection service without duplicating the readiness algorithm.
- [x] Keep environment content/hands/compact projects independent; update executable paths, documentation and test entry points.

### 3. Separate runtime responsibilities

- [x] Create `composition`, `orchestration`, `projections`, `events`, `compatibility` subpackages and retain `workflow_runtime.py` as the stable facade.
- [x] Move pure review policy to auditor, graph compilation/semantic patch to planner, mission-input projection and identity lifecycle to mission, quota rules to resource, shared lifecycle rules to domain.
- [x] Move locks to a single support implementation; remove executor imports of runtime by injecting the event publisher.
- [x] Keep write-capable identity projection/reconciliation in orchestration; projections contain read views only.
- [x] Repair frozen compilation-recipe source paths and late imports without bypassing version checks.

### 4. Converge adapters and shared support

- [x] Group adapters into model/agent/tool/retrieval/transport with one canonical implementation and update public exports.
- [x] Move root `service/agents` registration/protocols into `adapters/agent`; put instance pools and provisioning under `components/resource/agents`, preserving public behavior.
- [x] Move ACG schemas/planning data to contracts, pure graph validation to planner, capability registration infrastructure to a technical registry; remove business ownership from support/acg.
- [x] Consolidate identical canonical JSON/model fingerprint helpers while preserving full-field versus omit-default digest semantics.
- [x] Remove unused empty/duplicate source modules only after checking callers; keep unrelated experimental and generated workspace files out of commits.

### 5. Integration, review and evidence

- [x] Update application callers under `apps/agent`, operational paths, evals and moved tests using the combined module map; no broad rewrite of historical evidence.
- [x] Run compile/import checks, architecture and component/runtime/storage regressions, safe regressions, and Hands/compact typechecks/tests available in the existing environment.
- [x] Review source dependency directions and compare the physical tree with the 13-component target; fix integration failures before declaring completion.
- [x] Update `apps/agentOS/README.md` with the implemented structure, actual capability limits and reproducible commands; record validation counts and unresolved environmental constraints.
- [x] Commit the completed refactor on the branch after validation, leaving the pre-refactor snapshot independently recoverable.


## Final integration record — 2026-11-16

- Directory/source checkpoint: `1c63269b`, after the independently recoverable snapshot `faf7ba8a`.
- Completed final regressions: 538 integration tests, 406 adapter tests, and 470 safe/domain/runtime-boundary tests passed in separate batches. Batches may overlap; counts are not an independent-test total.
- Hands and compact typechecks passed on Node 24.11.1; compact passed 51 tests. Hands execution tests remain 91 passed / 11 failed around Windows confinement and ACL checks.
- Full AgentOS collection reached 3078 tests and three errors for the already-missing `examples.contract_review`; this is not a claim that the entire suite passes.
- Blueprint-to-package compilation now has one planner implementation. Executor retains runtime graph conversion, and the implementation fingerprint covers both source files.
- Tests have native `TEST.tests` package identities and canonical fixture imports for Windows spawn. Legacy test-root path injection was removed from pytest and the freeze runner.
- The temporary SDK / FastAPI dependency conflict was isolated and corrected with compatible cached Starlette / SSE wheels for the final HTTP regression batch. No system Python changes or fake SDK were used.
- Existing legacy trace/recovery assertions, missing federated encryption service, privacy capability limits, and environment constraints are recorded in the linked audit. No guard or frozen baseline was weakened to make validation green.
- Checkboxes record the performed migration and validation work; unresolved pre-existing/environmental acceptance limits remain explicit.

Detailed responsibility mapping, test commands, and limitations: [migration and validation audit](../../audits/2026-11-16-agentos-architecture-convergence.md).
