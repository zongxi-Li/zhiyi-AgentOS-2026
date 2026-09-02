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

describe('application route boundaries', () => {
  it('keeps the user center as an independent route instead of a settings tab', () => {
    const userRecord = router.resolve('/user').matched.at(-1)

    expect(userRecord?.redirect).toBeUndefined()
    expect(userRecord?.components?.default).toBeDefined()
  })
})
