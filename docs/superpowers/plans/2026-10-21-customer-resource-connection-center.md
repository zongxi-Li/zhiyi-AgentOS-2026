# Customer Resource Connection Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a customer-facing resource and connection center where customers can understand, connect, and manage their own device, model, and tool resources across local, edge, and cloud deployments.

**Architecture:** Keep ResourcePlane and the existing AgentOS resource APIs as the single source of truth. Add small, presentation-only frontend helpers for customer terminology and status explanations; recompose the existing overview, registration dialog, and detail panel around those helpers without duplicating health, capacity, authorization, or scheduling decisions in the browser.

**Tech Stack:** Vue 3 Composition API, TypeScript, Element Plus, Vitest, existing `agentosApi` runtime resource client.

---

## File Structure

- Create: `apps/frontend/src/components/resource-center/resourceCenterPresentation.ts` - maps ResourcePlane catalog values to customer labels, filter values, and actionable connection guidance.
- Create: `apps/frontend/src/components/resource-center/resourceCenterPresentation.spec.ts` - unit tests for customer-facing mapping behavior.
- Create: `apps/frontend/src/components/resource-center/ResourceTopologyPanel.vue` - three deployment columns and concise connection-problem state.
- Modify: `apps/frontend/src/components/resource-center/ResourceOverviewPanel.vue` - consume presentation helper, expose customer metrics/filters, and render the topology panel while retaining API loading and detail opening.
- Modify: `apps/frontend/src/components/resource-center/ResourceRegistrationDialog.vue` - replace internal registration vocabulary with customer device/model/tool onboarding paths while producing existing Node/Runtime payloads.
- Modify: `apps/frontend/src/components/resource-center/ResourceDetailPanel.vue` - make operational summary primary and group low-level operations under advanced settings.
- Modify: `apps/frontend/src/views/ResourceCenterView.vue` - update the page title, copy, and primary actions without changing routes.
- Modify: `apps/frontend/src/views/ResourceCenterView.spec.ts` - preserve route compatibility and assert customer-facing labels/actions.
- Modify: `apps/frontend/src/components/resource-center/ResourcePlaneAdaptation.spec.ts` - cover the three registration paths and retained ResourcePlane payload invariants.

### Task 1: Customer presentation mapping

**Files:**
- Create: `apps/frontend/src/components/resource-center/resourceCenterPresentation.ts`
- Create: `apps/frontend/src/components/resource-center/resourceCenterPresentation.spec.ts`

- [ ] **Step 1: Write failing presentation tests**

```ts
import { describe, expect, it } from 'vitest'
import { connectionGuidance, customerResourceType, deploymentGroup } from './resourceCenterPresentation'

describe('resource center presentation', () => {
  it('maps runtime catalog categories to customer resource names', () => {
    expect(customerResourceType('model_server')).toBe('模型')
    expect(customerResourceType('tool_service')).toBe('工具')
    expect(customerResourceType('execution_backend')).toBe('设备服务')
  })

  it('groups local, edge, and cloud deployments into customer topology columns', () => {
    expect(deploymentGroup('local')).toEqual({ id: 'device', label: '我的设备' })
    expect(deploymentGroup('edge')).toEqual({ id: 'edge', label: '边缘节点' })
    expect(deploymentGroup('cloud')).toEqual({ id: 'cloud', label: '云端服务' })
  })

  it('explains an offline resource with a direct next action', () => {
    expect(connectionGuidance('offline')).toEqual({ tone: 'danger', action: '检测连接' })
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npm run test -- resourceCenterPresentation.spec.ts`

Expected: FAIL because `resourceCenterPresentation` does not exist.

- [ ] **Step 3: Implement the minimal pure mapping helper**

```ts
import type { RuntimeDeploymentTier, RuntimeResourceHealth, RuntimeResourceType } from '@/services/api/agentos'

export type CustomerDeploymentGroup = { id: 'device' | 'edge' | 'cloud'; label: string }

export const deploymentGroup = (tier: RuntimeDeploymentTier | null | undefined): CustomerDeploymentGroup => {
  if (tier === 'edge' || tier === 'terminal') return { id: 'edge', label: '边缘节点' }
  if (tier === 'cloud') return { id: 'cloud', label: '云端服务' }
  return { id: 'device', label: '我的设备' }
}

export const customerResourceType = (kind: RuntimeResourceType | string | null | undefined): string => ({
  model_server: '模型', model_endpoint: '模型', tool_service: '工具', execution_backend: '设备服务'
}[kind || ''] || '资源')

export const connectionGuidance = (health: RuntimeResourceHealth | string | null | undefined) => {
  if (health === 'offline') return { tone: 'danger', action: '检测连接' }
  if (health === 'degraded') return { tone: 'warning', action: '查看状态' }
  if (health === 'unknown') return { tone: 'neutral', action: '检测连接' }
  return { tone: 'success', action: '查看详情' }
}
```

- [ ] **Step 4: Run the presentation tests**

