# Landing Embedded Auth Design

## Goal

Clicking the landing page primary CTA switches the right-side hero animation slot into the existing embedded login/register card.

## Scope

- Keep the current landing page layout, copy, navigation, background, and visual direction.
- Replace only the hero right-side `GlassConstellation` content when auth is requested.
- Remove the top header login button from the landing page.
- Stop presenting `/login` as a standalone page; stale `/login` visits redirect to the landing page with embedded auth open.
- Keep `LoginView` as the reusable auth form component because its `embedded` mode is already implemented and tested.

## Behavior

- `探索知弈 AgentOS` opens embedded auth in the hero slot.
- The embedded card close button restores the original animation.
- Unauthenticated protected-route access redirects to `/?auth=1&redirect=<target>` so login still returns to the intended workspace page.
- Successful login/register behavior remains owned by `LoginView`.

## Tests

- Update landing tests to assert the CTA does not route away and shows embedded auth.
- Assert the header login button is gone.
- Update router tests to assert `/login` redirects to landing embedded auth and protected routes redirect there.
