# ACG Step 路线图 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 ACG 页面默认以 Step 依赖路线展示任务执行，并保留完整拓扑用于审计和排障。

**Architecture:** 在 `AcgTopologyGraph.vue` 内将图形数据投影为两种视图：默认的 Step-only dependency 路线和既有全图。路线图在前端从 Blueprint 推导拓扑层级、卡片和详情关联，不改变 API 契约或运行时存储。

**Tech Stack:** Vue 3、TypeScript、Vitest、Vue Test Utils、vis-network。

---

### Task 1: 创建可测试的 Step 路线投影

**Files:**

- Create: `frontend/src/components/agentos/acgStepRoute.ts`
- Create: `frontend/src/components/agentos/acgStepRoute.spec.ts`

- [ ] **Step 1: 写出阶段化路线的失败测试**

```ts
it('places independent successors in the same stage and their join after them', () => {
  const route = buildAcgStepRoute({
    nodes: [
      { nodeId: 'extract', nodeType: 'step' },
      { nodeId: 'classify', nodeType: 'step' },
      { nodeId: 'search', nodeType: 'step' },
      { nodeId: 'report', nodeType: 'step' }
    ],
    edges: [
      { edgeId: 'e1', sourceId: 'extract', targetId: 'classify', edgeType: 'dependency' },
      { edgeId: 'e2', sourceId: 'extract', targetId: 'search', edgeType: 'dependency' },
      { edgeId: 'e3', sourceId: 'classify', targetId: 'report', edgeType: 'dependency' },
      { edgeId: 'e4', sourceId: 'search', targetId: 'report', edgeType: 'dependency' }
    ]
  })
  expect(route.stages.map(stage => stage.stepIds)).toEqual([
    ['extract'], ['classify', 'search'], ['report']
  ])
})
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `npm run test -- src/components/agentos/acgStepRoute.spec.ts`

Expected: FAIL because `acgStepRoute.ts` does not exist.

- [ ] **Step 3: 实现最小 Step-only 拓扑投影**

```ts
export function buildAcgStepRoute(blueprint: AcgBlueprint) {
  const steps = blueprint.nodes.filter(node => node.nodeType === 'step')
  const stepIds = new Set(steps.map(step => step.nodeId))
  const edges = blueprint.edges.filter(edge =>
    edge.edgeType === 'dependency' && stepIds.has(edge.sourceId) && stepIds.has(edge.targetId)
  )
  // Assign each successor to max(predecessor stages) + 1.
}
```

- [ ] **Step 4: 重新运行测试并确认通过**

Run: `npm run test -- src/components/agentos/acgStepRoute.spec.ts`

Expected: PASS.

### Task 2: 实现默认路线及全图切换

**Files:**

- Create: `frontend/src/components/agentos/AcgStepRoute.vue`
- Create: `frontend/src/components/agentos/AcgStepRoute.spec.ts`
- Modify: `frontend/src/components/agentos/AcgTopologyGraph.vue`
- Create: `frontend/src/components/agentos/AcgTopologyGraph.spec.ts`

- [ ] **Step 1: 写出默认路线和模式切换的失败测试**

```ts
it('renders the Step route by default and exposes full graph as an auxiliary mode', async () => {
  const wrapper = mount(AcgTopologyGraph, { props: { blueprint, stepStates: [] } })
  expect(wrapper.get('[data-testid="acg-step-route"]').isVisible()).toBe(true)
  expect(wrapper.find('[data-testid="acg-full-graph"]').exists()).toBe(false)

  await wrapper.get('[data-testid="acg-view-full"]').trigger('click')
  expect(wrapper.get('[data-testid="acg-full-graph"]').isVisible()).toBe(true)
})
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `npm run test -- src/components/agentos/AcgTopologyGraph.spec.ts`

Expected: FAIL because the route view and mode controls do not exist.

- [ ] **Step 3: 实现路线卡片和视图切换**

```vue
<button data-testid="acg-view-route" :class="{ active: viewMode === 'route' }" @click="viewMode = 'route'">Step 路线</button>
<button data-testid="acg-view-full" :class="{ active: viewMode === 'full' }" @click="viewMode = 'full'">全图</button>
<AcgStepRoute v-if="viewMode === 'route'" data-testid="acg-step-route" ... />
<div v-else data-testid="acg-full-graph" class="graph-stage">...</div>
```

Keep vis-network, edge filters, and main execution chain in full-graph mode only. Route mode uses horizontal stages with CSS grid and emits the selected Step id to the existing detail panel.

- [ ] **Step 4: 写出卡片状态与详情关联的失败测试**

```ts
it('shows a running Step card and emits its id when selected', async () => {
  const wrapper = mount(AcgStepRoute, {
    props: { blueprint, stepStates: [{ stepId: 'classify', status: 'running', agentName: '分类 Agent', attempt: 1, retryCount: 0 }] }
  })
  expect(wrapper.get('[data-step-id="classify"]').text()).toContain('执行中')
  await wrapper.get('[data-step-id="classify"]').trigger('click')
  expect(wrapper.emitted('select-step')).toEqual([['classify']])
})
```

- [ ] **Step 5: 运行测试并确认失败**

Run: `npm run test -- src/components/agentos/AcgStepRoute.spec.ts`

Expected: FAIL because `AcgStepRoute.vue` does not exist.

- [ ] **Step 6: 实现卡片、状态及详情关联**

```vue
<section class="acg-step-route" aria-label="ACG Step 执行路线">
  <div v-for="stage in route.stages" :key="stage.index" class="route-stage">
    <span class="route-stage__label">阶段 {{ stage.index + 1 }}</span>
    <button v-for="step in stage.steps" :key="step.nodeId" :data-step-id="step.nodeId" @click="$emit('select-step', step.nodeId)">
      <span>{{ statusLabel(step.nodeId) }}</span>
      <strong>{{ step.name || step.nodeId }}</strong>
      <small>{{ agentLabel(step.nodeId) }}</small>
    </button>
  </div>
</section>
```

Group adjacent non-Step nodes by `nodeType` in the existing detail panel. Retain legacy fallback status behavior and responsive layout.

- [ ] **Step 7: 运行相关组件测试并确认通过**

Run: `npm run test -- src/components/agentos/acgStepRoute.spec.ts src/components/agentos/AcgStepRoute.spec.ts src/components/agentos/AcgTopologyGraph.spec.ts`

Expected: PASS.

### Task 3: 页面级回归验证

**Files:**

- Modify: `frontend/src/views/AcgVisualizationView.spec.ts` only if it lacks a default route assertion.

- [ ] **Step 1: 为默认 Step 路线写出页面级断言**

```ts
expect(wrapper.get('[data-testid="acg-step-route"]').isVisible()).toBe(true)
```

- [ ] **Step 2: 运行页面及组件测试**

Run: `npm run test -- src/components/agentos/acgStepRoute.spec.ts src/components/agentos/AcgStepRoute.spec.ts src/components/agentos/AcgTopologyGraph.spec.ts src/views/AcgVisualizationView.spec.ts`

Expected: PASS.

- [ ] **Step 3: 构建前端**

Run: `npm run build`

Expected: PASS with `vue-tsc && vite build` completed successfully.

- [ ] **Step 4: 提交已验证的改动**

```bash
git add frontend/src/components/agentos frontend/src/views/AcgVisualizationView.spec.ts
git commit -m "feat: visualize ACG execution as step route"
```
