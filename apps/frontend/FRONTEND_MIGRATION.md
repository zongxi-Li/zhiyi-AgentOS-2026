# Frontend migration status

The Workbench is the primary surface for Mission and Run work. The legacy chat
route remains active because it still owns independent conversation sessions,
context compaction, command and file approvals, and starting a workflow from a
conversation. Those flows do not yet have one-for-one Workbench equivalents.

| Capability | Current owner | Migration status |
| --- | --- | --- |
| Mission and Run navigation, graph, trace, artifacts, recovery and runtime inspection | `MissionWorkspaceView` and Workbench contributions | Primary Workbench path |
| Independent conversation history and context lifecycle | `ChatView` at `/chat` | Active; not migrated |
| Command/file approval and conversation-scoped execution | `ChatView` | Active; migration target not defined |
| Start a workflow from conversation context | `ChatView` | Active; keep until equivalent handoff is implemented |
| Legacy federation and console URLs | Router redirects | Compatibility only; preserve redirects |
| Unreferenced federation, ACG inspector and utility components | Removed from source | Dead code removed after reference checks |

`RuntimeInspector` and `ProjectRunInspector` remain separate: the former handles
the Mission Workspace runtime context, while the latter contributes a compact
Run status projection in the project workbench. Consolidation requires a
shared contract and interaction review; matching names alone are insufficient.

Next migration checkpoint: map each active `ChatView` capability to a Workbench
owner, add route-level regression coverage for the transferred flow, then remove
the old implementation only after the capability and session behavior match.
