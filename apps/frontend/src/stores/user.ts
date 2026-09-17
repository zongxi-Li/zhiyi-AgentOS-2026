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
  const PROFILE_TTL_MS = 30000
  let loadedIdentity = ''
  let loadedAt = 0
  let generation = 0
  let pending: { identity: string; promise: Promise<void> } | null = null
  const identity = () => `${localStorage.getItem('token') || ''}:${localStorage.getItem('userId') || ''}`

  const loadCurrentUser = async (options: { force?: boolean } = {}) => {
    const userId = localStorage.getItem('userId')
    const sessionIdentity = identity()
    if (!userId) {
      setCurrentUser(null)
      return
    }
    if (!options.force && currentUser.value && loadedIdentity === sessionIdentity && Date.now() - loadedAt < PROFILE_TTL_MS) return
    if (pending?.identity === sessionIdentity) return pending.promise
    const requestGeneration = ++generation
    if (loadedIdentity !== sessionIdentity) currentUser.value = null
    loading.value = true
    const promise = request.get<User>(`/users/${userId}`).then(response => {
      if (requestGeneration === generation && identity() === sessionIdentity) {
        currentUser.value = response.data
        loadedIdentity = sessionIdentity
        loadedAt = Date.now()
      }
    }).catch(error => {
      console.error('加载用户信息失败', error)
      if (requestGeneration === generation && identity() !== sessionIdentity) currentUser.value = null
    }).finally(() => {
      if (pending?.promise === promise) pending = null
      if (requestGeneration === generation) loading.value = false
    })
    pending = { identity: sessionIdentity, promise }
    return promise
  }

  const setCurrentUser = (user: User | null) => {
    generation += 1
    pending = null
    loading.value = false
    currentUser.value = user
    if (user) {
      localStorage.setItem('userId', user.id)
    } else {
      localStorage.removeItem('userId')
    }
    loadedIdentity = user ? identity() : ''
    loadedAt = user ? Date.now() : 0
  }

  return {
    currentUser,
    loading,
    loadCurrentUser,
    setCurrentUser
  }
})

