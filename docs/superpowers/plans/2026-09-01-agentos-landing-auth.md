# AgentOS Landing and Auth Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a public `/` landing page using `frontend/public/bg.jpeg` and redesign `/login` login/register screens to match the supplied light sci-fi glassmorphism references without changing authenticated workbench behavior.

**Architecture:** Keep the existing Vue Router and authentication API. Add a focused `LandingView.vue`; make `App.vue` render public routes without authenticated navigation chrome; restyle `LoginView.vue` while preserving its existing form state, validation, API calls, and redirect behavior.

**Tech Stack:** Vue 3, TypeScript, Vue Router 4, Element Plus, SCSS, Vitest, Vue Test Utils, Vite.

---

### Task 1: Add red tests for public landing behavior

**Files:**
- Create: `frontend/src/views/LandingView.spec.ts`
- Modify: `frontend/src/router/index.ts` only after the red test is observed

- [ ] **Step 1: Write the failing tests**

Create a memory-router test that mounts the landing view and asserts the public CTA navigates to `/login`; add a route contract test that expects `/` to resolve to a named `Landing` route instead of `/chat`.

```ts
import { mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'
import LandingView from './LandingView.vue'

describe('LandingView', () => {
  it('sends visitors to login from the primary CTA', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', component: LandingView },
        { path: '/login', component: { template: '<div />' } }
      ]
    })
    await router.push('/')
    await router.isReady()
    const wrapper = mount(LandingView, {
      global: { plugins: [router], stubs: { 'el-icon': true } }
    })

    await wrapper.get('[data-testid="landing-cta"]').trigger('click')

    expect(router.currentRoute.value.path).toBe('/login')
  })
})
```

Add the route assertion to a small router contract test using the exported route behavior or a minimal extracted route table, without making network calls from the test.

- [ ] **Step 2: Run the focused test and verify the expected failure**

Run from `frontend`:

```powershell
npm test -- src/views/LandingView.spec.ts
```

Expected: FAIL because `LandingView.vue` and the public `/` route do not exist yet.

- [ ] **Step 3: Commit the red tests**

```powershell
git add -- frontend/src/views/LandingView.spec.ts
git commit -m "test: define public landing behavior"
```

### Task 2: Implement the public route and shell isolation

**Files:**
- Create: `frontend/src/views/LandingView.vue`
- Modify: `frontend/src/router/index.ts`
- Modify: `frontend/src/App.vue`
- Test: `frontend/src/views/LandingView.spec.ts`

- [ ] **Step 1: Add the public route**

Replace the root redirect with a named route:

```ts
{
  path: '/',
  name: 'Landing',
  component: () => import('@/views/LandingView.vue'),
  meta: { title: '首页', requiresAuth: false }
},
```

Keep `/login` public and leave every other route protected as-is.

- [ ] **Step 2: Add `LandingView.vue` with reference-aligned structure**

Implement a semantic page containing:

```vue
<main class="landing-view">
  <header class="landing-header">
    <a class="brand" href="/" aria-label="知弈 AgentOS 首页">...</a>
    <nav aria-label="主导航">...</nav>
    <span class="header-note">More Agents <i>·</i> More Possibilities</span>
  </header>
  <section id="home" class="landing-hero">...</section>
  <section id="features" class="landing-section">...</section>
  <section id="ecosystem" class="landing-section">...</section>
  <section id="about" class="landing-section">...</section>
</main>
```

Use `/bg.jpeg` as the page background, `logo.png` for the brand, Element Plus outline icons for four capability items, `data-testid="landing-cta"` on the primary button, and `router.push('/login')` for the CTA. Keep below-fold sections short and factual. Use `scroll-behavior: smooth`, visible keyboard focus states, and a reduced-motion media query.

- [ ] **Step 3: Isolate public routes from the authenticated shell**

In `App.vue`, derive:

```ts
const isPublicRoute = computed(() => route.path === '/' || route.path === '/login')
```

Use it to hide `AppTopBar`, sidebars, and `DesktopRuntimeStatus` on public routes. Add a `public-layout`/`public-main` class so the public view receives the full viewport without workbench padding or overflow constraints. Keep the existing router-view and all authenticated route logic unchanged.

- [ ] **Step 4: Run the focused tests and build**

```powershell
npm test -- src/views/LandingView.spec.ts
npm run build:web
```

Expected: the landing tests pass and the web build exits with code 0.

- [ ] **Step 5: Commit the public landing slice**

```powershell
git add -- frontend/src/views/LandingView.vue frontend/src/router/index.ts frontend/src/App.vue frontend/src/views/LandingView.spec.ts
git commit -m "feat: add public AgentOS landing page"
```

