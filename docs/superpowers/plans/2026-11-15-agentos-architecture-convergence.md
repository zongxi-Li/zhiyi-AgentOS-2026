# AgentOS Architecture Convergence Implementation Plan

> **For agentic workers:** Use the dispatching-parallel-agents workflow for disjoint migrations; the primary agent owns import integration and final verification. Execute all tasks without a further approval gate: the user has approved the architecture and requested implementation.

**Goal:** Place current AgentOS implementations under the approved 13-component architecture, remove duplicated authorities, and repair source, test, and launch paths after the user's existing moves.

**Architecture:** Preserve one canonical Python module per implementation. Move code by responsibility, update callers instead of adding parallel implementations, retain a thin runtime facade, and keep transactional cross-component coordination distinct from component rules. Shared contracts and domain interfaces remain lightweight; database schemas stay isolated.

**Tech Stack:** Python 3.10, Pydantic 2, pytest, independent TypeScript Hands/compact engines.

## Baseline and constraints

- Snapshot committed as `faf7ba8a` on `refactor/agentos-architecture-20261115` before implementation.
- The user's tests now live at repository-root `TEST/tests/`; evaluations live at `evals/`.
- Existing pytest paths and several source imports are already broken. Capture baseline collection errors, then repair paths before assessing regressions.
- Do not discard safe HTTP/authentication implementations, merge independent database schemas, copy singleton brokers/locks, or equate renamed directories with completed features.
- Parent owns git operations. Migration workers own disjoint source areas and emit old-to-new module maps; global caller updates occur once after those maps are combined.

## Tasks

### 1. Repair test discovery and canonical imports

- [ ] Update `apps/agentOS/pytest.ini` to root-relative absolute-resolvable source/test locations; add shared `TEST/tests/conftest.py` repository discovery.
- [ ] Replace obsolete `components.mission_manager`, `contracts.mission_semantic`, `contracts.mission_revision`, `components.content`, `storage.v2`, and fully qualified duplicate `apps.agentOS.src.*` imports with canonical paths.
- [ ] Repair test filesystem roots by locating `apps/agentOS/src` from repository markers; preserve existing assertions and monkeypatch semantics.
- [ ] Record a fresh pytest collection result and retain all moved tests.

### 2. Converge components

- [ ] Move `src/safe` as one package to `src/components/safe`, preserving its lightweight public facades, HTTP/authentication, model runners and privacy rejection semantics.
- [ ] Restore the deleted partition-validation boundary from the snapshot's parent under safe; share its public contract, do not fabricate a model executor.
- [ ] Move `components/marketplace` into `components/resource/catalog`; preserve installation and resource-qualification boundaries.
- [ ] Extract graph dependency-ready selection into `components/scheduler`; executor consumes that public selection service without duplicating the readiness algorithm.
- [ ] Keep environment content/hands/compact projects independent; update executable paths, documentation and test entry points.

### 3. Separate runtime responsibilities

- [ ] Create `composition`, `orchestration`, `projections`, `events`, `compatibility` subpackages and retain `workflow_runtime.py` as the stable facade.
- [ ] Move pure review policy to auditor, graph compilation/semantic patch to planner, mission-input projection and identity lifecycle to mission, quota rules to resource, shared lifecycle rules to domain.
- [ ] Move locks to a single support implementation; remove executor imports of runtime by injecting the event publisher.
- [ ] Keep write-capable identity projection/reconciliation in orchestration; projections contain read views only.
- [ ] Repair frozen compilation-recipe source paths and late imports without bypassing version checks.

### 4. Converge adapters and shared support

- [ ] Group adapters into model/agent/tool/retrieval/transport with one canonical implementation and update public exports.
- [ ] Move root `service/agents` into the agent integration area, preserving its existing public types and registration/pool behavior.
- [ ] Move ACG schemas/planning data to contracts, pure graph validation to planner, capability registration infrastructure to a technical registry; remove business ownership from support/acg.
- [ ] Consolidate identical canonical JSON/model fingerprint helpers while preserving full-field versus omit-default digest semantics.
- [ ] Remove unused empty/duplicate source modules only after checking callers; keep unrelated experimental and generated workspace files out of commits.

### 5. Integration, review and evidence

- [ ] Update application callers under `apps/agent`, operational paths, evals and moved tests using the combined module map; no broad rewrite of historical evidence.
- [ ] Run compile/import checks, architecture and component/runtime/storage regressions, safe regressions, and Hands/compact typechecks/tests available in the existing environment.
- [ ] Review source dependency directions and compare the physical tree with the 13-component target; fix integration failures before declaring completion.
- [ ] Update `apps/agentOS/README.md` with the implemented structure, actual capability limits and reproducible commands; record validation counts and unresolved environmental constraints.
- [ ] Commit the completed refactor on the branch after validation, leaving the pre-refactor snapshot independently recoverable.
