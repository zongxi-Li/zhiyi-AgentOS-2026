import axios from 'axios'
import { apiUrl } from '@/platform'
import { attachAuthToken, handleUnauthorizedError } from '@/utils/requestAuth'

export const agentosRequest = axios.create({
  baseURL: apiUrl('/api/agentos/v2'),
  timeout: 240000
})

agentosRequest.interceptors.request.use(attachAuthToken)

agentosRequest.interceptors.response.use(
  response => response,
  (error) => {
    handleUnauthorizedError(error)
    return Promise.reject(error)
  }
)
