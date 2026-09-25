import axios from 'axios'
import { apiUrl } from '@/platform'

export const agentosRequest = axios.create({
  baseURL: apiUrl('/api/agentos/v2'),
  timeout: 240000,
  headers: {
    'Content-Type': 'application/json'
  }
})

agentosRequest.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})
