import { beforeEach, describe, expect, it, vi } from 'vitest'

const { errorMessage, isDesktop } = vi.hoisted(() => ({
  errorMessage: vi.fn(),
  isDesktop: vi.fn(() => true)
}))

vi.mock('element-plus', () => ({
  ElMessage: { error: errorMessage }
}))

vi.mock('@/platform', () => ({
  apiUrl: (path: string) => path,
  isDesktop
}))

import { agentosRequest } from './client'
import { wasErrorUserNotified } from '@/utils/requestAuth'

describe('AgentOS request authentication policy', () => {
  beforeEach(() => {
    errorMessage.mockClear()
    isDesktop.mockReturnValue(true)
    localStorage.clear()
    window.location.hash = ''
  })

  it('uses the shared bearer token behavior without changing the AgentOS API base path', async () => {
    localStorage.setItem('token', 'session-token')
    let authorization: unknown

    await agentosRequest.request({
      url: '/runs',
      method: 'get',
      adapter: async config => {
        authorization = config.headers.Authorization
        return {
          data: { items: [] },
          status: 200,
          statusText: 'OK',
          headers: {},
          config
        }
      }
    })

    expect(authorization).toBe('Bearer session-token')
    expect(agentosRequest.defaults.baseURL).toBe('/api/agentos/v2')
  })

  it('shares expired-session cleanup and performs one Tauri hash redirect', async () => {
    localStorage.setItem('token', 'expired-token')
    localStorage.setItem('userId', 'user_1')
    window.location.hash = '#/missions?run=1'

    const error = await agentosRequest.request({
      url: '/runs',
      method: 'get',
      adapter: async config => Promise.reject(Object.assign(new Error('unauthorized'), {
        config,
        response: { status: 401, data: {} }
      }))
    }).catch(reason => reason)

    expect(errorMessage).toHaveBeenCalledOnce()
    expect(wasErrorUserNotified(error)).toBe(true)
    expect(localStorage.getItem('token')).toBeNull()
    expect(localStorage.getItem('userId')).toBeNull()
    expect(window.location.hash).toBe('#/login?redirect=%2Fmissions%3Frun%3D1')
  })

  it('notifies once when parallel requests return 401 for the cleared token', async () => {
    localStorage.setItem('token', 'expired-token')
    localStorage.setItem('userId', 'user_1')

    await Promise.all(['/runs/1', '/runs/2'].map(url => agentosRequest.request({
      url,
      method: 'get',
      adapter: async config => Promise.reject(Object.assign(new Error('unauthorized'), {
        config,
        response: { status: 401, data: {} }
      }))
    }).catch(() => undefined)))

    await agentosRequest.request({
      url: '/runs/after-expiry',
      method: 'get',
      adapter: async config => Promise.reject(Object.assign(new Error('unauthorized'), {
        config,
        response: { status: 401, data: {} }
      }))
    }).catch(() => undefined)

    expect(errorMessage).toHaveBeenCalledOnce()
    expect(localStorage.getItem('token')).toBeNull()
    expect(localStorage.getItem('userId')).toBeNull()
  })

  it('does not clear a new session when an older request returns 401', async () => {
    localStorage.setItem('token', 'old-token')
    localStorage.setItem('userId', 'old-user')
    window.location.hash = '#/missions'

    let rejectRequest!: (reason: unknown) => void
    let requestConfig: unknown
    let markAdapterStarted!: () => void
    const adapterStarted = new Promise<void>(resolve => { markAdapterStarted = resolve })
    const pending = agentosRequest.request({
      url: '/runs',
      method: 'get',
      adapter: config => new Promise((_resolve, reject) => {
        requestConfig = config
        rejectRequest = reject
        markAdapterStarted()
      })
    }).catch(() => undefined)

    await adapterStarted
    localStorage.setItem('token', 'new-token')
    localStorage.setItem('userId', 'new-user')
    rejectRequest(Object.assign(new Error('unauthorized'), {
      config: requestConfig,
      response: { status: 401, data: {} }
    }))
    await pending

    expect(errorMessage).not.toHaveBeenCalled()
    expect(localStorage.getItem('token')).toBe('new-token')
    expect(localStorage.getItem('userId')).toBe('new-user')
    expect(window.location.hash).toBe('#/missions')
  })

  it('leaves 403 errors to the AgentOS caller for contextual handling', async () => {
    localStorage.setItem('token', 'valid-token')
    localStorage.setItem('userId', 'user_1')
    window.location.hash = '#/missions'

    const error = await agentosRequest.request({
      url: '/runs',
      method: 'get',
      adapter: async config => Promise.reject({
        config,
        response: { status: 403, data: { message: 'mission access denied' } }
      })
    }).catch(reason => reason)

    expect(error.response.status).toBe(403)
    expect(errorMessage).not.toHaveBeenCalled()
    expect(localStorage.getItem('token')).toBe('valid-token')
    expect(localStorage.getItem('userId')).toBe('user_1')
    expect(window.location.hash).toBe('#/missions')
  })
})
