# Prompt Runtime PR-2 Audit

## Baseline and production chain

Audited current local `master` on 2026-09-18, including the uncommitted PR-0/PR-1 backend changes already present in the worktree. Unrelated frontend changes were not modified.

The production native chain is:

`ACG node ready` -> `ACGNodeRunner.run_step` -> frozen capability descriptor/model/tool binding -> `AgentRunContext` -> `NativeGeneralAgent.run` -> `NativeCapabilityPromptBuilder` -> `GuardedModelRuntime` -> `RegisteredModelRuntime` -> `ModelInvocationRequest` -> `OpenAICompatibleRuntime`.

All 15 declared native capabilities bind to `NativeGeneralAgent`. `information_retrieval` is the exception to model prompting: it executes runtime-authorized retrieval tools and returns deterministic `AgentOutput`. The other native capabilities converge on one prompt entry. JSON repair, contract repair, capacity split, partial execution/reduction, artifact outline/section split, and assembly verification are alternate model invocation paths from that same agent.

## Original authority and context sources

- `NativeCapabilityPromptBuilder` returned one mixed string containing behavior instructions plus `RUNTIME_REQUEST` JSON. `RegisteredModelRuntime` consequently sent it as one `user` message.
- `systemBoundary` was an ordinary user-payload field. It had no provider-level system authority.
- `ContextPack` is assembled by `ACGNodeRunner`/Communicator from topology-allowed upstream values. `data` contains selected upstream output fields; `sourceData` retains producer-scoped payload; `evidenceRefs` retains references.
- Memory is recalled by `MemoryService` according to the compiled step memory policy, then placed in `AgentRunContext.memory`. It previously was not explicitly represented in the native prompt request.
- Upstream outputs are model/tool-produced node values from the ContextPack and were previously merged without an explicit trust class.
- Tool authority is scoped in `ACGNodeRunner` from the compiled skill manifest/runtime allowed set. Retrieval and industrial calculator observations originate in the tool runtime; their content is still data.
- Task identity, planned goal, acceptance criteria, capability binding, tool availability, and output schema originate in the control plane. Mission/source text may originate with users or external materials. Upstream and memory content may be model generated.
- Verification and artifact generation used the generic native prompt. Artifact prompting also imposed universal report coverage areas through `build_artifact()`.
- Generic OpenAI-compatible transport preserved message roles. GLM/Zhipu added schema compatibility at the system transport layer, after the PR-1 ordering fix.

## Risks found

- No real Executor system role on any native model path.
- `systemBoundary` could look authoritative despite being mutable user data.
- Memory, upstream output, source content, evidence references, and tool observations lacked explicit, distinct authority semantics.
- Verifier could semantically behave like an executor and improve the candidate while judging it.
- Synthesizer shared generic execution behavior and could invent completeness or universal report sections.
- Capability profiles existed but most execution principles were generic; behavior differed mainly through schema and purpose.
- Recovery/repair calls could silently regress to user-only mixed instruction prompts.
- AgentOS test dependencies omitted `pytest-asyncio`, causing four async tests not to execute.

## Self-audit

1. **CONFIRMED** Executor model calls use system + user roles through `PromptEnvelope` and `system_prompt` on sync and streaming paths (`NativeGeneralAgent.run`, `NativeCapabilityPromptBuilder.build_envelope`).
2. **CONFIRMED** No formal model-backed native path intentionally sends a user-only prompt; every `generate_json`/stream call in `adapters/model/native.py` receives `system_prompt`. Retrieval remains a non-model tool path.
3. **CONFIRMED** `systemBoundary` is absent from ExecutionRequest and has no behavioral authority (`NativeCapabilityPromptBuilder.build_envelope`).
4. **CONFIRMED** ContextPack channels are classified as runtime authoritative, verified evidence, agent generated, or external untrusted (`TrustClass`, `build_envelope`).
   Task-carried material, contract, attachment, source-material and plugin payloads are explicitly excluded from authoritative mission scope.
5. **CONFIRMED** Memory is serialized only as agent-generated data and never into system content (`contextPack.memory`).
6. **CONFIRMED** Upstream output is agent-generated, never automatically verified evidence (`contextPack.upstreamOutputs`).
7. **CONFIRMED** Tool observations are data with authenticated-origin metadata distinct from content authority (`runtimeVerifiedOrigin`, `contentAuthority=data_not_instruction`).
8. **CONFIRMED** Every native capability renders a policy; `native_capability_descriptors()` supplies explicit differences tested by `test_high_value_capability_policies_are_semantically_distinct`.
9. **CONFIRMED** `preset_for_capability("verification")` selects Verifier; `_recover_artifact_by_sections` explicitly composes the verification policy for assembly checks.
10. **CONFIRMED** `preset_for_capability("artifact_generation")` selects Synthesizer.
11. **CONFIRMED** `build_artifact()` no longer adds universal report coverage areas. Existing structured-output compatibility fields remain schema-owned rather than prompt instructions.
12. **CONFIRMED** `_trusted_system()` composes Kernel -> preset -> capability policy -> runtime contract upstream into one stable system prefix; providers do not choose capability authority.
13. **CONFIRMED** `NativeGeneralAgent.run` passes the same `system_prompt` and ExecutionRequest to native streaming and sync execution.
14. **CONFIRMED** JSON structure remains enforced by response schema, `ModelInvocationRequest.response_schema`, provider output controls, defaults, and validators.
15. **CONFIRMED** `TaskPlanTopologyCompiler` was not modified by PR-2.
16. **CONFIRMED** RuntimeGraph/scheduler/ready-set/checkpoint code was not modified by PR-2; the required runtime regression suite passes.
17. **CONFIRMED** `adapters/prompt_runtime.py` and the existing model runtime were extended; no parallel Prompt/Runtime authority was introduced.
