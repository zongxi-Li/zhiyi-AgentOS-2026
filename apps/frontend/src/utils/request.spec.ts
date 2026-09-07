import { beforeEach, describe, expect, it, vi } from 'vitest'

const { errorMessage, isDesktop } = vi.hoisted(() => ({
  errorMessage: vi.fn(),
  isDesktop: vi.fn(() => false)
}))

vi.mock('element-plus', () => ({
  ElMessage: { error: errorMessage }
}))

vi.mock('@/platform', () => ({
  apiUrl: (path: string) => path,
  isDesktop
}))

import request, { wasErrorUserNotified } from './request'

describe('request error notifications', () => {
  beforeEach(() => {
    errorMessage.mockClear()
    isDesktop.mockReturnValue(false)
    localStorage.clear()
    window.location.hash = ''
  })

  it('marks a rejected business response after notifying the user once', async () => {
    const pending = request.request({
      url: '/agent/lawyer/chat',
      method: 'post',
      adapter: async config => ({
        data: { success: false, message: 'Python agent unavailable' },
        status: 200,
        statusText: 'OK',
        headers: {},
        config
      })
    })

    const error = await pending.catch(reason => reason)

    expect(errorMessage).toHaveBeenCalledOnce()
    expect(errorMessage).toHaveBeenCalledWith('Python agent unavailable')
    expect(wasErrorUserNotified(error)).toBe(true)
  })

  it('does not classify ordinary errors as already displayed', () => {
    expect(wasErrorUserNotified(new Error('local failure'))).toBe(false)
    expect(wasErrorUserNotified({ message: 'not an Error instance' })).toBe(false)
  })

  it('keeps an unauthorized desktop redirect inside hash history', async () => {
    isDesktop.mockReturnValue(true)
    window.location.hash = '#/roles?tab=favorites'
    localStorage.setItem('token', 'expired-token')

    const pending = request.request({
      url: '/roles/builtin',
      method: 'get',
      adapter: async config => Promise.reject({
        config,
        response: { status: 401, data: {} }
      })
    })

    await pending.catch(() => undefined)

    expect(window.location.hash).toBe('#/?auth=1&redirect=%2Froles%3Ftab%3Dfavorites')
    expect(localStorage.getItem('token')).toBeNull()
    expect(errorMessage).toHaveBeenCalledWith('登录状态已过期，请重新登录')
  })
})
