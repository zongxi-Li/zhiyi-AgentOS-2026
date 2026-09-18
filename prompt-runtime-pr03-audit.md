# Prompt Runtime PR-3 Audit

## Scope and production chain

Audited the current worktree on 2026-09-18, including the completed PR-0/PR-1/PR-2 backend changes. Unrelated frontend work was not modified.

The shared production chain is `Prompt Runtime -> PromptEnvelope/system_prompt + user request -> RegisteredModelRuntime -> ModelInvocationRequest -> provider adapter`. Sync calls return `StructuredGenerationResult`; native execution projects `audit_record()` into `modelInvocations`, which `WorkflowRuntime` projects into the existing Trace. Streaming emits `model.started`/`model.completed`; `NativeGeneralAgent` reconstructs a `StructuredGenerationResult` from the completion payload.

Planner intent profiling, monolithic decomposition, staged outline/detail/relation planning, repair and topology patch all use `call_planning_model`. It supplies the Planner system prompt but Planner `last_audit` is separately assembled by `IntentAnalyzer` and `TaskDecomposer`. Executor, Verifier and Synthesizer use `NativeCapabilityPromptBuilder.build_envelope`; JSON repair, contract repair, capacity split/reduction and artifact section recovery reuse the same trusted system content with a structured `runtimeOperation` user payload.

## Current identity and audit behavior

- `IntentAnalyzer` and `TaskDecomposer` call a value named `promptTemplateHash`, but compute it from legacy prompt version plus response schema. It does not identify the actual Kernel/Preset/static protocol.
- `RegisteredModelRuntime.generate_json` also calls a value `promptTemplateHash`, but computes it from the dynamic user prompt only. Mission/source changes alter it while system policy changes do not.
- No `promptInstanceHash`, `schemaHash` or stable-prefix identity exists.
- `promptVersion` is passed through sync calls. Streaming currently discards `prompt_version`, and `model.completed` has no prompt identity; the reconstructed result therefore loses all hashes.
- Sync audit records contain provider, model, latency, usage, output policy and the ambiguous template hash. They do not contain Kernel/Preset/Capability/Protocol versions or a trust summary.
- Native `modelInvocations` and the existing trace projection are the correct persistence path. They already avoid raw prompt/model response text, so no PromptAudit database or second trace truth is needed.
- Planner `promptAudit` is stored in existing planning audit metadata. It can be enriched without changing Blueprint or topology ownership.
- Before PR-3, errors sometimes carried provider/usage audit metadata but not prompt identity. The implementation now attaches the same safe identity/version metadata to sync and stream failure objects once an invocation has been normalized; pre-normalization validation/configuration errors intentionally have no instance identity. The protected RuntimeGraph failure-event projection still allowlists only the older subset, so full failed-call trace persistence remains a follow-up rather than a control-plane change in this PR.

## Static and dynamic boundaries

The stable trusted prefix is composed only from AgentOS Kernel, Agent Preset, optional Capability Policy and the static runtime contract. It contains no run id, task id, timestamp, user identity, source, memory, upstream output or tool observation. ExecutionRequest/PlanningRequest and response schema are dynamic invocation inputs.

PR-3 will define one canonical serializer and three related identities:

- `promptTemplateHash`: canonical static template metadata plus the exact composed trusted system prefix.
- `stablePrefixHash`: canonical normalized system message. With the current single-system-message architecture it is expected to match the static prefix portion of template identity, but remains a separately named audit field.
- `promptInstanceHash`: normalized final messages, response schema, provider family, model binding/version and behavior-relevant options. Streaming transport mode, request ids, timeouts, retries and trace ids are excluded.

`schemaHash` will independently identify the response schema. Audit records will contain only hashes, versions, bounded identifiers and trust-class counts, never raw prompt/source/memory/tool/attachment/plugin content.

## Provider audit

Production registration is configuration-driven through `ApplicationSetup` and a single `OpenAICompatibleRuntime`; provider names and endpoints are not hard-coded to a closed list. Generic OpenAI-compatible endpoints use native strict `json_schema`. Provider aliases `glm` and `zhipu` take the explicit compatibility branch: one composed AgentOS system message is retained first and the schema-only transport contract is appended to it, with `json_object` response mode. `zhipuai` is recognized for retrieval routing but is not in the model transport's GLM schema branch and must be documented as a limitation rather than inferred as equivalent.

The provider adapter does not select Kernel, Preset or Capability Policy. Multiple upstream system messages are not produced; Prompt Runtime composes one stable system prefix before transport.

