import { beforeEach, describe, expect, it, vi } from 'vitest'
import { authApi } from '@/services/api/auth'
import router from './index'

vi.mock('@/services/api/auth', () => ({
  authApi: {
    verifyToken: vi.fn()
  }
}))

describe('public route contract', () => {
  beforeEach(async () => {
    localStorage.clear()
    vi.clearAllMocks()
    await router.push('/')
  })

  it('keeps the root route public and resolves it to the landing page', () => {
    expect(router.currentRoute.value.path).toBe('/')
    expect(router.currentRoute.value.name).toBe('Landing')
  })

  it('redirects the legacy login path to landing embedded auth', async () => {
    await router.push('/login?redirect=%2Fchat&from=%2F%23about')

    expect(router.currentRoute.value.path).toBe('/')
    expect(router.currentRoute.value.query).toMatchObject({
      auth: '1',
      redirect: '/chat',
      from: '/#about'
    })
  })

  it('opens landing embedded auth for protected routes without a token', async () => {
    await router.push('/chat?workspace=agent')

    expect(router.currentRoute.value.path).toBe('/')
    expect(router.currentRoute.value.query).toMatchObject({
      auth: '1',
      redirect: '/chat?workspace=agent'
    })
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

describe('integrated legacy route contract', () => {
  it.each([
    ['/roles', '/agentos/resources', 'roles'],
    ['/federated-learning', '/agentos/resources', 'federated'],
    ['/federated-models', '/agentos/resources', 'models'],
    ['/agentos-console', '/history', 'acg'],
  ])('keeps %s as a redirect-only route', (legacyPath, targetPath, tab) => {
    const legacyRoute = router.getRoutes().find(route => route.path === legacyPath)

    expect(legacyRoute?.component).toBeUndefined()
    expect(legacyRoute?.redirect).toBeTypeOf('function')
    expect(legacyRoute?.redirect?.({ query: {}, params: {}, path: legacyPath } as never)).toEqual({
      path: targetPath,
      query: { tab }
    })
  })

  it.each([
    ['/roles?source=legacy', '/agentos/resources', { source: 'legacy', tab: 'roles' }],
    ['/federated-learning?source=legacy', '/agentos/resources', { source: 'legacy', tab: 'federated' }],
    ['/federated-models?source=legacy', '/agentos/resources', { source: 'legacy', tab: 'models' }],
    ['/agentos-console?runId=run_1&source=legacy', '/history', { runId: 'run_1', source: 'legacy', tab: 'acg' }],
  ])('resolves %s to its integrated tab target', async (legacyUrl, targetPath, query) => {
    localStorage.setItem('token', 'token')
    vi.mocked(authApi.verifyToken).mockResolvedValue({ valid: true } as never)

    await router.push(legacyUrl)

    expect(router.currentRoute.value.path).toBe(targetPath)
    expect(router.currentRoute.value.query).toMatchObject(query)
  })
})
