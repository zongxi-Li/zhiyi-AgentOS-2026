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
    localStorage.setItem('token', 'session-a')
    localStorage.setItem('userId', 'user-a')
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

  it('does not restore profile data after logout', async () => {
    let resolve!: (value: any) => void
    vi.mocked(request.get).mockReturnValue(new Promise(done => { resolve = done }))
    const store = useUserStore()
    const first = store.loadCurrentUser()
    store.setCurrentUser(null)
    localStorage.removeItem('token')
    resolve({ data: profile })
    await first
    expect(store.currentUser).toBeNull()
    expect(store.loading).toBe(false)
  })

  it('discards late responses from another account', async () => {
    let resolve!: (value: any) => void
    vi.mocked(request.get).mockReturnValueOnce(new Promise(done => { resolve = done })).mockResolvedValueOnce({ data: { id: 'user-b', username: 'Bob' } })
    const store = useUserStore()
    const first = store.loadCurrentUser()
    localStorage.setItem('token', 'session-b')
    localStorage.setItem('userId', 'user-b')
    await store.loadCurrentUser()
    resolve({ data: profile })
    await first
    expect(store.currentUser?.id).toBe('user-b')
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
})
