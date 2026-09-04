# Resource and History Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Integrate role, federation, and model management into Resource Center; integrate ACG history into History; remove standalone entries while preserving legacy links through redirects.

**Architecture:** Keep \`ResourceCenterView.vue\` and \`HistoryView.vue\` as the only top-level pages. Extract each standalone page's content into focused child panels, synchronize parent tabs with URL query parameters, and share one semantic HTML title banner. Keep the existing Store/API behavior and use a 1400px desktop content canvas.

**Tech Stack:** Vue 3 \`<script setup>\`, TypeScript, Vue Router 4, Element Plus, Pinia, Vitest, Vite.

---

## File map

- Create \`apps/frontend/src/components/app/WorkspacePageHero.vue\`: shared eyebrow/title/description/action banner.
- Create \`apps/frontend/src/components/resource-center/ResourceOverviewPanel.vue\`: current ResourceService list and loading/error states.
- Create \`apps/frontend/src/components/resource-center/RoleManagementPanel.vue\`: role list, selection, edit/delete, and create-role behavior.
- Create \`apps/frontend/src/components/resource-center/FederatedManagementPanel.vue\`: federation dashboard and controls.
- Create \`apps/frontend/src/components/resource-center/ModelManagementPanel.vue\`: model list, filters, details, evaluation, deployment, and creation.
- Create \`apps/frontend/src/components/history/AcgHistoryPanel.vue\`: ACG run filters, list, details, cancellation, refresh, and navigation.
- Modify \`apps/frontend/src/views/ResourceCenterView.vue\`: resource tabs, shared banner, URL sync, and wide layout.
- Modify \`apps/frontend/src/views/HistoryView.vue\`: history tabs, shared banner, URL sync, and wide layout.
- Modify \`apps/frontend/src/router/index.ts\` and \`apps/frontend/src/App.vue\`: redirects and navigation cleanup.
- Modify/create focused tests under \`apps/frontend/src/components\`, \`apps/frontend/src/views\`, and \`apps/frontend/src/router\`.
- Delete the four obsolete standalone view files only after all imports and tests are migrated.

## Task 1: Add the shared title banner

**Files:**
- Create: \`apps/frontend/src/components/app/WorkspacePageHero.vue\`
- Create: \`apps/frontend/src/components/app/WorkspacePageHero.spec.ts\`

- [ ] **Step 1: Write the failing test**

Mount the component with \`eyebrow="RESOURCE CENTER"\`, \`title="资源中心"\`, \`description="资源描述"\`, and an action slot. Assert all text, the action slot, and a semantic \`h1\` are rendered; assert no \`img\` is used for the title.

- [ ] **Step 2: Run the focused test**

~~~powershell
npm test -- src/components/app/WorkspacePageHero.spec.ts
~~~

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement the component**

Use props \`{ eyebrow: string; title: string; description?: string }\`; render the eyebrow, \`h1\`, optional description, and \`<slot name="actions" />\`. Add scoped styles for the shared horizontal banner and a mobile column layout.

- [ ] **Step 4: Verify**

~~~powershell
npm test -- src/components/app/WorkspacePageHero.spec.ts
~~~

Expected: PASS.

## Task 2: Create the Resource Center tab shell

**Files:**
- Create: \`apps/frontend/src/components/resource-center/ResourceOverviewPanel.vue\`
- Modify: \`apps/frontend/src/views/ResourceCenterView.vue\`
- Modify: \`apps/frontend/src/views/ResourceCenterView.spec.ts\`

- [ ] **Step 1: Add failing tab tests**

Test that \`/agentos/resources\` defaults to \`overview\`, renders four tab labels (\`资源概览\`, \`角色管理\`, \`联邦管理\`, \`模型管理\`), and selecting \`roles\` updates only the query to \`tab=roles\`.

- [ ] **Step 2: Verify the tests fail**

~~~powershell
npm test -- src/views/ResourceCenterView.spec.ts
~~~

Expected: FAIL because the current page has no tabs.

- [ ] **Step 3: Extract the current resource list**

Move the current Resource Center template and its \`resources\`, \`searchText\`, \`loading\`, \`errorMessage\`, filtering, date/health formatting, abort controller, API loading, and lifecycle code into \`ResourceOverviewPanel.vue\` unchanged.

- [ ] **Step 4: Implement parent tab state**

Define \`type ResourceTab = 'overview' | 'roles' | 'federated' | 'models'\`, normalize unknown query values to \`overview\`, and update tabs with:

~~~ts
const selectResourceTab = (tab: ResourceTab) => {
  void router.replace({ path: '/agentos/resources', query: tab === 'overview' ? {} : { tab } })
}
~~~

Render \`WorkspacePageHero\` once and render the overview panel for the default tab.

- [ ] **Step 5: Apply the wide desktop canvas**

Set the centered main content to \`width: min(100%, 1400px)\` with responsive horizontal padding; retain a 16px mobile override.

- [ ] **Step 6: Verify**

~~~powershell
npm test -- src/views/ResourceCenterView.spec.ts
~~~

Expected: PASS for the overview and tab URL behavior.

## Task 3: Move role, federation, and model management into Resource Center

**Files:**
- Create: \`apps/frontend/src/components/resource-center/RoleManagementPanel.vue\`
- Create: \`apps/frontend/src/components/resource-center/FederatedManagementPanel.vue\`
- Create: \`apps/frontend/src/components/resource-center/ModelManagementPanel.vue\`
- Modify: \`apps/frontend/src/views/ResourceCenterView.vue\`
- Modify: \`apps/frontend/src/views/ResourceCenterView.spec.ts\`

- [ ] **Step 1: Add failing panel tests**

Add tests for \`tab=roles\`, \`tab=federated\`, and \`tab=models\). Assert the role panel has role content and create action, the federation panel has its dashboard/demo/reset controls, and the model panel has search/filter/model action controls.

- [ ] **Step 2: Verify the tests fail**

~~~powershell
npm test -- src/views/ResourceCenterView.spec.ts
~~~

Expected: FAIL because the three panels are not mounted.

- [ ] **Step 3: Extract role management**

Move the role list, \`useRoleStore\`, \`useChatStore\`, selection, create navigation to \`/create-role\`, edit dialog, delete confirmation, role-created listener, and lifecycle hooks from \`RoleView.vue\` into \`RoleManagementPanel.vue\`. Remove only the standalone page header and outer page wrapper.

- [ ] **Step 4: Extract federation management**

Move the federation state, statistics, demo/reset actions, graph/chart components, privacy/aggregation panels, and existing API/store calls from \`FederatedLearningView.vue\` into \`FederatedManagementPanel.vue\`. Remove only the standalone ambient layer and page header.

- [ ] **Step 5: Extract model management**

Move the model state, filters, cards, details panel, evaluation/deployment handlers, creation action, and API calls from \`FederatedModelManagementView.vue\` into \`ModelManagementPanel.vue\`. Remove only the standalone page header, ambient background, and page-level width rules.

- [ ] **Step 6: Mount all three panels**

Render the corresponding component for \`resourceTab === 'roles' | 'federated' | 'models'\`; preserve real Store/API data and existing loading/error behavior without fallback data.

- [ ] **Step 7: Verify**

~~~powershell
npm test -- src/views/ResourceCenterView.spec.ts
~~~

Expected: PASS.

## Task 4: Add ACG history to History

**Files:**
- Create: \`apps/frontend/src/components/history/AcgHistoryPanel.vue\`
- Modify: \`apps/frontend/src/views/HistoryView.vue\`
- Create/modify: \`apps/frontend/src/views/HistoryView.spec.ts\`

- [ ] **Step 1: Add failing history tests**

Test that the default tab is \`conversations\`, \`tab=files\` keeps the file list, \`tab=acg\` renders ACG run filters/list content, and selecting ACG updates only \`/history?tab=acg\`.

- [ ] **Step 2: Verify the tests fail**

~~~powershell
npm test -- src/views/HistoryView.spec.ts
~~~

Expected: FAIL because the current page has no ACG tab.

- [ ] **Step 3: Extract ACG history**

Move the ACG console run filters, grouping, pagination, selection, cancellation, refresh, detail loading, export, identity health, and open ACG/Chat handlers from \`AgentOsConsoleView.vue\` into \`AcgHistoryPanel.vue\`. Preserve all existing runtime child components and API calls; remove only the standalone page shell.

- [ ] **Step 4: Implement history tab state**

Define \`type HistoryTab = 'conversations' | 'files' | 'acg'\`, normalize unknown values to \`conversations\`, and use:

~~~ts
const selectHistoryTab = (tab: HistoryTab) => {
  void router.replace({ path: '/history', query: tab === 'conversations' ? {} : { tab } })
}
~~~

Keep \`ConversationList\` and \`FileHistoryList\` on their current branches and mount \`AcgHistoryPanel\` for \`acg\`.

- [ ] **Step 5: Apply shared hero and width**

Render \`WorkspacePageHero\` once, place search/refresh/clear actions in its action slot, and set the main history content to \`width: min(100%, 1400px)\` with mobile padding overrides.

- [ ] **Step 6: Verify**

~~~powershell
npm test -- src/views/HistoryView.spec.ts
~~~

Expected: PASS.

## Task 5: Replace standalone routes with compatibility redirects

**Files:**
- Modify: \`apps/frontend/src/router/index.ts\`
- Modify: \`apps/frontend/src/router/index.spec.ts\`

- [ ] **Step 1: Add failing route assertions**

~~~ts
expect(router.resolve('/roles').fullPath).toBe('/agentos/resources?tab=roles')
expect(router.resolve('/federated-learning').fullPath).toBe('/agentos/resources?tab=federated')
expect(router.resolve('/federated-models').fullPath).toBe('/agentos/resources?tab=models')
expect(router.resolve('/agentos-console').fullPath).toBe('/history?tab=acg')
~~~

- [ ] **Step 2: Verify failure**

~~~powershell
npm test -- src/router/index.spec.ts
~~~

Expected: FAIL because the old route records still mount standalone views.

- [ ] **Step 3: Implement redirects**

Remove the four standalone view imports and replace their route components with redirects to the new parent route and query. Keep \`CreateRoleView\` and all unrelated routes unchanged.

- [ ] **Step 4: Verify**

~~~powershell
npm test -- src/router/index.spec.ts
~~~

Expected: PASS.

## Task 6: Remove standalone navigation and obsolete pages

**Files:**
- Modify: \`apps/frontend/src/App.vue\`
- Delete: \`apps/frontend/src/views/RoleView.vue\`
- Delete: \`apps/frontend/src/views/FederatedLearningView.vue\`
- Delete: \`apps/frontend/src/views/FederatedModelManagementView.vue\`
- Delete: \`apps/frontend/src/views/AgentOsConsoleView.vue\`
- Modify/delete tests that exclusively import those view roots

- [ ] **Step 1: Remove four menu entries**

Remove \`/roles\`, \`/federated-learning\`, \`/federated-models\`, and \`/agentos-console\` from both expanded and drawer sidebars. Keep only \`/agentos/resources\` and \`/history\` for these capabilities.

- [ ] **Step 2: Update active-menu and scroll mappings**

Update \`isRouteScrollable\` and \`activeMenu\` so the canonical parent paths represent the integrated sections. Do not remove the existing history refresh event or unrelated navigation behavior.

- [ ] **Step 3: Verify live imports before deletion**

~~~powershell
rg -n "RoleView|FederatedLearningView|FederatedModelManagementView|AgentOsConsoleView" apps/frontend/src
~~~

Expected: only tests or intended deletion targets remain.

- [ ] **Step 4: Delete obsolete page files and exclusive tests**

Delete the four standalone view files and tests that only mount those page roots. Retain \`CreateRoleView.vue\`, shared stores, services, child components, and the new integrated panels.

- [ ] **Step 5: Verify no stale imports**

~~~powershell
rg -n "RoleView|FederatedLearningView|FederatedModelManagementView|AgentOsConsoleView" apps/frontend/src
~~~

Expected: no output.

## Task 7: Add title, tab, and width regression coverage

**Files:**
- Modify: \`apps/frontend/src/components/app/WorkspacePageHero.spec.ts\`
- Create/modify: \`apps/frontend/src/views/ResourceCenterView.layout.spec.ts\`
- Create/modify: \`apps/frontend/src/views/HistoryView.layout.spec.ts\`

- [ ] **Step 1: Add layout assertions**

Assert that both parent views contain \`width: min(100%, 1400px)\`, the shared hero renders a semantic \`h1\`, and title content is not represented by an image.

- [ ] **Step 2: Run focused tests**

~~~powershell
npm test -- src/views/ResourceCenterView.layout.spec.ts src/views/HistoryView.layout.spec.ts src/components/app/WorkspacePageHero.spec.ts
~~~

Expected: PASS.

## Task 8: Full verification

**Files:**
- Verify: all modified frontend files

- [ ] **Step 1: Run all frontend tests**

~~~powershell
npm test
~~~

Expected: zero failed tests.

- [ ] **Step 2: Run production build**

~~~powershell
npm run build:web
~~~

Expected: \`vue-tsc\` and Vite exit with code 0.

- [ ] **Step 3: Check the diff**

~~~powershell
git diff --check
git status --short
~~~

Expected: no whitespace errors; only intended integration files and pre-existing user changes remain.

- [ ] **Step 4: Manually verify the final UI**

Confirm Resource Center has four tabs, History has three tabs, old standalone entries are absent, old URLs redirect to the correct tab, title banners are consistent semantic HTML, desktop content uses the wider canvas, and mobile content stays within the viewport.

