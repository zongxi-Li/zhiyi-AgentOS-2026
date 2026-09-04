# Repository P0 Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove P0 repository noise and relocate unreferenced or misplaced material without changing the current `agent/` and `agentOS/` runtime split.

**Architecture:** Preserve the current application/runtime Module split and the canonical Compose overlay Interface. Delete only the empty observability overlay and the unreferenced third-party study Module. Move delivery evidence and QA material into `docs/` or `scripts/`, and move the frontend-owned prompt into the frontend Module while updating its build Seam references.

**Tech Stack:** Git worktree, PowerShell, Docker Compose YAML, Vue/Vite raw Markdown import, Markdown documentation.

---

### Task 1: Capture the dirty-worktree boundary

**Files:**
- Read: `git status --short --branch`
- Read: `git status --short -- frontend/grok-icon-study-main compose.observability.yaml ACG 提示词.md design-qa.md _verify_desktop_scroll.ps1 artifacts output docs`

- [ ] **Step 1: Confirm all P0 targets are not already modified by the user.**

Run:

```powershell
git status --short -- frontend/grok-icon-study-main compose.observability.yaml "ACG 提示词.md" design-qa.md _verify_desktop_scroll.ps1 artifacts output docs
```

Expected: no pre-existing modifications for the exact P0 targets, or stop and preserve any conflicting user edits.

### Task 2: Remove P0-only dead material

**Files:**
- Delete: `compose.observability.yaml`
- Delete: `frontend/grok-icon-study-main/`

- [ ] **Step 1: Reconfirm both deletion targets and their reference counts.**

Run:

```powershell
Test-Path "compose.observability.yaml"
Test-Path "frontend/grok-icon-study-main"
@(rg -l --fixed-strings "compose.observability.yaml" . 2>$null).Count
@(rg -l --fixed-strings "grok-icon-study-main" . 2>$null).Count
```

Expected: both paths exist; the study directory has zero references; the Compose file is referenced only by the historical Docker documentation.

- [ ] **Step 2: Delete the exact targets.**

Run:

```powershell
Remove-Item -LiteralPath "frontend/grok-icon-study-main" -Recurse -Force
Remove-Item -LiteralPath "compose.observability.yaml" -Force
```

Expected: only those exact targets are removed; `.venv`, `node_modules`, `.worktrees`, databases, and unrelated changes remain untouched.

### Task 3: Move P0 evidence and QA material

**Files:**
- Move: `design-qa.md` → `docs/04-演示与交付/design-qa.md`
- Move: `_verify_desktop_scroll.ps1` → `scripts/qa/verify-desktop-scroll.ps1`
- Move: `artifacts/architecture/kinlin-agentos-current-architecture.md` → `docs/02-架构设计/kinlin-agentos-current-architecture.md`
- Move: `output/video_intro/` → `docs/04-演示与交付/video_intro/`

- [ ] **Step 1: Confirm destination paths do not exist and source files have no references.**

Run:

```powershell
Test-Path "docs/04-演示与交付/design-qa.md"
Test-Path "scripts/qa/verify-desktop-scroll.ps1"
Test-Path "docs/02-架构设计/kinlin-agentos-current-architecture.md"
Test-Path "docs/04-演示与交付/video_intro"
```

Expected: all destination paths are absent.

- [ ] **Step 2: Create only the required destination directories.**

Run:

```powershell
New-Item -ItemType Directory -Path "scripts/qa" -Force | Out-Null
New-Item -ItemType Directory -Path "docs/04-演示与交付/video_intro" -Force | Out-Null
```

- [ ] **Step 3: Move the exact files and directory.**

Run:

