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

  // 退出登录：先请求服务端撤销当前会话，再清理本地凭证与登录状态。
  // 网络失败仍允许本地退出，但绝不显示服务端撤销已成功。
  async logout(): Promise<{ success: boolean; message?: string; serverRevoked: boolean }> {
    clearVerification()
    const token = localStorage.getItem('token')
    let serverRevoked = false
    let message = '退出登录成功'
    if (token) {
      try {
        await request.post('/auth/logout', undefined, { timeout: 8000 })
        serverRevoked = true
      } catch (error: any) {
        if (error?.response?.status === 401) {
          // 服务端已拒绝该凭证（过期或已被撤销）：本地清理即等效退出
          serverRevoked = true
          message = '登录凭证已失效，本机已退出'
        } else {
          // 网络失败或服务不可用：撤销结果未知，不得声称已撤销
          message = '本机已退出，服务端撤销未确认'
        }
      }
    }
    localStorage.removeItem('token')
    localStorage.removeItem('userId')
    localStorage.removeItem('userInfo')
    return { success: true, message, serverRevoked }
  }
}

