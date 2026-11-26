import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import request from '@/utils/request'
import { useUserStore } from './user'

vi.mock('@/utils/request', () => ({ default: { get: vi.fn() } }))
const profile = { id: 'user-a', username: 'Alice' }

describe('current user loading', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.resetAllMocks()
  })

  it('reuses recent profile data and refreshes after an edit', async () => {
    const store = useUserStore()
    vi.mocked(request.get).mockResolvedValueOnce({ data: profile }).mockResolvedValueOnce({ data: { ...profile, username: 'Updated' } })
    await store.loadCurrentUser()
    await store.loadCurrentUser()
    expect(request.get).toHaveBeenCalledTimes(1)
    await store.loadCurrentUser({ force: true })
    expect(store.currentUser?.username).toBe('Updated')
    expect(request.get).toHaveBeenCalledTimes(2)
  })

  it('merges profile requests from the shell and page', async () => {
    let resolve!: (value: any) => void
    vi.mocked(request.get).mockReturnValue(new Promise(done => { resolve = done }))
    const store = useUserStore()
    const first = store.loadCurrentUser()
    const second = store.loadCurrentUser()
    resolve({ data: profile })
    await Promise.all([first, second])
    expect(request.get).toHaveBeenCalledTimes(1)
    expect(store.currentUser).toEqual(profile)
    expect(store.loading).toBe(false)
  })

  it('ignores a response after the displayed profile is replaced', async () => {
    let resolve!: (value: any) => void
    vi.mocked(request.get).mockReturnValue(new Promise(done => { resolve = done }))
    const store = useUserStore()
    const first = store.loadCurrentUser()
    store.setCurrentUser(null)
    resolve({ data: profile })
    await first
    expect(store.currentUser).toBeNull()
    expect(store.loading).toBe(false)
  })

  it('reads the launcher identity without a saved account id', async () => {
    vi.mocked(request.get).mockResolvedValue({ data: profile })
    const store = useUserStore()
    await store.loadCurrentUser()
    expect(request.get).toHaveBeenCalledWith('/user/profile', { timeout: 10000 })
    expect(store.currentUser).toEqual(profile)
    expect(localStorage.getItem('userId')).toBe('user-a')
    expect(localStorage.getItem('token')).toBeNull()
  })

  it('revalidates an expired profile', async () => {
    const now = vi.spyOn(Date, 'now').mockReturnValue(1000)
    try {
      const store = useUserStore()
      vi.mocked(request.get).mockResolvedValue({ data: profile })
      await store.loadCurrentUser()
      now.mockReturnValue(31001)
      await store.loadCurrentUser()
      expect(request.get).toHaveBeenCalledTimes(2)
    } finally { now.mockRestore() }
  })

  it('refreshes a launcher projection without avatar after the backend settles', async () => {
    vi.useFakeTimers()
    try {
      const store = useUserStore()
      vi.mocked(request.get)
        .mockRejectedValueOnce(new Error('backend not ready'))
        .mockResolvedValueOnce({ data: { ...profile, avatar: 'a.png' } })
      store.setCurrentUser({ id: 'user-a', username: 'Alice' }, { refreshProfile: true })
      expect(store.currentUser?.avatar).toBeUndefined()
      await vi.advanceTimersByTimeAsync(4000)
      expect(request.get).toHaveBeenCalledTimes(1)
      expect(request.get).toHaveBeenCalledWith('/user/profile', { timeout: 10000, silent: true })
      await vi.advanceTimersByTimeAsync(2000)
      expect(store.currentUser?.avatar).toBe('a.png')
      expect(request.get).toHaveBeenCalledTimes(2)
      await vi.advanceTimersByTimeAsync(6000)
      expect(request.get).toHaveBeenCalledTimes(2)
    } finally { vi.useRealTimers() }
  })

  it('does not schedule a backend refresh for a projection that already carries the avatar', async () => {
    vi.useFakeTimers()
    try {
      const store = useUserStore()
      store.setCurrentUser({ id: 'user-a', username: 'Alice', avatar: 'a.png' }, { refreshProfile: true })
      await vi.advanceTimersByTimeAsync(10000)
      expect(request.get).not.toHaveBeenCalled()
    } finally { vi.useRealTimers() }
  })
})
