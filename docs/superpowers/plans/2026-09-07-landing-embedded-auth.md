# Landing Embedded Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make landing auth happen inside the hero right-side slot instead of navigating to a standalone login page.

**Architecture:** Reuse `LoginView` in `embedded` mode inside `LandingView`. Keep route-level compatibility by redirecting `/login` and unauthenticated protected routes to `/?auth=1&redirect=...`.

**Tech Stack:** Vue 3, Vue Router 4, Vitest, Element Plus stubs in component tests.

---

### Task 1: Landing View Behavior

**Files:**
- Modify: `apps/frontend/src/views/LandingView.spec.ts`
- Modify: `apps/frontend/src/views/LandingView.vue`

- [ ] **Step 1: Write the failing tests**

Update the primary CTA test to click `[data-testid="landing-cta"]`, expect the current route to stay `/`, expect `[data-testid="embedded-auth"]` to exist, and expect `[data-testid="glass-constellation"]` to be absent while auth is open. Add an assertion that `.landing-header__login` does not exist.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- src/views/LandingView.spec.ts`

Expected: FAIL because the CTA still routes to `/login`.

- [ ] **Step 3: Implement minimal landing change**

Import `LoginView`, add an `authOpen` state, render `<LoginView v-if="authOpen" embedded @back="closeAuth" />` in `.landing-agent-slot`, render `<GlassConstellation v-else />`, remove the header login button, and make `goToLogin` open auth in place.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- src/views/LandingView.spec.ts`

Expected: PASS.

### Task 2: Router Compatibility

**Files:**
- Modify: `apps/frontend/src/router/index.spec.ts`
- Modify: `apps/frontend/src/router/index.ts`

- [ ] **Step 1: Write the failing tests**

Update router expectations so `/login` redirects to `/?auth=1`, and unauthenticated protected routes redirect to the landing route with `auth=1` and a safe `redirect` query.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- src/router/index.spec.ts`

Expected: FAIL because `/login` still mounts `LoginView`.

- [ ] **Step 3: Implement minimal router change**

Remove the `LoginView` route component import, change `/login` to redirect to `{ path: '/', query: { auth: '1', redirect, from } }`, and change protected-route unauthenticated redirects to the same embedded auth target.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test -- src/router/index.spec.ts`

Expected: PASS.

### Task 3: Verification

**Files:**
- Read: `apps/frontend/package.json`

- [ ] **Step 1: Run focused tests**

Run: `npm test -- src/views/LandingView.spec.ts src/router/index.spec.ts`

Expected: PASS.

- [ ] **Step 2: Run frontend build**

Run: `npm run build:web`

Expected: PASS.
