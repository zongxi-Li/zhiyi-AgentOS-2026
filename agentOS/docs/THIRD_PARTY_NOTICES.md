# Third-party notices

## LangGraph execution-base attribution

AgentOS incorporates adapted execution concepts and selected implementation structure from
LangGraph **1.2.10**, upstream commit
`d56666f7fbf0d380ad84cdf0cbe5aa48ab0cc086`.

The adapted files identify their source module and modifications in their headers:

- `src/components/executor/graph.py` — StateGraph/Pregel ready-set semantics,
  reduced to AgentOS reference state and AgentOS stream events.
- `src/components/executor/compiler.py` — StateGraph compilation semantics,
  changed to consume the AgentOS ACG Blueprint and enforce communication governance.
- `src/components/recovery/checkpoint.py` — SQLite checkpoint semantics, changed
  to store AgentOS run-reference state under `runId` as SQLite thread ID.
- `src/components/executor/node_runner.py` — node execution semantics, changed
  to use AgentOS ContextPack, MemoryService, adapters and Trace references.
- `src/components/auditor/governance/trace.py` — Pregel event projection,
  changed to emit existing AgentOS `TraceEvent` values only.

Copyright (c) 2024 LangChain, Inc.

### MIT License

MIT License

Copyright (c) 2024 LangChain, Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
