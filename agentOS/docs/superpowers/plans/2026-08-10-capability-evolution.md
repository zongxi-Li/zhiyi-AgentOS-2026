# Capability Compatibility and Evolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish importable contracts and service facades for external capability compatibility plus graph and Skills self-evolution, while deliberately deferring runtime algorithms.

**Architecture:** External adapters depend only on `contracts.capability`; the evolution component depends only on `contracts.evolution`. The service facades produce or validate future evolution proposals and never directly mutate a running graph or skill registry.

**Tech Stack:** Python 3, Pydantic v2, `typing.Protocol`, pytest.

---

### Task 1: Define public capability contracts

**Files:**
- Create: `src/contracts/capability.py`
- Test: `tests/test_capability_evolution_architecture.py`

- [ ] Define provider, agent architecture, framework, tool protocol and capability-kind enums.
- [ ] Define frozen Pydantic request, response, manifest and invocation envelope models with camelCase aliases.
- [ ] Verify imports and the four stable capability kinds.

### Task 2: Define adapter boundaries

**Files:**
- Create: `src/adapters/model_compatibility.py`
- Create: `src/adapters/agent_architecture.py`
- Create: `src/adapters/skill_tool_compatibility.py`

- [ ] Define one `Protocol` per adapter type and a registry facade that raises an explicit Chinese `NotImplementedError` until its runtime implementation exists.
- [ ] Keep SDK imports, authentication, session state and network behavior out of these modules.

### Task 3: Define self-evolution contracts and facades

**Files:**
- Create: `src/contracts/evolution.py`
- Create: `src/components/evolution/__init__.py`
- Create: `src/components/evolution/models.py`
- Create: `src/components/evolution/skill_service.py`
- Create: `src/components/evolution/graph_service.py`

- [ ] Define trajectory, multi-dimensional evaluation, candidate skill, skill lifecycle proposal and graph evolution proposal models.
- [ ] Define independent Skills and graph service facades whose algorithmic boundaries are documented in Chinese TODO text.

### Task 4: Document and verify the architecture

**Files:**
- Create: `docs/capability-evolution-design.md`
- Test: `tests/test_capability_evolution_architecture.py`

- [ ] Document provider/framework coverage, adapter boundaries, trajectory-to-skill loop, graph evolution boundary and governance rules.
- [ ] Run focused import and syntax checks, recording any baseline collection failures separately.