### Task 3: Add red tests for authentication presentation and interaction

**Files:**
- Create: `frontend/src/views/LoginView.spec.ts`
- Modify: `frontend/src/views/LoginView.vue` only after the red test is observed

- [ ] **Step 1: Write tests for preserved auth behavior and new presentation hooks**

Cover the following concrete behavior with Vue Test Utils:

```ts
it('renders the glass auth card with login and register tabs', () => {
  const wrapper = mount(LoginView, { global: { stubs: { 'el-tabs': ..., 'el-tab-pane': ... } } })
  expect(wrapper.find('[data-testid="auth-card"]').exists()).toBe(true)
  expect(wrapper.text()).toContain('登录')
  expect(wrapper.text()).toContain('注册')
})

it('keeps the primary register action available when the register tab is selected', async () => {
  // use the component's tab interaction, then assert the register submit button exists
  expect(wrapper.get('[data-testid="auth-submit"]').text()).toContain('注册')
})
```

Also retain/extend existing validation expectations for empty username/password and password confirmation mismatch. Mock only `authApi` at the network boundary; do not assert Element Plus internals.

- [ ] **Step 2: Run the focused auth test and verify it fails for the missing presentation hooks**

```powershell
npm test -- src/views/LoginView.spec.ts
```

Expected: FAIL because the current view has no new `auth-card`/submit test hooks and still renders the old ACG showcase layout.

- [ ] **Step 3: Commit the red auth tests**

```powershell
git add -- frontend/src/views/LoginView.spec.ts
git commit -m "test: define redesigned auth presentation"
```

### Task 4: Redesign login and registration without changing auth contracts

**Files:**
- Modify: `frontend/src/views/LoginView.vue`
- Test: `frontend/src/views/LoginView.spec.ts`

- [ ] **Step 1: Preserve the script behavior**

Keep `activeTab`, both form models, all existing `FormRules`, `handleLogin`, `handleRegister`, route redirect sanitization, localStorage keys, and `authApi.login/register` payloads. Add only presentational handlers for unsupported forgot-password and third-party buttons, using `ElMessage.info` instead of pretending those flows succeed.

- [ ] **Step 2: Replace the template with the reference-aligned layout**

Use a full-screen `.auth-view` with `/bg.jpeg`, a brand header, left-side headline/capability copy, and a right-side `<section data-testid="auth-card" class="auth-card">`. Keep the Element Plus forms and `el-tabs`, with explicit labels or visually hidden labels, Enter-to-submit, loading state, and a `data-testid="auth-submit"` hook on each primary action. Remove the ACG demo from this page so the supplied background remains the dominant visual.

- [ ] **Step 3: Replace scoped styles with responsive glassmorphism tokens**

Use semantic local variables for surface, border, primary gradient, and text colors. The card must have a translucent white surface, backdrop blur where supported, a soft shadow, 16–24px radius, 44px minimum controls, visible focus rings, and a 150–300ms transition. On narrow screens, keep the card and form usable, hide the large left marketing copy, and allow vertical scrolling. Add `@media (prefers-reduced-motion: reduce)` to disable decorative transitions.

- [ ] **Step 4: Run auth tests and fix only implementation failures**

```powershell
npm test -- src/views/LoginView.spec.ts
```

Expected: all auth presentation and validation tests pass.

- [ ] **Step 5: Commit the auth redesign**

```powershell
git add -- frontend/src/views/LoginView.vue frontend/src/views/LoginView.spec.ts
git commit -m "feat: redesign AgentOS login and registration"
```

### Task 5: Full verification and runtime smoke check

**Files:**
- Modify: none unless verification exposes a defect

- [ ] **Step 1: Run the complete frontend test suite**

```powershell
npm test
```

Expected: Vitest exits 0 with zero failed tests.

- [ ] **Step 2: Run the TypeScript/Vite production build**

```powershell
npm run build:web
```

Expected: `vue-tsc` and Vite both exit 0.

- [ ] **Step 3: Check the running Node frontend and asset responses**

With the existing frontend server running on port 8080, execute:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/ | Select-Object StatusCode
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/login | Select-Object StatusCode
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/bg.jpeg | Select-Object StatusCode, Headers
```

Expected: all responses are HTTP 200 and the background content type is an image type.

- [ ] **Step 4: Inspect the final diff and preserve unrelated changes**

```powershell
git diff --check HEAD~4..HEAD
git status --short
```

Do not stage or revert the pre-existing `compose.windows.yaml`, `frontend/public/bg.jpeg`, or supplied reference image changes unless explicitly requested.

