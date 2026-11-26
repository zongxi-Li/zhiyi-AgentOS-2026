import { defineStore } from 'pinia'
import { ref } from 'vue'
import request from '@/utils/request'

export interface User {
  id: string
  username: string
  email?: string
  avatar?: string
  createdAt?: Date | string
}

export const useUserStore = defineStore('user', () => {
  const currentUser = ref<User | null>(null)
  const loading = ref(false)
  const loadError = ref('')
  let loadedAt = 0
  let generation = 0
  let pending: Promise<void> | null = null
  // 启动投影（本机启动器账号）不含头像；等后端就绪后延后补拉完整档案。
  const PROFILE_REFRESH_DELAY_MS = 4000
  const PROFILE_REFRESH_RETRY_INTERVAL_MS = 2000
  let profileRefreshTimer: number | null = null

  const loadCurrentUser = async (options: { force?: boolean; silent?: boolean } = {}) => {
    if (!options.force && currentUser.value && Date.now() - loadedAt < 30000) return
    if (pending) return pending
    const requestGeneration = ++generation
    loading.value = true
    loadError.value = ''
    const promise = request.get<User>('/user/profile', { timeout: 10000, silent: options.silent }).then(response => {
      if (requestGeneration !== generation) return
      if (!response.data?.id) throw new Error('本机身份尚未就绪')
      currentUser.value = response.data
      // Draft/cache scoping only; backend authority comes from LocalIdentity.
      localStorage.setItem('userId', response.data.id)
      loadedAt = Date.now()
    }).catch(error => {
      if (requestGeneration === generation) loadError.value = error.message || '本机身份加载失败'
      console.error('加载本机身份失败', error)
    }).finally(() => {
      if (pending === promise) pending = null
      if (requestGeneration === generation) loading.value = false
    })
    pending = promise
    return promise
  }

  // 延后补拉直到后端就绪（silent 请求失败不弹全局提示）；拿到档案后无论有无头像都停止。
  const refreshProfileUntilReady = async (attempts = 4) => {
    for (let attempt = 0; attempt < attempts; attempt++) {
      if (attempt) await new Promise(resolve => setTimeout(resolve, PROFILE_REFRESH_RETRY_INTERVAL_MS))
      await loadCurrentUser({ force: true, silent: true })
      if (!loadError.value) return
    }
  }

  const setCurrentUser = (user: User | null, options: { refreshProfile?: boolean } = {}) => {
    generation += 1
    pending = null
    loading.value = false
    currentUser.value = user
    if (user) localStorage.setItem('userId', user.id)
    loadedAt = user ? Date.now() : 0
    if (profileRefreshTimer !== null) {
      window.clearTimeout(profileRefreshTimer)
      profileRefreshTimer = null
    }
    if (user && options.refreshProfile && !user.avatar) {
      profileRefreshTimer = window.setTimeout(() => {
        profileRefreshTimer = null
        void refreshProfileUntilReady()
      }, PROFILE_REFRESH_DELAY_MS)
    }
  }

  return { currentUser, loading, loadError, loadCurrentUser, setCurrentUser }
})