## Eval audit

`evals/prompt_orchestration_v2.json` is an existing 30-case planning dataset and rubric, but there is no executable model-backed prompt eval runner. The governance evaluator scores completed run history and is not a remote Prompt Runtime eval harness. PR-3 should extend the existing `evals` area with one explicit, opt-in runner and versioned cases rather than introduce a parallel test framework. Deterministic hash/redaction/provider tests remain in `tests/` and must not call a paid model.

## Risks and boundaries

- Hashes identify complete canonical invocations; they are not encryption and no source-level secret hashes will be persisted.
- Provider failover can change the effective adapter while provider/model binding remains the same; audit must use the selected response/capability where available.
- Model-backed eval results are only confirmed when a configured provider is actually invoked. A runner and case set alone are not evidence of behavioral success.
- The 44 current warnings are legacy agent-field migration warnings. Fixing them requires broader execution model migration and is outside Prompt Runtime PR-3.
- TaskPlanTopologyCompiler, CapabilityBindingSolver, ACGBuilder, RuntimeGraph, Scheduler, checkpoints, tools and artifact persistence remain unchanged.

## Chosen convergence point

Extend `PromptEnvelope` with immutable safe template metadata, pass it through the existing optional model-runtime kwargs, compute final instance/schema identities inside `RegisteredModelRuntime`, and project them through `StructuredGenerationResult.audit_record()` and streaming completion metadata. This keeps Prompt Runtime authoritative for static policy identity, Model Runtime authoritative for the final provider-facing invocation identity, and the existing Planner/Run trace structures authoritative for audit persistence.

## Final architecture self-audit

1. **CONFIRMED** `promptTemplateHash` has one static-template meaning (`prompt_template_metadata`).
2. **CONFIRMED** `promptInstanceHash` has one normalized invocation meaning (`prompt_instance_metadata`).
3. **CONFIRMED** Both use UTF-8 canonical JSON with sorted object keys and order-preserving arrays (`canonical_json`, deterministic tests).
4. **CONFIRMED** Mission/source changes alter only user input and instance identity, not template identity (`test_template_hash_ignores_mission_and_source_data`).
5. **CONFIRMED** Kernel/preset/capability policy changes alter template identity (`test_template_hash_changes_*`).
6. **CONFIRMED** Schema changes are independently visible through `schemaHash` and also alter instance identity.
7. **CONFIRMED** `StructuredGenerationResult.audit_record()` contains no raw prompt or generated data.
8. **CONFIRMED** `RegisteredModelRuntime._prompt_metadata` and `ACGNodeRunner._safe_model_invocations` use safe allowlists; trust summary stops at envelope boundaries and stores no source/memory/tool body.
9. **CONFIRMED** Planner metadata is supplied in `call_planning_model`; Executor/Verifier/Synthesizer metadata comes from their `PromptEnvelope`.
10. **CONFIRMED** Sync results and streaming `model.started`/`model.completed` carry the same identity fields; streaming transport mode is excluded from instance hash.
11. **CONFIRMED** Native repair/recovery calls reuse the static envelope metadata while their structured runtime operation changes the instance hash; internal artifact verification uses a Verifier envelope.
12. **CONFIRMED** Prompt Runtime composes one system message upstream; generic transport preserves it and GLM/Zhipu appends only the transport output contract after it.
13. **NOT CONFIRMED** Injection behavioral eval cases and a real-model runner exist, but no model is configured and no remote invocation occurred.
14. **NOT CONFIRMED** Graph parsimony has a model-backed paired evaluation path through the real TaskDecomposer/topology compiler, but it was not executed.
15. **NOT CONFIRMED** Capability differentiation behavior cases were not executed against a model.
16. **NOT CONFIRMED** Verifier self-attestation resistance was not measured against a model.
17. **NOT CONFIRMED** Synthesizer unknown preservation was not measured against a model.
18. **CONFIRMED** Planner audit and Native `modelInvocations`/Run Trace are reused; no PromptAudit store/database was added.
19. **CONFIRMED** Existing planning audit and Run Trace remain the only persistence truths.
20. **CONFIRMED** TaskPlanTopologyCompiler, RuntimeGraph, Scheduler, checkpoints and recovery control code were not modified. `components/executor/graph.py` has no content diff when line-ending differences are ignored.

Because items 13-17 are not confirmed, PR-3 is **partially converged** and the overall Prompt Runtime must not yet be labelled `Prompt Runtime Converged`.
