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

  const loadCurrentUser = async () => {
    loading.value = true
    try {
      const userId = localStorage.getItem('userId')
      if (userId) {
        const response = await request.get(`/users/${userId}`)
        currentUser.value = response.data
      }
    } catch (error) {
      console.error('加载用户信息失败', error)
      currentUser.value = null
    } finally {
      loading.value = false
    }
  }

  const setCurrentUser = (user: User | null) => {
    currentUser.value = user
    if (user) {
      localStorage.setItem('userId', user.id)
    } else {
      localStorage.removeItem('userId')
    }
  }

  return {
    currentUser,
    loading,
    loadCurrentUser,
    setCurrentUser
  }
})