Run: `npm run test -- resourceCenterPresentation.spec.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps/frontend/src/components/resource-center/resourceCenterPresentation.ts apps/frontend/src/components/resource-center/resourceCenterPresentation.spec.ts
git commit -m "feat(resources): add customer presentation mapping"
```

### Task 2: End-edge-cloud topology and connection attention

**Files:**
- Create: `apps/frontend/src/components/resource-center/ResourceTopologyPanel.vue`
- Modify: `apps/frontend/src/components/resource-center/ResourceOverviewPanel.vue`

- [ ] **Step 1: Write a failing component test for deployment grouping and connection attention**

Add a test in `ResourcePlaneAdaptation.spec.ts` that mounts the overview with a local online runtime, an edge offline runtime, and a cloud online runtime, then asserts:

```ts
expect(wrapper.text()).toContain('我的设备')
expect(wrapper.text()).toContain('边缘节点')
expect(wrapper.text()).toContain('云端服务')
expect(wrapper.text()).toContain('检测连接')
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm run test -- ResourcePlaneAdaptation.spec.ts`

Expected: FAIL because the topology and attention state are absent.

- [ ] **Step 3: Implement `ResourceTopologyPanel.vue`**

Create a focused props-only component with `items: RuntimeResourceItem[]`, `loading: boolean`, and `onOpen(item)` emit. Group rows using `deploymentGroup()`. Render three stable columns titled `我的设备`, `边缘节点`, `云端服务`; each card must show display name, customer type, health, data zone, capacity, and open-detail button. Derive offline/degraded/unknown attention rows with `connectionGuidance()` and emit `open` instead of making API calls.

- [ ] **Step 4: Integrate it into `ResourceOverviewPanel.vue`**

After the summary and before the full catalog, render:

```vue
<ResourceTopologyPanel
  :items="filteredResources"
  :loading="loading"
  @open="openDetail"
/>
```

Replace internal headings such as `运行时资源目录` and `承载节点` with `我的资源` and `已连接设备`; retain `loadResources`, abort handling, resource detail drawer, and API calls exactly as they are.

- [ ] **Step 5: Run the focused tests**

Run: `npm run test -- ResourcePlaneAdaptation.spec.ts`

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add apps/frontend/src/components/resource-center/ResourceTopologyPanel.vue apps/frontend/src/components/resource-center/ResourceOverviewPanel.vue apps/frontend/src/components/resource-center/ResourcePlaneAdaptation.spec.ts
git commit -m "feat(resources): add customer topology overview"
```

### Task 3: Customer resource filters and page framing

**Files:**
- Modify: `apps/frontend/src/views/ResourceCenterView.vue`
- Modify: `apps/frontend/src/views/ResourceCenterView.spec.ts`
- Modify: `apps/frontend/src/components/resource-center/ResourceOverviewPanel.vue`

- [ ] **Step 1: Write failing view tests**

Add assertions that the default route renders `资源与连接中心`, primary action `接入资源`, and preserves `?tab=models`:

```ts
expect(wrapper.text()).toContain('资源与连接中心')
expect(wrapper.text()).toContain('接入资源')
await testRouter.push('/agentos/resources?tab=models')
expect(testRouter.currentRoute.value.query.tab).toBe('models')
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm run test -- ResourceCenterView.spec.ts`

Expected: FAIL because current customer-facing labels are not present.

- [ ] **Step 3: Implement customer page framing and filters**

Change the hero in `ResourceCenterView.vue` to:

```vue
<WorkspacePageHero
  eyebrow="RESOURCE & CONNECTIONS"
  title="资源与连接中心"
  description="连接并管理您的设备、模型和工具；任务会在符合数据与能力要求的位置运行。"
>
```

Rename `注册资源` to `接入资源`; keep refresh, `overview`, `models`, and query behavior unchanged. In the overview, add type, deployment, health, and data-zone filter controls that only filter the returned catalog locally; do not synthesize scheduling eligibility.

- [ ] **Step 4: Run the view tests**

Run: `npm run test -- ResourceCenterView.spec.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps/frontend/src/views/ResourceCenterView.vue apps/frontend/src/views/ResourceCenterView.spec.ts apps/frontend/src/components/resource-center/ResourceOverviewPanel.vue
git commit -m "feat(resources): frame customer resource center"
```

### Task 4: Device, model, and tool onboarding

**Files:**
- Modify: `apps/frontend/src/components/resource-center/ResourceRegistrationDialog.vue`
- Modify: `apps/frontend/src/components/resource-center/ResourcePlaneAdaptation.spec.ts`

- [ ] **Step 1: Write failing onboarding payload tests**

Use the existing API mocks to test the three customer paths:

```ts
it('registers a customer device as a Node payload', async () => {
  // select "接入设备", fill node id and owner scope, submit
  expect(registerNode).toHaveBeenCalledWith(expect.objectContaining({ profile: expect.objectContaining({ nodeId: 'node:lab', placement: 'edge' }) }))
})