```powershell
Move-Item -LiteralPath "design-qa.md" -Destination "docs/04-演示与交付/design-qa.md"
Move-Item -LiteralPath "_verify_desktop_scroll.ps1" -Destination "scripts/qa/verify-desktop-scroll.ps1"
Move-Item -LiteralPath "artifacts/architecture/kinlin-agentos-current-architecture.md" -Destination "docs/02-架构设计/kinlin-agentos-current-architecture.md"
Get-ChildItem -LiteralPath "output/video_intro" -Force | Move-Item -Destination "docs/04-演示与交付/video_intro"
Remove-Item -LiteralPath "output/video_intro" -Force
```

Expected: the four source locations are absent and all content exists at the destination locations.

### Task 4: Move the frontend-owned ACG prompt

**Files:**
- Move: `ACG 提示词.md` → `frontend/src/assets/prompts/ACG 提示词.md`
- Modify: `frontend/src/views/CreateMissionView.vue`
- Modify: `frontend/Dockerfile`
- Modify: `compose.dev.yaml`

- [ ] **Step 1: Create the frontend prompt directory and move the prompt.**

Run:

```powershell
New-Item -ItemType Directory -Path "frontend/src/assets/prompts" -Force | Out-Null
Move-Item -LiteralPath "ACG 提示词.md" -Destination "frontend/src/assets/prompts/ACG 提示词.md"
```

- [ ] **Step 2: Update the Vue raw import.**

Change:

```ts
import defaultAcgPromptMarkdown from '../../../ACG 提示词.md?raw'
```

to:

```ts
import defaultAcgPromptMarkdown from '../assets/prompts/ACG 提示词.md?raw'
```

- [ ] **Step 3: Remove obsolete Docker and Compose mounts.**

Delete the `COPY ["ACG 提示词.md", "/ACG 提示词.md"]` line from `frontend/Dockerfile`, and delete the `./ACG 提示词.md:/ACG 提示词.md:ro` volume entry from `compose.dev.yaml`.

- [ ] **Step 4: Verify no stale prompt path remains.**

Run:

```powershell
rg -n --fixed-strings "ACG 提示词.md" .
rg -n --fixed-strings "../../../ACG 提示词.md" .
```

Expected: the remaining references point to the frontend asset, display text, or frontend-owned path; no root-level Docker/Compose mount remains.

### Task 5: Verify P0 boundaries

**Files:**
- Read: `git status --short`
- Read: `docs/README.md`
- Read: `frontend/package.json`
- Read: `compose.yaml`, `compose.dev.yaml`, `compose.prod.yaml`, `compose.windows.yaml`, `compose.windows.prod.yaml`, `compose.release.yaml`

- [ ] **Step 1: Confirm deleted and moved paths.**

Run:

```powershell
Test-Path "compose.observability.yaml"
Test-Path "frontend/grok-icon-study-main"
Test-Path "docs/04-演示与交付/design-qa.md"
Test-Path "scripts/qa/verify-desktop-scroll.ps1"
Test-Path "docs/02-架构设计/kinlin-agentos-current-architecture.md"
Test-Path "docs/04-演示与交付/video_intro"
Test-Path "frontend/src/assets/prompts/ACG 提示词.md"
```

Expected: the first two values are `False`; the remaining five are `True`.

- [ ] **Step 2: Run formatting/path checks.**

Run:

```powershell
git diff --check
```

Expected: exit code 0 with no whitespace errors.

- [ ] **Step 3: Build the frontend to validate the moved raw Markdown import.**

Run:

```powershell
Set-Location frontend
npm run build:web
Set-Location ..
```

Expected: exit code 0.

- [ ] **Step 4: Validate Compose files still parse without starting services.**

Run:

```powershell
docker compose -f compose.yaml -f compose.dev.yaml config --quiet
```

Expected: exit code 0, subject only to the local Docker Compose installation.

- [ ] **Step 5: Inspect the final diff and report pre-existing changes separately.**

Run:

```powershell
git status --short
git diff --stat
git diff --check
```

Expected: only the planned P0 deletions, moves, prompt-reference changes, and the plan file appear as new work; existing staged/unstaged user changes remain intact.
