# Prompt Runtime PR-2 Implementation

## Files

- `apps/agentOS/src/adapters/prompt_runtime.py`: shared presets, trust classes, deterministic system composition and capability policy rendering.
- `apps/agentOS/src/adapters/model/native_prompt.py`: structured ExecutionRequest and trust-aware context serialization.
- `apps/agentOS/src/adapters/model/native.py`: native sync/stream/recovery/artifact model-path migration.
- `apps/agentOS/src/support/acg/models.py`: capability-specific `CapabilityPromptProfile` policies.
- `apps/agentOS/src/adapters/{model_runtime,model_adapter,guarded_model,openai_runtime}.py`: PR-0/PR-1 message authority and provider transport used by PR-2.
- `apps/agentOS/requirements.txt`: executable async-test baseline.
- `apps/agentOS/tests/adapters/test_prompt_runtime_pr02.py` and existing adapter/provider/native tests: PR-2 authority and regression coverage.
- `prompt-runtime-pr02-{audit,implementation,capability-matrix}.md` and `prompt-runtime-followups.md`: audit deliverables.

## Implementation

- Extended `adapters/prompt_runtime.py` with `PromptEnvelope`, `AgentPreset`, `TrustClass`, Executor/Verifier/Synthesizer presets, deterministic trusted-prefix composition, and capability policy rendering.
- Converted `NativeCapabilityPromptBuilder` to build a structured ExecutionRequest user message separately from trusted system content.
- Removed `systemBoundary` and universal artifact coverage instructions from the production request architecture.
- Migrated native sync, streaming, JSON repair, contract repair, capacity recovery, partial reduction, artifact sections, and artifact assembly verification to explicit system authority.
- Serialized runtime scope/contract as `runtime_authoritative`, evidence references as `verified_evidence`, upstream/memory as `agent_generated`, and supplied source data as `external_untrusted`. Task-carried material, contract, attachment, source-material and plugin payloads are removed from authoritative mission scope and collected under the untrusted source envelope.
- Marked tool observations with authenticated-origin metadata while explicitly retaining data-only content authority.
- Reused and strengthened `CapabilityPromptProfile`; no parallel capability policy model was introduced.
- Added distinct Verifier and Synthesizer presets. Verification evaluates rather than repairs. Synthesis is artifact-contract-driven and preserves uncertainty/provenance.
- Added `pytest` and `pytest-asyncio` declarations to the AgentOS requirements so async tests execute.

## Compatibility

The public structured model runtime keeps optional `system_prompt`, so non-native legacy callers remain compatible. Provider schema handling, model retry/failover, usage, timeout, streaming events, output validators, tool binding, capability binding, ACG compilation, checkpoints, and artifact persistence retain their existing owners.

Repair and capacity-recovery user messages now remain JSON: the original ExecutionRequest plus a runtime-authoritative `runtimeOperation`. Operation semantics live in the trusted runtime contract.

## Tests

Tests cover authority roles, systemBoundary retirement, injection boundaries, memory/upstream/tool trust, policy differentiation, Verifier/Synthesizer behavior, provider ordering, streaming, repair/recovery, and the previously failing async resource adapter tests.

- Focused command: `pytest -q tests/adapters/test_prompt_runtime_pr02.py tests/adapters/test_native_prompt_v2.py tests/adapters/test_native_agent.py tests/adapters/test_native_recovery_ladder.py tests/adapters/test_model_runtime.py tests/adapters/test_model_runtime_streaming.py tests/adapters/test_openai_runtime.py tests/adapters/test_resource_execution.py`
- Focused result: 56 passed, 0 failed, 0 skipped.
- Regression command: `pytest -q tests/adapters tests/components/planner tests/runtime`
- Regression result: 337 passed, 0 failed, 0 skipped, 44 deprecation warnings.
- The former async baseline failures are now executed and passing after declaring/installing `pytest-asyncio`.
- Static verification: `python -m compileall -q src service` and `git diff --check` completed successfully (`git diff --check` emitted line-ending warnings only).
