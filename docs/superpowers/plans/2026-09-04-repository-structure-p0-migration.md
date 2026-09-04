# Repository Structure P0 Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收敛仓库根目录，将应用、运维、非生产配置分别归档到 `apps/`、`ops/`、隐藏的 `.config/`，并让根目录只保留生产 `compose.yaml` 与生产 `.env.example`。

**Architecture:** 保留 `agent/` 与 `agentOS/` 的运行时边界，仅改变它们在仓库中的父目录；Compose 以根 `compose.yaml` 作为完整生产定义，开发、Windows、离线发布通过 `.config/compose/` 中的覆盖文件叠加。非生产环境模板集中到 `.config/env/`，真实 `.env`、`.env.windows` 与 secrets 继续作为本地状态处理。

**Tech Stack:** PowerShell、Git、Docker Compose、Python、Maven/Spring Boot、Vue/Vite、Tauri。

---

### Task 1: Record the dirty-worktree boundary and inventory active path references

**Files:**
- Read: `git status --short --branch`
- Read: root Compose/env files, `dev.ps1`, `dev.sh`, `docker-bake.hcl`
- Read: `scripts/`, `deploy/`, `docker/`, all Dockerfiles and current documentation

- [ ] **Step 1: Capture existing staged and unstaged changes.**

Run:

```powershell
git status --short --branch
git diff --name-status
git diff --cached --name-status
```

Expected: preserve all existing changes; do not reset, restore, clean, commit, or push.

- [ ] **Step 2: Inventory path-sensitive references before moving anything.**

Run:

```powershell
rg -n --hidden --glob '!.git/**' --glob '!.venv/**' --glob '!**/node_modules/**' --glob '!data/**' --glob '!**/*.lock' 'compose\.(dev|prod|release|windows|windows\.prod)\.yaml|\.env\.windows|deploy/\.env\.prod|\./(agent|agentOS|backend|frontend|desktop|docker|deploy|scripts)(/|$)|(^|[^A-Za-z])((agent|agentOS|backend|frontend|desktop|docker|deploy|scripts)/)' .
```

Expected: produce the source-of-truth list used by later path updates; historical documentation is reviewed rather than mechanically rewritten.

### Task 2: Create the target grouping and move application/operations trees

**Files:**
- Create: `apps/`
- Create: `ops/`
- Move: `agent/` → `apps/agent/`
- Move: `agentOS/` → `apps/agentOS/`
- Move: `backend/` → `apps/backend/`
- Move: `frontend/` → `apps/frontend/`
- Move: `desktop/` → `apps/desktop/`
- Move: `docker/` → `ops/docker/`
- Move: `deploy/` → `ops/deploy/`
- Move: `scripts/` → `ops/scripts/`

- [ ] **Step 1: Confirm destination directories are not occupied.**

Run:

```powershell
foreach ($path in @('apps','ops','apps/agent','apps/agentOS','apps/backend','apps/frontend','apps/desktop','ops/docker','ops/deploy','ops/scripts')) { if (Test-Path -LiteralPath $path) { throw "Target already exists: $path" } }
```

Expected: no output and exit code 0.

- [ ] **Step 2: Create grouping directories and move exact trees.**

Run:

```powershell
New-Item -ItemType Directory -Path 'apps','ops' | Out-Null
Move-Item -LiteralPath 'agent' -Destination 'apps/agent'
Move-Item -LiteralPath 'agentOS' -Destination 'apps/agentOS'
Move-Item -LiteralPath 'backend' -Destination 'apps/backend'
Move-Item -LiteralPath 'frontend' -Destination 'apps/frontend'
Move-Item -LiteralPath 'desktop' -Destination 'apps/desktop'
Move-Item -LiteralPath 'docker' -Destination 'ops/docker'
Move-Item -LiteralPath 'deploy' -Destination 'ops/deploy'
Move-Item -LiteralPath 'scripts' -Destination 'ops/scripts'
```

Expected: every source tree is absent and present at its exact target; no file contents are edited by this step.

### Task 3: Consolidate Compose definitions and non-production templates

**Files:**
- Modify: `compose.yaml`
- Create: `.config/compose/`
- Move: `compose.dev.yaml` → `.config/compose/dev.yaml`
- Move: `compose.windows.yaml` → `.config/compose/windows.yaml`
- Move: `compose.windows.prod.yaml` → `.config/compose/windows-prod.yaml`
- Move: `compose.release.yaml` → `.config/compose/release.yaml`
- Delete: `compose.prod.yaml` after merging its exact production service settings into `compose.yaml`

- [ ] **Step 1: Create the hidden Compose configuration directory and move non-production overlays.**

Run:

