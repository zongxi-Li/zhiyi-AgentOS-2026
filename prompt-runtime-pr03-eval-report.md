# Prompt Runtime PR-3 Eval Report

## Configuration

- Date: `2026-09-18`
- Provider: `not configured`
- Model: `not configured`
- Model version: `not configured`
- Temperature: `0.0 planned`
- Seed: `not set; provider-independent seed is not supported by the current runtime`
- Planned runs per case: `2`
- Executed runs per case: `0`
- Status: **NOT RUN**

The workspace contains no `AGENTOS_MODELS` environment configuration, root `.env`, AgentOS `.env`, or model credentials. No remote model was invoked and no behavioral success claim is made.

## Evaluation Design

| Evaluation | Designed cases | Planned observations | Executed | Passed | Failed | Status |
|---|---:|---:|---:|---:|---:|---|
| Injection | 5 | 10 | 0 | 0 | 0 | NOT CONFIRMED |
| Graph Parsimony | 1 paired case | 2 pairs | 0 | 0 | 0 | NOT CONFIRMED |
| Capability Differentiation | 4 | 8 | 0 | 0 | 0 | NOT CONFIRMED |
| False Tool Claim | 1 | 2 | 0 | 0 | 0 | NOT CONFIRMED |
| Verifier Resistance | 1 | 2 | 0 | 0 | 0 | NOT CONFIRMED |
| Synthesizer Hallucination | 1 | 2 | 0 | 0 | 0 | NOT CONFIRMED |

Injection cases cover uploaded/source data, memory, upstream agent output, tool observation and plugin payload, including Chinese and English attacks. Parsimony reuses `software-02` from `evals/prompt_orchestration_v2.json` and compares it with a rhetoric-only complexity inflation while retaining deterministic topology compilation.

## Failure Examples

No model outputs exist. The blocking example is environmental: the explicit runner terminates before invocation with `AGENTOS_MODELS is not configured; no model-backed eval was run`.

## Run Command

```powershell
python evals/run_prompt_runtime_pr03.py --runs 2 --temperature 0 --output ..\..\prompt-runtime-pr03-eval-report.md
```

The runner also writes a JSON sidecar when an eval actually runs. It is opt-in and is not part of pytest or default CI.

## Limitations

The case manifest and runner are implemented, but this report is not behavioral evidence until a configured provider is invoked. Even after execution, results are bounded to the recorded model snapshot, provider, date and configuration; they cannot establish universal injection resistance. Prompt hashes provide invocation identity, not confidentiality or encryption.
