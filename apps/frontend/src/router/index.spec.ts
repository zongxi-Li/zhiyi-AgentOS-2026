import { beforeEach, describe, expect, it } from 'vitest'
import router from './index'

describe('public route contract', () => {
  beforeEach(async () => {
    localStorage.clear()
    await router.push('/')
  })

  it('keeps the root route public and resolves it to the landing page', () => {
    expect(router.currentRoute.value.path).toBe('/')
    expect(router.currentRoute.value.name).toBe('Landing')
  })
})

describe('user center route contract', () => {
  it('renders the user center instead of redirecting to settings', () => {
    const userRoute = router.getRoutes().find(route => route.name === 'User')

    expect(userRoute?.path).toBe('/user')
    expect(userRoute?.redirect).toBeUndefined()
    expect(userRoute?.components?.default).toBeDefined()
  })
})
