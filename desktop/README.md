# 知弈 AgentOS Desktop

Phase 1 is a Tauri 2 native shell around the existing Vue frontend. The desktop app does not bundle or supervise Backend, AgentOS, Docker, Python, Java, PostgreSQL, or Redis.

## Development

Start the existing local runtime first:

```powershell
./scripts/infra/windows/up.ps1 -DebugPorts
```

Then start the existing Vite frontend and the Tauri shell in separate terminals:

```powershell
Set-Location frontend
npm ci
npm run dev
```

```powershell
Set-Location desktop
npm install
npm run dev
```

The Tauri hook starts Vite in `desktop` mode at `http://127.0.0.1:3000`. Desktop API, SSE, WebSocket, and Runtime health requests use the same host Gateway as the browser frontend: `http://127.0.0.1:18088`.

## Build

```powershell
Set-Location desktop
npm install
npm run build
```

The build command first runs `frontend`'s `build:desktop` with the `desktop` mode. `frontend/.env.desktop` points API requests at the host Gateway `http://127.0.0.1:18088`, then Tauri bundles `frontend/dist`.

## Architecture

```text
Zhiyi Desktop
      |
      v
Tauri 2 + native plugins
      |
      v
Existing Vue frontend (frontend/)
      |
      +-- HTTP / SSE / WebSocket / health
      v
Existing host HTTP Gateway :18088
      |
      v
Existing Spring Backend :8080 (Docker internal)
      |
      v
Existing AgentOS / WKN Runtime
```

The platform adapter exposes file picker, directory picker, native notification, and external URL actions. The desktop shell checks the existing Backend readiness endpoint and shows an explicit offline state without starting or retrying runtime processes.

## Phase 2 deferred

Runtime Supervisor, Backend sidecar, Python/Java packaging, Docker installation or launch, tray, updater, local shell execution, automatic recovery, and a full Desktop Capability Broker remain deferred.
