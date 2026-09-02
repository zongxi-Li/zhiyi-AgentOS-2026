# AgentOS Remote Resource Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add authenticated remote resource registration and signed observation updates without weakening the existing internal service boundary.

**Architecture:** Keep resource identity and snapshot truth in the existing `ResourceService` and SQLite resource database. Add a credential/nonce table beside the resource table; the service issues a one-time secret and verifies HMAC-SHA256 requests using a canonical request string. The FastAPI router remains a thin adapter and requires the existing internal middleware plus resource-level headers.

**Tech Stack:** Python 3, Pydantic, FastAPI, SQLite, pytest, HMAC-SHA256.

---

### Task 1: Add persistent resource credential records

**Files:**
- Modify: `agentOS/src/components/resource/store.py`
- Modify: `agentOS/src/components/resource/service.py`
- Test: `agentOS/tests/components/resource/test_resource_auth.py`

- [ ] **Step 1: Write failing tests** for issuing a credential, verifying a secret after reopening SQLite, rejecting unknown credentials, and consuming a nonce only once.
- [ ] **Step 2: Run `agent\\.venv\\Scripts\\python.exe -m pytest agentOS/tests/components/resource/test_resource_auth.py -q` and confirm collection or assertion failure because credential APIs do not exist.
- [ ] **Step 3: Add a private credential record and store methods for issue, lookup, and atomic nonce consumption; keep only a SHA-256 secret hash and never persist the raw secret.
- [ ] **Step 4: Expose minimal `ResourceService.issue_credential`, `credential`, and `consume_nonce` methods and run the focused test until it passes.
- [ ] **Step 5: Commit with `feat: persist remote resource credentials`.

### Task 2: Implement canonical HMAC authentication

**Files:**
- Create: `agentOS/src/components/resource/auth.py`
- Test: `agentOS/tests/components/resource/test_resource_auth.py`

- [ ] **Step 1: Add failing tests** for canonical signing, wrong resource ID, wrong credential ID, mismatched signature, expired timestamp, and replayed nonce.
- [ ] **Step 2: Run the focused authentication tests and confirm failure because the verifier is absent.
- [ ] **Step 3: Implement `ResourceRequestAuthenticator` with `method + path + timestamp + nonce + sha256(body)` canonicalization, constant-time HMAC comparison, bounded clock skew, and atomic nonce consumption.
- [ ] **Step 4: Run the focused authentication tests and refactor only after all remain green.
- [ ] **Step 5: Commit with `feat: authenticate signed resource requests`.

### Task 3: Add protected registration and observation API

**Files:**
- Modify: `agent/app/api/agentos_v2.py`
- Modify: `agentOS/src/components/resource/service.py`
- Modify: `agent/tests/test_agentos_v2_api.py`

- [ ] **Step 1: Add failing API tests** for authorized registration, one-time secret response, unauthenticated registration, signed observation success, missing signature, wrong resource credential, expired timestamp, replayed nonce, and stale observation sequence.
- [ ] **Step 2: Run the selected API tests and confirm they fail because registration and resource headers are not implemented.
- [ ] **Step 3: Add strict registration request/response models, require a trusted operator/system actor, validate remote profile constraints, and return the secret only in the registration response.
- [ ] **Step 4: Require resource credential headers on the observation route, verify the raw request body before applying `observe_remote`, and map authentication failures to explicit HTTP statuses.
- [ ] **Step 5: Run the selected API tests and commit with `feat: expose authenticated remote resource API`.

### Task 4: Wire configuration and document the boundary

**Files:**
- Modify: `agent/app/execution/wiring.py`
- Modify: `agentOS/src/components/resource/__init__.py`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-09-02-agentos-remote-resource-auth-design.md`

- [ ] **Step 1: Add a failing wiring test showing the production SQLite resource service has credential storage enabled.
- [ ] **Step 2: Pass the existing SQLite resource store into the authenticator without introducing a second database or an in-memory production fallback.
- [ ] **Step 3: Document required headers, signature construction, one-time secret handling, and the fact that this is resource placement rather than model-layer splitting.
- [ ] **Step 4: Run targeted resource/API/wiring tests and commit with `docs: document remote resource authentication boundary`.

### Task 5: Full verification and branch hygiene

**Files:**
- No frontend files.

- [ ] **Step 1: Run `agentOS\\.venv\\Scripts\\python.exe -m pytest -q` if available, otherwise use the confirmed `agent\\.venv\\Scripts\\python.exe` environment for AgentOS tests.
- [ ] **Step 2: Run `agent\\.venv\\Scripts\\python.exe -m pytest -q` from the `agent` directory.
- [ ] **Step 3: Run `git diff --check` and inspect `git diff --name-only master...HEAD` to confirm only backend and backend documentation changed.
- [ ] **Step 4: Report exact test counts, warnings, commits, and any remaining deployment limitations without claiming real multi-device deployment has been validated.

