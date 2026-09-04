/**
 * API连接测试工具
 * 用于测试前后端通信是否正常
 */
import request from './request'

export interface ApiTestResult {
  success: boolean
  message: string
  status?: number
  data?: any
  timestamp: string
}

/**
 * 测试后端健康检查接口
 */
export async function testHealthCheck(): Promise<ApiTestResult> {
  try {
    const response = await request.get('/health')
    return {
      success: true,
      message: '后端连接正常',
      status: response.status,
      data: response.data,
      timestamp: new Date().toISOString()
    }
  } catch (error: any) {
    return {
      success: false,
      message: error.message || '后端连接失败',
      status: error.response?.status,
      timestamp: new Date().toISOString()
    }
  }
}

/**
 * 测试认证接口（不需要token）
 */
export async function testAuthEndpoint(): Promise<ApiTestResult> {
  try {
    // 测试一个公开的认证端点（即使失败也能知道接口存在）
    const response = await request.post('/auth/login', {
      username: 'test',
      password: 'test'
    }).catch((error: any) => {
      // 即使登录失败，只要不是网络错误就说明接口存在
      if (error.response && error.response.status === 401) {
        return { status: 401, data: { message: '认证接口正常（预期失败）' } }
      }
      throw error
    })
    
    return {
      success: true,
      message: '认证接口可访问',
      status: response.status || 401,
      data: response.data,
      timestamp: new Date().toISOString()
    }
  } catch (error: any) {
    return {
      success: false,
      message: error.message || '认证接口不可访问',
      status: error.response?.status,
      timestamp: new Date().toISOString()
    }
  }
}

/**
 * 测试需要认证的接口
 */
export async function testAuthenticatedEndpoint(): Promise<ApiTestResult> {
  const token = localStorage.getItem('token')
  if (!token) {
    return {
      success: false,
      message: '未登录，无法测试认证接口',
      timestamp: new Date().toISOString()
    }
  }

  try {
    const response = await request.get('/roles/builtin')
    return {
      success: true,
      message: '认证接口正常',
      status: response.status,
      data: response.data,
      timestamp: new Date().toISOString()
    }
  } catch (error: any) {
    return {
      success: false,
      message: error.message || '认证接口测试失败',
      status: error.response?.status,
      timestamp: new Date().toISOString()
    }
  }
}

/**
 * 完整的前后端通信测试
 */
export async function testApiConnection(): Promise<{
  health: ApiTestResult
  auth: ApiTestResult
  authenticated?: ApiTestResult
  summary: {
    allPassed: boolean
    passedCount: number
    totalCount: number
  }
}> {
  const results = {
    health: await testHealthCheck(),
    auth: await testAuthEndpoint(),
    authenticated: undefined as ApiTestResult | undefined
  }

  // 如果有token，测试认证接口
  if (localStorage.getItem('token')) {
    results.authenticated = await testAuthenticatedEndpoint()
  }

  const allResults = [results.health, results.auth, results.authenticated].filter(Boolean) as ApiTestResult[]
  const passedCount = allResults.filter(r => r.success).length
  const totalCount = allResults.length

  return {
    ...results,
    summary: {
      allPassed: passedCount === totalCount,
      passedCount,
      totalCount
    }
  }
}

