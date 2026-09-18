# Prompt Runtime PR-0/PR-1 Audit

## Scope and evidence

Audit baseline: current local `master` (`master...origin/master`) on 2026-09-18. Existing frontend worktree changes were not modified. The audit used production source, not historical design documents.

## Original call chains

Planner: `WorkflowRuntime.planning_engine` -> `PlanningEngine` -> `IntentParser` -> `SemanticPlanner` -> `TaskDecomposer` -> `call_planning_model` -> `GuardedModelRuntime` -> `RegisteredModelRuntime` -> registered provider -> `OpenAICompatibleRuntime`.

Formal Planner model entries were intent profiling (including repair), standard decomposition (including schema, coverage and topology patch repairs), and staged outline/detail/relations (including their repairs). They all converge on `call_planning_model`.

Executor: runtime node execution -> native model agent -> `NativeCapabilityPromptBuilder` -> guarded/registered model runtime -> provider. Its `systemBoundary` is a JSON field inside a string prompt; ContextPack, source data, evidence and upstream results are serialized into that same user-level prompt. This remains a PR-2 concern.

## Findings

- `ModelInvocationRequest` already supported message arrays, but `RegisteredModelRuntime.generate_json` and its streaming twin always produced one `user` message.
- Intent and decomposition policy, capability catalog, mission contract and source text were concatenated into ordinary prompt strings.
- No Kernel-level AgentOS system instruction existed on the Planner path.
- `materialText`, `contractText`, `attachmentContext`, source materials and similar content had no explicit trust classification.
- OpenAI-compatible providers preserved messages and used native strict `response_format`; GLM/Zhipu prepended an additional schema system message ahead of upstream messages.
- Task decomposition explicitly targeted complexity-dependent approximate node ranges.
- Planner audit hashes were version+schema hashes while `RegisteredModelRuntime` called a hash of the entire prompt `promptTemplateHash`; semantics were inconsistent.
- Deterministic catalog normalization, topology compilation and ACG construction remained downstream authorities.

## Change boundary

PR-0 adds explicit system-message input to the existing structured generation runtime. PR-1 adds one static Kernel, one Planner preset, Planner-wide injection at the shared call boundary, source trust envelopes, parsimonious decomposition guidance, and provider ordering fixes. No RuntimeGraph, scheduler, ACG builder, topology compiler, binding solver, execution, persistence or streaming event semantics were redesigned.

## Architecture self-review

1. **CONFIRMED** Kernel enters Planner model requests as `system` through `call_planning_model` -> `system_prompt` -> `ModelInvocationRequest.messages`.
2. **CONFIRMED** Planner policy is static system content; runtime/source payload remains user content.
3. **PARTIAL** Planner source fields are marked `external_untrusted` and cannot enter system content. Executor remains single-user prompt architecture for PR-2.
4. **CONFIRMED** All formal Planner entries converge on the shared boundary; no production Planner path intentionally sends a single user message.
5. **CONFIRMED** generic providers preserve ordering; GLM appends its transport schema contract after existing AgentOS system content rather than prepending over it.
6. **CONFIRMED** generic strict JSON schema and GLM `json_object` behavior remain in the provider adapter and are covered by tests.
7. **CONFIRMED** `TaskPlanTopologyCompiler` and existing validation path remain unchanged and authoritative.
8. **CONFIRMED** no second model runtime, orchestration runtime or prompt execution truth was introduced.
