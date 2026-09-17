import request from '@/utils/request'

export interface LoginRequest {
  username: string
  password: string
  email?: string
}

export interface LoginResponse {
  token?: string
  userId?: string | number
  username?: string
  message?: string
  success?: boolean
}

export interface TokenVerification {
  valid: boolean
  userId?: string
  username?: string
}

const VERIFICATION_TTL_MS = 30000
let verificationCache: { token: string; result: TokenVerification; expiresAt: number } | null = null
let pendingVerification: { token: string; promise: Promise<TokenVerification> } | null = null
let verificationGeneration = 0

const clearVerification = () => {
  verificationGeneration += 1
  verificationCache = null
  pendingVerification = null
}

export const authApi = {
  // 登录
  async login(loginRequest: LoginRequest): Promise<LoginResponse & { success?: boolean }> {
    clearVerification()
    const response = await request.post<LoginResponse & { success?: boolean }>('/auth/login', loginRequest)
    return response.data
  },

  // 注册
  async register(registerRequest: LoginRequest): Promise<LoginResponse & { success?: boolean }> {
    const response = await request.post<LoginResponse & { success?: boolean }>('/auth/register', registerRequest)
    return response.data
  },

  // 验证Token
  async verifyToken(force = false): Promise<TokenVerification> {
    const token = localStorage.getItem('token')
    if (!token) {
      clearVerification()
      return { valid: false }
    }
    if (!force && verificationCache?.token === token && verificationCache.expiresAt > Date.now()) {
      return verificationCache.result
    }
    if (pendingVerification?.token === token) return pendingVerification.promise

    const generation = ++verificationGeneration
    verificationCache = null
    const promise = request.get<TokenVerification>('/auth/verify', {
      timeout: 5000,
      headers: { Authorization: `Bearer ${token}` }
    }).then(response => {
      if (generation === verificationGeneration && localStorage.getItem('token') === token && response.data.valid) {
        verificationCache = { token, result: response.data, expiresAt: Date.now() + VERIFICATION_TTL_MS }
      }
      return response.data
    }).finally(() => {
      if (pendingVerification?.promise === promise) pendingVerification = null
    })
    pendingVerification = { token, promise }
    return promise
  },

  // 退出登录
  async logout(): Promise<{ success: boolean; message?: string }> {
    clearVerification()
    try {
      // 清除本地存储的token
      localStorage.removeItem('token')
      localStorage.removeItem('userId')
      localStorage.removeItem('userInfo')
      
      // 可以调用后端接口进行token失效（如果有的话）
      // 目前后端没有logout接口，所以只在前端清除
      
      return { success: true, message: '退出登录成功' }
    } catch (error: any) {
      console.error('退出登录失败:', error)
      return { success: false, message: error.message || '退出登录失败' }
    }
  }
}

