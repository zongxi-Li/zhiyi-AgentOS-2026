# Prompt Runtime PR-2 Capability Matrix

All schemas remain the existing catalog `outputContract`. Required tools are requirements/preferences only; actual availability is exclusively runtime-controlled.

| Capability | Purpose | Execution principles | Evidence policy | Quality focus | Tool semantics | Output schema required fields | Preset |
|---|---|---|---|---|---|---|---|
| task_understanding | Resolve task scope | Separate mission, constraints, criteria, assumptions, unknowns | Supplied/tool evidence only | Explicit bounded understanding | None | `task_summary`, `constraints` | Executor |
| information_extraction | Extract traceable items | Map every item to source; preserve conflicts | Cite supplied source | No added facts | None | `extracted_information` | Executor |
| information_retrieval | Retrieve missing information | Preserve identity and gaps | Runtime-produced source refs | Traceable retrieval boundary | Requests knowledge_search; runtime must bind | `retrieved_information`, `evidence_refs` | Executor/tool path |
| requirement_analysis | Produce testable requirements | Trace needs and constraints | Cite origin | Testability and acceptance | None | `requirements`, `acceptance_criteria` | Executor |
| process_decomposition | Define executable process | Inputs, outputs, owners, dependencies, gates | Cite basis | Complete process contract | None | `process_steps` | Executor |
| resource_planning | Estimate resources/capacity | Units, utilization, bottlenecks, missing inputs | Cite inputs/assumptions | Reproducible capacity basis | None | `resource_plan`, `capacity_plan` | Executor |
| architecture_design | Define system structure | Boundaries, interfaces, ownership, direction, failure boundaries, trade-offs | Unsupported components are assumptions | Coherent responsibilities | None | `architecture`, `components`, `data_flow` | Executor |
| analysis | Analyze bounded question | Findings vs derivations vs gaps | Cite factual claims | Scope discipline | None | `analysis` | Executor |
| evidence_analysis | Assess claim support | Claim mapping, quality, conflict, coverage | Source existence is not proof | Contradictions explicit | None | `evidence_analysis`, `evidence_refs` | Executor |
| comparative_analysis | Compare alternatives | Same criteria and evidence standard | Expose missing-data asymmetry | Fair comparison | None | `comparison`, `alternatives` | Executor |
| cost_analysis | Calculate cost | Basis, formula, input, unit, assumption, result, source | Missing rates stay unknown | Reproducible totals | None | `cost_analysis`, `cost_drivers` | Executor |
| risk_analysis | Analyze risk | Cause, trigger, impact, likelihood basis, mitigation, residual risk | No fabricated probability | Evidence-backed risk record | None | `risk_analysis`, `risks` | Executor |
| solution_design | Design bounded solution | Trace requirements, interfaces, resources, risks, verification | Unsupported choices are assumptions | No scope expansion | None | `solution_design` | Executor |
| verification | Judge candidate | Never improve candidate; inspect each criterion | Candidate self-attestation is insufficient | Failed/unresolved explicit | None | `verification` | Verifier |
| artifact_generation | Produce requested artifact | Contract-driven structure; preserve uncertainty/provenance | Separate upstream conclusions from evidence | Complete requested deliverable | None | `deliverable`, `final_answer`, `verification`, `artifact` | Synthesizer |