it('registers a model as a model_server runtime payload', async () => {
  // select "接入模型", select node, fill capabilities/address, submit
  expect(registerResource).toHaveBeenCalledWith(expect.objectContaining({ profile: expect.objectContaining({ kind: 'model_server' }) }))
})

it('registers a tool as a tool_service runtime payload', async () => {
  // select "接入工具", select node, fill capabilities/address, submit
  expect(registerResource).toHaveBeenCalledWith(expect.objectContaining({ profile: expect.objectContaining({ kind: 'tool_service' }) }))
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm run test -- ResourcePlaneAdaptation.spec.ts`

Expected: FAIL because customer onboarding labels and selections do not exist.

- [ ] **Step 3: Recompose the dialog without changing payload contracts**

Replace four internal choices with three customer choices:

```ts
const registrationTypes = [
  { value: 'device', label: '接入设备', description: '本地或边缘设备，用于承载任务' },
  { value: 'model', label: '接入模型', description: '连接自有模型服务或登记云端模型' },
  { value: 'tool', label: '接入工具', description: '连接 HTTP 或 MCP 工具服务' }
] as const
```

Map `device` to the existing `registerNode()` path. Map `model` to `kind: 'model_server'` and `tool` to `kind: 'tool_service'`; do not add a new endpoint. After registration, keep the one-time credential view and add an explicit `下一步：在设备上完成连接后，返回此页检测连接。` message. Preserve current validation, node loading, one-time secret behavior, and error handling.

- [ ] **Step 4: Run onboarding tests**

Run: `npm run test -- ResourcePlaneAdaptation.spec.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps/frontend/src/components/resource-center/ResourceRegistrationDialog.vue apps/frontend/src/components/resource-center/ResourcePlaneAdaptation.spec.ts
git commit -m "feat(resources): add customer onboarding paths"
```

### Task 5: Customer-first resource detail and safe management actions

**Files:**
- Modify: `apps/frontend/src/components/resource-center/ResourceDetailPanel.vue`
- Modify: `apps/frontend/src/components/resource-center/ResourcePlaneAdaptation.spec.ts`

- [ ] **Step 1: Write failing detail tests**

Add a test that mounts a runtime detail panel and asserts:

```ts
expect(wrapper.text()).toContain('资源概览')
expect(wrapper.text()).toContain('高级设置')
expect(wrapper.text()).toContain('停止后不会删除资源或历史记录')
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npm run test -- ResourcePlaneAdaptation.spec.ts`

Expected: FAIL because the current panel exposes internal facts without customer grouping.

- [ ] **Step 3: Reorganize `ResourceDetailPanel.vue`**

Keep existing API calls and action handlers. Make the first section `资源概览` with deployment location, data zone, privacy, health, capacity, observed time, capabilities, and recent task usage. Add a collapsed `高级设置` section containing health history, labels, cost metadata, probe, enable/disable, and credential rotation. Update the disable confirmation to include:

```ts
'停止后，新的任务不会再使用此资源；资源配置和历史记录会保留。继续？'
```

Do not render raw endpoint secrets, Redis information, lease versions, or score weights.

- [ ] **Step 4: Run the focused test suite**

Run: `npm run test -- ResourcePlaneAdaptation.spec.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add apps/frontend/src/components/resource-center/ResourceDetailPanel.vue apps/frontend/src/components/resource-center/ResourcePlaneAdaptation.spec.ts
git commit -m "feat(resources): organize customer resource details"
```

### Task 6: Final frontend verification and manual workflow

**Files:**
- Modify only if verification exposes a defect in the files above.

- [ ] **Step 1: Run affected frontend tests**

Run: `npm run test -- ResourceCenterView.spec.ts ResourcePlaneAdaptation.spec.ts resourceCenterPresentation.spec.ts`

Expected: PASS with no test failure.

- [ ] **Step 2: Run lint and build**

Run: `npm run lint && npm run build`

Expected: both commands exit 0.

- [ ] **Step 3: Manually verify in the running application**

Open `http://127.0.0.1:8080/agentos/resources` and verify:

1. Desktop and mobile widths keep topology labels, resource cards, and action buttons readable with no overlap.
2. `接入资源` exposes device, model, and tool paths; each validates required fields before calling an API.
3. An unavailable resource offers `检测连接` through the detail panel.
4. Disable confirmation makes its non-destructive behavior explicit.
5. `/agentos/resources?tab=models` remains reachable.

- [ ] **Step 4: Commit any verification-only fixes**

```powershell
git add apps/frontend/src
git commit -m "fix(resources): resolve customer center verification findings"
```

## Self-review

- Spec coverage: Tasks 1-5 implement customer terminology, topology, catalog management, three onboarding paths, safe detail actions, owner/API boundaries, and error-preserving UI. Task 6 verifies responsiveness and route compatibility.
- No new backend API, database, config, or migration is introduced. Existing ResourcePlane remains authoritative for health, capacity, binding, and authorization.
- The plan contains no placeholders. Names in tests and implementations use the same `deploymentGroup`, `customerResourceType`, and `connectionGuidance` helper interfaces.
