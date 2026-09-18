# Prompt Runtime Follow-ups

## PR-2 (closed)

- Native Executor, Verifier, and Synthesizer now use real system authority.
- ContextPack, memory, evidence, tool observations, and upstream output have explicit trust classes.
- `systemBoundary` has been retired from the native execution request.
- Capability policies are rendered from the existing versioned prompt profiles.

## PR-3 engineering (implemented)

- `promptTemplateHash`, `promptInstanceHash`, `schemaHash` and `stablePrefixHash` now have separate canonical semantics.
- Planner and Native sync/stream/repair/recovery audit metadata uses existing planning audit and Run Trace projections.
- Prompt audit persistence is allowlisted and excludes raw prompt, source, memory, attachment, plugin and tool bodies.
- The opt-in model-backed injection, parsimony, capability, false-tool, verifier and synthesizer eval runner is implemented under `apps/agentOS/evals`.
- Generic OpenAI-compatible and GLM/Zhipu authority/schema ordering has deterministic coverage.

## PR-3 external validation (open)

- Run `evals/run_prompt_runtime_pr03.py` against an explicitly configured model for at least two runs per case and replace the NOT RUN eval report with measured results.
- Execute live endpoint compatibility checks for each production provider/model snapshot; current workspace has no model configuration or credentials.
- Decide whether `zhipuai` should join the model transport's explicit GLM/Zhipu schema branch; retrieval routing currently recognizes it while model transport does not.
- Extend the existing RuntimeGraph failed-invocation event allowlist with the safe PR-3 identity fields in a dedicated Runtime/Trace change; failure objects already carry them, but PR-3 intentionally did not modify protected RuntimeGraph control code.

## Independent hygiene

- Migrate legacy agent fields to explicit AgentNode + EXECUTION declarations to remove the 44 deprecation warnings. This is an execution-model migration, not Prompt Runtime work.
