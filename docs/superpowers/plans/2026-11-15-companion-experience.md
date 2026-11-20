# Companion Experience Implementation Plan

> For agentic workers: use `subagent-driven-development` for bounded implementation/review tasks and execute coupled integration in this session. The user approved the existing audit and requested implementation followed by a branch commit.

**Goal:** Complete the voice/reply loop, wire existing run events, make persona/edit semantics consistent, reduce Host orchestration, and align the existing renderers.

**Architecture:** Keep the existing Vue presentation and port boundaries. Reuse the workbench's existing run SSE and the platform chat API; no second task executor or new character engine. Conversation, appearance and runtime policies become focused modules/composables with lifecycle cleanup.

**Tech stack:** Vue 3, TypeScript, SVG, Web Speech/local PCM ASR, Fastify/Python chat adapters, Vitest and Electron node tests.

## Accepted design decisions

- Preserve voice-first interaction with visible final transcripts/replies, pending status and a clearly labelled optional keyboard fallback; do not rely on Win+H without an input.
- ASR stop drains accepted audio/results before ending. Abort cancels result delivery and shuts capture immediately, including permission requests resolved later.
- Run selection comes from the verified workbench projection; events are forwarded from the existing SSE client only, with run identity filtering and no extra connection.
- User appearance settings stay local. Send a bounded companion persona through the existing context projection; separate system instruction from user text and disable tools for companion chat. Keep server-owned conversation IDs.
- Preview is transient. Save commits and persists; cancel restores the complete prior appearance/voice/lines and selected skin, including when starting from DIY.
- Extract cohesive appearance/conversation/runtime/position concerns rather than mechanically splitting by line count. Existing integration behavior remains covered.
- Align mouth/listening effects and motion settings across the three SVG skins, validate manifests and honor fallback links. Keep landing showcase controls separate; reuse shared identity where appropriate without changing its demo purpose.

## Task 1: Voice and reply loop

Files: `features/companion/adapters/serverAsr.ts`, `serverAsr.spec.ts`, `voice.ts`, `voice.spec.ts`, `components/companion/CompanionDialogue.vue`, `CompanionHost.vue` and voice integration specs.

- [ ] Reproduce existing ASR/result and hidden-message failures with `node node_modules/vitest/vitest.mjs run src/features/companion src/components/companion --maxWorkers=2 --minWorkers=1`.
- [ ] Correct ASR fixture getter and add delayed-upload/abort/open-source lifecycle regressions before implementation.
- [ ] Use `recording -> finishing -> ended`; stop closes input and drains uploads, abort ends once and suppresses late callbacks.
- [ ] Restore visible bounded messages, processing status, optional fallback input; wire submit to the same command/service path.
- [ ] Verify successful, muted, unsupported and failed reply paths. Preserve cancellation and provide deterministic local chat fallback.

## Task 2: Existing runtime event wiring

Files: `workbench/runtime/runtimeEvents.ts`, `views/MissionWorkspaceView.vue`, new `features/companion/runtimeBridge.ts` and tests, `adapters/progress.ts`, Host/runtime state tests.

- [ ] Add tests proving selected-run ownership, event isolation, replay suppression and absence of a second stream.
- [ ] Publish verified run selection; forward accepted SSE envelopes after sequence/run checks.
- [ ] Subscribe through a typed bridge and ignore other runs. Keep conversation pending and persistent runtime state independent of transient pet expression.
- [ ] Verify progress lookup and terminal/alert states, run switching and unmount cleanup.

## Task 3: Persona and editing semantics

Files: `adapters/chatStream.ts`, `chatStream.spec.ts`, `types.ts`, `dialogue.ts`, new persona/appearance modules, `CompanionHost.vue` and customization integration specs.

- [ ] Test model name/style context, bounded history, HTTP/stream fallback and abort propagation before implementing.
- [ ] Send existing context projection with a companion system instruction and normalized local name/lines; keep user text separate, `tool_mode: disabled`, existing `context_id` semantics.
- [ ] Capture saved appearance + skin snapshot on editor open; preview only effective state; cancel restores all fields, save commits sanitized state.
- [ ] Verify voice changes/mute consistency and switching from an existing DIY skin.

## Task 4: Host responsibility split

Files: new `features/companion/useCompanionConversation.ts`, `useCompanionAppearance.ts`, `useCompanionPosition.ts` (as warranted by ownership), runtime bridge, `CompanionHost.vue`.

- [ ] Extract conversation request/cancellation/history and appearance renderer/editor lifecycle, then position/pointer lifecycle where it reduces coupling.
- [ ] Keep Host as UI composition and explicit interaction coordination; preserve public selectors/events and disposal order.
- [ ] Re-run existing Host and integration tests after each extraction.

## Task 5: Renderer alignment and delivery

Files: `renderers.ts`, `skins.ts`, renderer/registry tests, Host CSS, current baseline documentation.

- [ ] Test required state keys, fallback chain, speaking/listening overlay, motion off and destroy during async mount.
- [ ] Apply effective palette/motion to all existing skins; provide Grok voice overlay without replacing its own eyes; honor reduced motion and cleanup.
- [ ] Update the current implementation document, record exact validation and remaining environmental limits.
- [ ] Run companion/workbench regression suites, frontend typecheck/build, and desktop companion/permission tests. Investigate new failures, distinguish baseline failures.
- [ ] Review specification compliance followed by code quality; fix findings and reverify.
- [ ] Stage explicit Companion files only and commit on `feat/companion-experience-20261115`; preserve the worktree for user review.

## Validation commands

```powershell
node node_modules/vitest/vitest.mjs run src/features/companion src/components/companion src/workbench/runtime/runtimeEvents.spec.ts src/views/MissionWorkspaceView.spec.ts --maxWorkers=2 --minWorkers=1
node node_modules/vue-tsc/bin/vue-tsc.js --noEmit -p tsconfig.json
npm run build:web
node --experimental-strip-types --test test/companion-tray.test.ts test/companion-ipc.test.ts test/permissions.test.ts
git diff --check
```

Baseline failures are explicitly authorized to be fixed by this task; unrelated shell failures are recorded separately. No deployment, merge or remote publication is included.
