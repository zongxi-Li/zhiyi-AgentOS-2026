# ACG Appendix Contract Design

## Goal

Make the ACG static and runtime models conform to the fields in Appendix I while retaining the existing `nodeId`-based graph APIs.

## Scope

- Add appendix aliases for all six static node types and expose blueprint status only where specified.
- Add `schema` to Memory and Evidence nodes.
- Add explicit runtime records for task, step execution, agent instance, evidence record, memory snapshot, and recovery checkpoint.
- Preserve `RuntimeGraph`, `RuntimeNode`, `RuntimeAttempt`, and `WorkflowRun` as existing execution internals; the new records are contracts and have no persistence or scheduling behavior.
- Make Loop and Consensus execution deliberately unsupported with explicit, stable errors. This avoids treating an enum value as implemented behavior.

## Compatibility

Existing `nodeId`, `name`, and graph algorithms remain authoritative. Appendix-specific identifiers and names are computed aliases of the generic node identity, so consumers can serialize either contract without maintaining duplicate state.

## Non-goals

- Implementing persistence, scheduler behavior, dispatch logic, consensus voting, or loop execution.
- Migrating or deleting `agent/`.