```powershell
New-Item -ItemType Directory -Path '.config/compose' -Force | Out-Null
Move-Item -LiteralPath 'compose.dev.yaml' -Destination '.config/compose/dev.yaml'
Move-Item -LiteralPath 'compose.windows.yaml' -Destination '.config/compose/windows.yaml'
Move-Item -LiteralPath 'compose.windows.prod.yaml' -Destination '.config/compose/windows-prod.yaml'
Move-Item -LiteralPath 'compose.release.yaml' -Destination '.config/compose/release.yaml'
```

- [ ] **Step 2: Merge production security anchors and service overrides into root `compose.yaml`.**

Insert the `x-prod-security-base` and `x-prod-secret-tmpfs` anchors from the former `compose.prod.yaml` at the root level, then merge the production fields into the corresponding root services:

```yaml
x-prod-security-base: &prod-security-base
  read_only: true
  cap_drop: [ALL]
  security_opt: [no-new-privileges:true]

x-prod-secret-tmpfs: &prod-secret-tmpfs
  - /run/secrets:rw,nosuid,nodev,noexec,size=1m,mode=0755
```

Apply `<<: *prod-security-base` to `frontend`, `backend`, `ai-service`, `postgres`, `redis`, and `schema-tool`; preserve the existing service fields and add the former production `ports`, `cpus`, `mem_limit`, `cap_add`, and `tmpfs` values exactly. The merged root file must remain the production configuration and must not add development bind mounts or Windows debug services.

- [ ] **Step 3: Remove the obsolete production overlay.**

Run:

```powershell
Remove-Item -LiteralPath 'compose.prod.yaml' -Force
```

Expected: root has exactly one `compose*.yaml`, namely `compose.yaml`.

- [ ] **Step 4: Update Compose-relative paths after the application/operations move.**

Use these exact path mappings in all Compose files:

```text
./agent        -> ./apps/agent
./agentOS      -> ./apps/agentOS
./backend      -> ./apps/backend
./frontend     -> ./apps/frontend
./docker       -> ./ops/docker
./migrations   -> ./apps/backend/src/main/resources/db/migration
```

For the release overlay, keep the migration source as `./apps/backend/src/main/resources/db/migration:/flyway/sql:ro`; do not invent a root `migrations/` directory.

### Task 4: Consolidate environment templates and preserve local state

**Files:**
- Modify: `.env.example` to contain the production template from `ops/deploy/.env.prod.example`
- Create: `.config/env/`
- Move: `.env.windows.example` → `.config/env/windows.example`
- Move: `ops/deploy/windows/package/.env.example` → `.config/env/package.example`
- Create: `.config/env/release.example` from the release-specific non-secret image settings currently required by offline packaging
- Preserve: `.env`, `.env.windows`, and `ops/deploy/windows/package/.env` if present; do not delete or rewrite real local values

- [ ] **Step 1: Create the hidden environment template directory and move templates.**

Run:

```powershell
New-Item -ItemType Directory -Path '.config/env' -Force | Out-Null
Move-Item -LiteralPath '.env.windows.example' -Destination '.config/env/windows.example'
Move-Item -LiteralPath 'ops/deploy/windows/package/.env.example' -Destination '.config/env/package.example'
```

- [ ] **Step 2: Replace root `.env.example` with the production template.**

Root `.env.example` must contain the production non-secret defaults and deployment comments currently defined in `ops/deploy/.env.prod.example`, plus the optional production model/runtime variables that `compose.yaml` reads. It must not be labeled `development`, must not use `kinlin-dev-yourname`, and must not contain Windows debug or polling settings.

- [ ] **Step 3: Add a release template containing all image variables used by `compose.release.yaml` and Windows package variables.**

`.config/env/release.example` must define `KINLIN_DEPLOYMENT_ID`, `KINLIN_SECRETS_DIR`, `KINLIN_DB_NAME`, `KINLIN_DB_USER`, `KINLIN_PUBLIC_ORIGIN`, and the six image variables `KINLIN_FRONTEND_IMAGE`, `KINLIN_BACKEND_IMAGE`, `KINLIN_AI_IMAGE`, `KINLIN_POSTGRES_IMAGE`, `KINLIN_REDIS_IMAGE`, `KINLIN_FLYWAY_IMAGE`; values are placeholders only and no secrets are added.

- [ ] **Step 4: Update ignore rules for the new locations.**

Change `.gitignore` and `.dockerignore` path rules so generated caches and local state remain ignored under `apps/` and `ops/`, while `.config/env/*.example` and `.config/compose/*.yaml` remain trackable. Keep `.secrets/`, real `.env`, databases, logs, `node_modules`, `dist`, and virtual environments ignored.

### Task 5: Update launchers, packaging, deployment scripts, Docker build contexts, tests, and active docs

