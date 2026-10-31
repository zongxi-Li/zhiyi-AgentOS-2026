import { getElectronBridge } from './bridge'

/**
 * 内部发行版的免登录入口。
 *
 * 账号在首启时由启动器注册并写进 DPAPI，密码只出现在 Main 进程的环境变量里；
 * 渲染层调用一次 `session.ensure()` 换回 JWT，再照常写 localStorage。
 * Web 构建与非发行版桌面构建没有这条通道，函数直接返回 false，行为不变。
 */
let inflight: Promise<boolean> | null = null

const store = (token: string, userId?: string | number): void => {
  localStorage.setItem('token', token)
  if (userId !== undefined && userId !== null && String(userId) !== '') {
    localStorage.setItem('userId', String(userId))
  }
}

export const ensureDesktopSession = async (): Promise<boolean> => {
  if (typeof localStorage === 'undefined') return false
  if (localStorage.getItem('token')) return true

  const ensure = getElectronBridge()?.session?.ensure
  if (!ensure) return false
  if (inflight) return inflight

  inflight = (async () => {
    try {
      const session = await ensure()
      if (!session?.token) return false
      store(session.token, session.userId)
      return true
    } catch {
      // 拿不到会话时保持未登录：路由守卫会退回原有登录页行为。
      return false
    } finally {
      inflight = null
    }
  })()
  return inflight
}

/** 退出登录时清空本地会话；下次导航会重新向 Main 要一个。 */
export const clearDesktopSession = (): void => {
  localStorage.removeItem('token')
  localStorage.removeItem('userId')
}
