# ACG Runtime Streaming Phase 1-2 Acceptance

## Regression attribution

- Baseline worktree (HEAD `c541d09`): 401 passed, 2 failed.
- Current after the minimal fix: 406 passed, 2 failed.
- The remaining two failures reproduce on baseline and are classified `PRE_EXISTING_FAILURE`: planner token contract and projection replay fixture.
- The common streaming regression was `WorkflowRuntime` forwarding unsupported `superstep_failed` events into `TraceStore`; removing that observation-side pollution restored the ACG runtime cluster.
- Frontend Output is a formal fifth tab. The stale test contract was updated from 4 to 5 tabs.

## Evidence

- Frontend full Vitest: 298/298 passed (57 files).
- Frontend production build: passed.
- Streaming frontend tests: 3/3 passed.
- Streaming backend/broker tests: 5/5 passed.
- Fake Provider -> Native Agent -> Broker timeline: passed; lifecycle ordering and completion payload redaction verified.
- SSE disconnect cleanup: passed.
- Slow consumer policy: passed.
- `git diff --check`: passed.

## Scope and verdict

No architecture, UI feature, or Phase 3 work was added. Real Provider Workbench manual acceptance was not executed in this turn, so the final product sign-off remains:

**NOT YET COMPLETED: waiting only for real Provider Workbench evidence and the two pre-existing backend baseline failures to be tracked separately.**