**Files:**
- Modify: `dev.ps1`, `dev.sh`, `docker-bake.hcl`
- Modify: `apps/*/Dockerfile*`, `ops/scripts/**`, `ops/deploy/**`, `README.md`, active docs and tests that reference current paths
- Modify: `ops/scripts/release/package_offline.py`, `ops/scripts/infra/common.py`, `ops/scripts/infra/windows/_common.ps1`, `ops/scripts/infra/windows/package.ps1`, and their tests

- [ ] **Step 1: Make launchers resolve Compose and scripts from the new paths.**

Use:

```text
compose.dev.yaml                 -> .config/compose/dev.yaml
compose.windows.yaml             -> .config/compose/windows.yaml
compose.windows.prod.yaml        -> .config/compose/windows-prod.yaml
compose.release.yaml             -> .config/compose/release.yaml
scripts/                         -> ops/scripts/
deploy/                          -> ops/deploy/
docker/                          -> ops/docker/
```

`dev.ps1` must pass the repository root and `.config/compose/windows.yaml` to the Windows scripts; `dev.sh` must use `-f .config/compose/dev.yaml` and `python -m ops.scripts.infra.preflight`.

- [ ] **Step 2: Update Docker build contexts and internal paths.**

Change root build references to:

```text
agent/Dockerfile        -> apps/agent/Dockerfile
frontend/Dockerfile     -> apps/frontend/Dockerfile
./docker/<service>      -> ./ops/docker/<service>
./backend               -> ./apps/backend
./frontend              -> ./apps/frontend
```

Inside container paths such as `/app/agent`, `/app/agentOS`, `/app/workspace/backend`, and `/app/workspace/frontend` remain unchanged unless they are host paths; only host-side repository references change.

- [ ] **Step 3: Update offline release and Windows packaging path resolution.**

Packaging code must resolve the repository root once, then locate `apps/`, `ops/docker/`, `ops/deploy/`, and `.config/compose/` from that root. Generated packages may still expose a deployment-oriented flat layout where the runtime contract requires it, but source collection must use the new repository paths and the selected Compose files must be copied under their documented names.

- [ ] **Step 4: Update active documentation and tests.**

Update current README/deployment/operations docs and path assertions to show the target structure and commands:

```powershell
docker compose --env-file .env.example -f compose.yaml config --quiet
docker compose --env-file .config/env/windows.example -f compose.yaml -f .config/compose/windows.yaml config --quiet
docker compose --env-file .config/env/release.example -f compose.yaml -f .config/compose/release.yaml config --quiet
```

Do not rewrite archived documents when the old path is historical evidence rather than an active command.

### Task 6: Verify the final P0 boundary

**Files:**
- Read: final tree, `git diff --check`, Compose configs, focused packaging tests

- [ ] **Step 1: Assert root cleanliness contract.**

Run:

```powershell
@(Get-ChildItem -File -Filter 'compose*.yaml').Name
@(Get-ChildItem -File -Filter '.env*' -Force).Name
Test-Path 'apps/agent'
Test-Path 'apps/agentOS'
Test-Path 'ops/docker'
Test-Path 'ops/deploy'
Test-Path 'ops/scripts'
```

Expected: only `compose.yaml` and `.env.example` match the tracked production files; the two real local files may exist but are not edited or tracked.

- [ ] **Step 2: Parse production, development, Windows, and release Compose configurations.**

Run the three `docker compose ... config --quiet` commands from Task 5, plus the Windows production overlay using `.config/compose/windows-prod.yaml`. Expected: all exit code 0 without starting services.

- [ ] **Step 3: Run focused and component verification.**

Run:

```powershell
git diff --check
Set-Location apps/frontend; npm run test -- --run; npm run build:web; Set-Location ../..
Set-Location apps/agent; ..\.venv\Scripts\python.exe -m pytest -q; Set-Location ../..
Set-Location apps/agentOS; ..\.venv\Scripts\python.exe -m pytest -q; Set-Location ../..
```

Also run the backend test command documented by `apps/backend/README.md` if its dependencies are available. Expected: no path/import regressions attributable to this migration.

- [ ] **Step 4: Search for stale active references and inspect diff.**

Run:

```powershell
rg -n --hidden --glob '!.git/**' --glob '!**/node_modules/**' --glob '!**/*.lock' 'compose\.(dev|prod|release|windows|windows\.prod)\.yaml|\.env\.windows\.example|deploy/\.env\.prod|(?<!apps/)\./(agent|agentOS|backend|frontend|desktop)|(?<!ops/)\./(docker|deploy|scripts)' --pcre2 .
git status --short
git diff --stat
```

Expected: no stale active references; any remaining old paths are explicitly historical or generated package contract text and are reviewed individually.

