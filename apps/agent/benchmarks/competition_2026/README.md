# Competition 2026 benchmark smoke

This directory contains an external, black-box benchmark harness for the AgentOS HTTP boundary. The smoke runner does **not** import `WorkflowRuntime`, Planner, Scheduler, Provider, or storage internals.

The first smoke case uses one public `THUDM/LongBench` `hotpotqa_e` sample and records four classes of evidence from the real Run:

- LongBench HotpotQA answer quality: token-level F1 against the public reference answers.
- End-to-end latency: wall-clock time from Mission submission until the Run reaches a terminal/review state.
- Provider usage: model-call count, provider/model, input/output/total tokens, retry count, and model latency from AgentOS `/resource-usage` projections.
- Communication efficiency: `tokensAvailable` vs `tokensDelivered` from provenance `DataConsumptionEvent` records. `RuntimeInteraction` mirrors (`int_*`) are excluded so communication is not double-counted.

`comm_tokens_*_est` are AgentOS normalized communication estimates. They are **not** provider billing tokens and must not be used to calculate model cost.

## Run one real sample inside the ai-service container

The production compose topology exposes only the frontend to the host. The simplest no-bypass smoke path is therefore to run the benchmark process inside the existing `ai-service` container and call the service through `127.0.0.1:8000/ai/agentos/v2`. The runner automatically reads the same `AI_INTERNAL_TOKEN_FILE` mounted in the container; it never prints the token.

After checking out this branch, rebuild the AI image once so the new benchmark file is copied into `/app/agent`:

```powershell
git switch benchmark/competition-2026-smoke
docker compose build ai-service
docker compose up -d ai-service
```

Then run exactly one LongBench-E sample:

```powershell
docker compose exec ai-service python /app/agent/benchmarks/competition_2026/smoke_one.py --row 0
```

The default output is written to the persistent AgentOS data volume at:

```text
/app/data/agentos/benchmarks/competition_2026/smoke_result.json
```

Inspect it with:

```powershell
docker compose exec ai-service cat /app/data/agentos/benchmarks/competition_2026/smoke_result.json
```

The command prints a compact summary containing Run status, length bucket, F1, wall latency, model latency, LLM token usage, usage coverage, and communication reduction.

## Idempotency

The default `clientRequestId` is deterministic for the dataset sample, prompt version, and planning seed. Running the same command again will normally reuse the same Run instead of spending another model call. To deliberately force a fresh measurement:

```powershell
docker compose exec ai-service python /app/agent/benchmarks/competition_2026/smoke_one.py --row 0 --force-new-run
```

Do not use `--force-new-run` casually while debugging; it intentionally creates another real Run and may incur provider cost.

## Interpretation guardrails

A completed Run only means the execution chain completed. It does not mean the benchmark answer is correct; answer quality is reported separately as `quality_score`.

`comm_payload_reduction` is calculated as:

```text
1 - sum(tokensDelivered) / sum(tokensAvailable)
```

where only `cons_*` provenance events are aggregated. `tokensAvailable` is the complete payload available from the authorized upstream producer set before ContextPack field selection. It is not an independently executed all-to-all/full-broadcast baseline, so report this metric as **context payload reduction / 上下文有效载荷冗余削减率**, not as a cross-system percentage claim.

The smoke runner intentionally disables web search and plugins for the benchmark Mission so the public reference answer is evaluated against the supplied benchmark context rather than external retrieval.
