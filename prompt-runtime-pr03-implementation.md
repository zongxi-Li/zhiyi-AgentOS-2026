# Prompt Runtime PR-3 Implementation

## Outcome

PR-3 engineering is implemented for deterministic prompt identity, safe audit projection, provider transport coverage and an opt-in behavioral eval harness. Model-backed behavior remains unmeasured because this workspace has no `AGENTOS_MODELS` configuration. The result is therefore **partially converged**, not `Prompt Runtime Converged`.

## Files and responsibilities

- `apps/agentOS/src/adapters/prompt_runtime.py`: canonical JSON/SHA-256 helpers, template/instance/schema/stable-prefix identities, version metadata and trust summaries.
- `apps/agentOS/src/adapters/{model_adapter,model_runtime,guarded_model}.py`: optional identity metadata transport, sync/stream success and failure audits, temperature validation/forwarding and safe audit records.
- `apps/agentOS/src/adapters/model/native.py`: prompt metadata on native sync, stream, repair, recovery, reduction, artifact and internal-verification calls.
- `apps/agentOS/src/components/planner/{complexity,intent_analyzer,task_decomposer}.py`: Planner identity metadata and existing `promptAudit`/`modelInvocations` projection.
- `apps/agentOS/src/components/executor/node_runner.py`: existing Run Trace allowlist extended with safe identity fields; raw content remains excluded.
- `apps/agentOS/src/adapters/openai_runtime.py` and provider tests: generic strict-schema and GLM/Zhipu compatibility ordering.
- `apps/agentOS/evals/prompt_runtime_pr03_cases.json` and `run_prompt_runtime_pr03.py`: versioned cases and explicit model-backed runner.
- `apps/agentOS/tests/adapters/test_prompt_runtime_pr03.py` plus updated runtime/provider/native tests: deterministic identity, redaction, trace, provider, stream and failure coverage.
- `prompt-runtime-pr03-{audit,eval-report}.md`, `prompt-runtime-provider-matrix.md` and `prompt-runtime-followups.md`: audit, provider and external-validation records.

No content changes were made to TaskPlanTopologyCompiler, CapabilityBindingSolver, RuntimeGraph, Scheduler, checkpoints/recovery control, tool runtime or artifact persistence. `components/executor/graph.py` only has a working-tree line-ending marker and no content diff when line endings are ignored. Unrelated frontend changes were preserved.

## Identity semantics

- `promptTemplateHash` identifies the static Kernel + Preset + optional Capability Policy + trusted protocol/version metadata. Mission, source, memory, run ids and timestamps are excluded.
- `stablePrefixHash` identifies the single composed system message and is ready for future provider prefix-cache correlation.
- `promptInstanceHash` identifies ordered normalized messages, response schema, effective provider/model/version, structured-output mode and behavior-relevant options. Streaming, timeout, retry count, request id and trace id are excluded.
- `schemaHash` independently identifies the canonical response schema.
- Canonicalization uses sorted object keys, stable UTF-8 JSON and order-preserving arrays. It rejects non-finite JSON values.

## Audit integration and safety

`StructuredGenerationResult.audit_record()`, Planner `promptAudit`, Native `modelInvocations`, stream events and existing successful Run Trace projections now expose the same bounded identity/version fields. Sync and stream provider failure objects also receive identity after request normalization. The protected RuntimeGraph failure-event projection still retains only its older field subset; completing that persistence path is deferred. No second audit store or runtime truth was introduced.

Audit metadata is allowlisted. It stores hashes, bounded versions/identifiers, provider/model metadata and trust-class counts, but never raw system/user prompts, source, memory, attachment, tool observation, plugin payload or generated content. Trust counting stops at a formal trust envelope so untrusted content cannot forge nested authoritative counts.

## Provider handling

Prompt Runtime still composes one upstream system message. Generic OpenAI-compatible transport preserves it and uses strict `json_schema`; GLM and `zhipu` preserve it first, append only the transport output contract, and use `json_object`. Provider/model and effective structured-output mode participate in instance identity. The configured identifier `zhipuai` remains a documented compatibility gap because model transport does not route it through the GLM/Zhipu branch.

## Behavioral eval

The runner reuses `ApplicationSetup`, `RegisteredModelRuntime`, Prompt Runtime, real TaskDecomposer and topology compiler. It covers five injection channels, paired graph parsimony, four capability policies, false tool claims, verifier self-attestation and synthesizer unknown preservation, with two temperature-zero runs by default. The manifest includes English and Chinese injections and now has a deterministic JSON-load test.

Command:

```powershell
python evals/run_prompt_runtime_pr03.py --runs 2 --temperature 0
```

Actual result: exit `1`, `prompt-runtime eval not run: AGENTOS_MODELS is not configured; no model-backed eval was run`. Executed observations: `0`; passed: `0`; failed: `0`; all behavioral conclusions remain `NOT CONFIRMED`.

## Verification

Focused PR-3 regression:

```powershell
pytest -q tests/adapters/test_prompt_runtime_pr03.py tests/adapters/test_model_runtime.py tests/adapters/test_model_runtime_streaming.py tests/adapters/test_native_agent.py tests/adapters/test_openai_runtime.py
```

Final result: `56 passed, 0 failed, 0 skipped` in `5.23s`. The PR-3 file alone reports `14 passed` in `1.02s`; sync/stream failure-audit coverage reports `30 passed` with its focused set.

Full regression:

```powershell
pytest -q tests/adapters tests/components/planner tests/runtime
```

- Clean run before the final manifest-only test: `354 passed, 0 failed, 0 skipped, 44 warnings` in `49.49s`.
- Final rerun after that test: `352 passed, 3 failed, 0 skipped, 44 warnings` in `141.55s`.
- All three final failures are pre-existing one-second wall-clock tests in `tests/runtime/test_resource_binding.py`; each timed out at unchanged `components/executor/graph.py:470 asyncio.wait`. The same tests passed in the immediately preceding full run. Runtime/Scheduler code was not changed to mask this timing instability.

Static checks:

```powershell
python -m compileall -q src service evals
git diff --check
python -m json.tool evals/prompt_runtime_pr03_cases.json
```

All exited `0`. `git diff --check` emitted only the repository's LF-to-CRLF working-tree warnings, with no whitespace errors.

## Compatibility and remaining risk

Optional arguments preserve existing callers. Structured output, streaming, timeout, failover, usage and tracing contracts remain in place. The unresolved work is live behavioral evaluation, live provider certification, the `zhipuai` alias decision, full failed-call identity projection through the protected RuntimeGraph event whitelist, and independent legacy-field warning cleanup. Until the behavioral suite is run against a pinned configured model, PR-3 must remain **partially converged**.
