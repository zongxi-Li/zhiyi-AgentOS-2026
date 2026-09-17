import { beforeEach, describe, expect, it, vi } from 'vitest'
import request from '@/utils/request'
import { authApi } from './auth'

vi.mock('@/utils/request', () => ({ default: { get: vi.fn(), post: vi.fn() } }))

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
