# Prompt Runtime PR-0/PR-1 Implementation

## Changes

- `adapters/prompt_runtime.py`: static AgentOS Kernel, Planner preset, deterministic composition and untrusted-source serialization.
- `adapters/model_adapter.py`, `guarded_model.py`, `model_runtime.py`: optional explicit `system_prompt` propagated through the existing sync/stream structured generation contracts.
- `components/planner/complexity.py`: injects Planner system authority at the one shared Planner invocation boundary, covering intent, decomposition, staged and repair calls.
- `components/planner/intent_analyzer.py`: serializes the intent PlanningRequest with source trust labels.
- `components/planner/task_decomposer.py`: removes approximate task-count targets and directs the model to the smallest sufficient plan.
- `adapters/openai_runtime.py`: preserves generic messages; GLM merges its compatibility schema instruction after an existing AgentOS system prefix.

## Compatibility

`system_prompt` is optional, so Executor and existing callers retain their behavior. Timeout, retry, failover, token policy, usage, tracing projection, streaming and provider-native structured output remain on the existing paths. Deterministic capability lookup and topology compilation are unchanged.

## Test results

- Focused command: `pytest -q tests/adapters/test_model_runtime.py tests/adapters/test_openai_runtime.py tests/components/planner/test_prompt_runtime_pr01.py tests/components/planner/test_prompt_capability_v2.py tests/components/planner/test_hierarchical_task_decomposition.py tests/components/planner/test_planning_budget_steering.py tests/components/planner/test_planner_runtime_streaming.py tests/components/planner/test_topology_compiler.py`
- Result: 89 passed, 0 failed, 0 skipped.
- Extended Prompt/Planner/runtime command: `pytest -q tests/components/planner tests/adapters/test_model_runtime.py tests/adapters/test_model_runtime_streaming.py tests/adapters/test_openai_runtime.py tests/adapters/test_guarded_runtime.py tests/runtime/test_app_setup.py tests/runtime/test_model_binding.py tests/runtime/test_runtime_guards.py`
- Result: 137 passed, 0 failed, 0 skipped.
- Broad command: `pytest -q tests/components/planner tests/adapters tests/runtime`
- Result: 321 passed, 4 failed, 0 skipped. All four failures are pre-existing environment collection failures in `tests/adapters/test_resource_execution.py`: async tests cannot run because the installed pytest environment lacks an async plugin. They do not execute Prompt Runtime code.
- Compile check: `python -m compileall -q src/adapters src/components/planner` passed.

## Remaining risks and follow-ups

- PR-2: migrate Executor/native capability prompts, remove `systemBoundary` as simulated authority, and introduce capability-specific policies.
- PR-3: normalize prompt template/instance hashes and tracing semantics, add behavior-level injection evals, and converge provider edge cases.
- Artifact synthesis and verification still use Executor prompt architecture.
- Memory/upstream-output trust classification is available in the serializer but needs Executor integration.
- Provider behavior beyond covered generic OpenAI-compatible and GLM paths requires compatibility evaluation.
