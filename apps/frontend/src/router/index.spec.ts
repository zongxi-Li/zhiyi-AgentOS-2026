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
