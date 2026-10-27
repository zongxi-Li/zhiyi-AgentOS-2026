import { beforeEach, describe, expect, it, vi } from 'vitest'
import request from '@/utils/request'
import { authApi } from './auth'

vi.mock('@/utils/request', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

describe('logout with server-side revocation', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.resetAllMocks()
  })

  it('revokes the session on the server and clears local credentials', async () => {
    localStorage.setItem('token', 'session-a')
    localStorage.setItem('userId', 'u1')
    localStorage.setItem('userInfo', '{}')
    vi.mocked(request.post).mockResolvedValue({ status: 204 })

    const result = await authApi.logout()

    expect(request.post).toHaveBeenCalledWith(
      '/auth/logout',
      undefined,
      expect.objectContaining({ timeout: 8000 })
    )
    expect(result).toEqual({ success: true, message: '退出登录成功', serverRevoked: true })
    expect(localStorage.getItem('token')).toBeNull()
    expect(localStorage.getItem('userId')).toBeNull()
    expect(localStorage.getItem('userInfo')).toBeNull()
  })

  it('still logs out locally on network failure but never claims the server revoked the session', async () => {
    localStorage.setItem('token', 'session-a')
    vi.mocked(request.post).mockRejectedValue(new Error('Network Error'))

    const result = await authApi.logout()

    expect(result.success).toBe(true)
    expect(result.serverRevoked).toBe(false)
    expect(result.message).toBe('本机已退出，服务端撤销未确认')
    expect(localStorage.getItem('token')).toBeNull()
  })

  it('treats a 401 during logout as an already-invalid credential and finishes locally', async () => {
    localStorage.setItem('token', 'session-a')
    vi.mocked(request.post).mockRejectedValue({ response: { status: 401 } })

    const result = await authApi.logout()

    expect(result.serverRevoked).toBe(true)
    expect(result.message).toBe('登录凭证已失效，本机已退出')
    expect(localStorage.getItem('token')).toBeNull()
  })

  it('skips the server call when there is no local token', async () => {
    const result = await authApi.logout()

    expect(request.post).not.toHaveBeenCalled()
    expect(result.success).toBe(true)
    expect(result.serverRevoked).toBe(false)
  })

  it('broadcasts the logout so live stream clients stop immediately', async () => {
    localStorage.setItem('token', 'session-a')
    vi.mocked(request.post).mockResolvedValue({ status: 204 })
    const listener = vi.fn()
    window.addEventListener('kinlin:auth-logout', listener)

    try {
      await authApi.logout()
      expect(listener).toHaveBeenCalledTimes(1)
    } finally {
      window.removeEventListener('kinlin:auth-logout', listener)
    }
  })

  it('clears the verification cache so a stale token cannot be verified after logout', async () => {
    localStorage.setItem('token', 'session-a')
    vi.mocked(request.post).mockResolvedValue({ status: 204 })
    vi.mocked(request.get).mockResolvedValue({ data: { valid: true } })
    await authApi.verifyToken()

    await authApi.logout()
    localStorage.setItem('token', 'session-a')

    await authApi.verifyToken()
    expect(request.get).toHaveBeenCalledTimes(2)
  })
})

describe('token verification', () => {
  beforeEach(async () => {
    localStorage.clear()
    await authApi.logout()
    vi.resetAllMocks()
    localStorage.setItem('token', 'session-a')
  })

  it('reuses a successful verification during navigation', async () => {
    vi.mocked(request.get).mockResolvedValue({ data: { valid: true } })
    await authApi.verifyToken()
    await authApi.verifyToken()
    expect(request.get).toHaveBeenCalledTimes(1)
    expect(request.get).toHaveBeenCalledWith('/auth/verify', expect.objectContaining({ timeout: 5000 }))
  })

  it('merges concurrent verification requests', async () => {
    let resolve!: (value: any) => void
    vi.mocked(request.get).mockReturnValue(new Promise(done => { resolve = done }))
    const first = authApi.verifyToken()
    const second = authApi.verifyToken()
    resolve({ data: { valid: true } })
    expect(await Promise.all([first, second])).toEqual([{ valid: true }, { valid: true }])
    expect(request.get).toHaveBeenCalledTimes(1)
  })

  it('revalidates when the cache expires', async () => {
    const now = vi.spyOn(Date, 'now').mockReturnValue(1000)
    try {
      vi.mocked(request.get).mockResolvedValue({ data: { valid: true } })
      await authApi.verifyToken()
      now.mockReturnValue(31001)
      await authApi.verifyToken()
      expect(request.get).toHaveBeenCalledTimes(2)
    } finally { now.mockRestore() }
  })

  it('revalidates when the token changes or refresh is forced', async () => {
    vi.mocked(request.get).mockResolvedValue({ data: { valid: true } })
    await authApi.verifyToken()
    await authApi.verifyToken(true)
    localStorage.setItem('token', 'session-b')
    await authApi.verifyToken()
    expect(request.get).toHaveBeenCalledTimes(3)
  })

  it('propagates outages and retries instead of treating them as invalid tokens', async () => {
    vi.mocked(request.get).mockRejectedValueOnce(new Error('Network Error')).mockResolvedValueOnce({ data: { valid: true } })
    await expect(authApi.verifyToken()).rejects.toThrow('Network Error')
    expect(localStorage.getItem('token')).toBe('session-a')
    expect(await authApi.verifyToken()).toEqual({ valid: true })
    expect(request.get).toHaveBeenCalledTimes(2)
  })

  it('propagates unauthorized responses and does not cache invalid results', async () => {
    vi.mocked(request.get).mockRejectedValueOnce({ response: { status: 401 } }).mockResolvedValue({ data: { valid: false } })
    await expect(authApi.verifyToken()).rejects.toMatchObject({ response: { status: 401 } })
    expect(await authApi.verifyToken()).toEqual({ valid: false })
    await authApi.verifyToken()
    expect(request.get).toHaveBeenCalledTimes(3)
  })

  it('does not restore cached verification after logout while a request is pending', async () => {
    let resolve!: (value: any) => void
    vi.mocked(request.get).mockReturnValueOnce(new Promise(done => { resolve = done }))
    const first = authApi.verifyToken()
    await authApi.logout()
    resolve({ data: { valid: true } })
    await first
    localStorage.setItem('token', 'session-a')
    vi.mocked(request.get).mockResolvedValueOnce({ data: { valid: true } })
    await authApi.verifyToken()
    expect(request.get).toHaveBeenCalledTimes(2)
  })
})
