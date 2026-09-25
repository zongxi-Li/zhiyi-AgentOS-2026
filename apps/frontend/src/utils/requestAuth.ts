import type { AxiosError, InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import { isDesktop } from '@/platform'

const EXPIRED_SESSION_MESSAGE = '登录状态已过期，请重新登录'

const USER_NOTIFIED_FLAG = '__kinlinUserNotified'
let expiredSessionToken: string | null | undefined
let lastObservedToken: string | null | undefined

type UserNotifiedError = Error & { [USER_NOTIFIED_FLAG]?: boolean }
type AuthAwareRequestConfig =
  InternalAxiosRequestConfig & { __kinlinAuthToken?: string | null }

export const markErrorAsUserNotified = <T extends Error>(error: T): T => {
  (error as UserNotifiedError)[USER_NOTIFIED_FLAG] = true
  return error
}

export const wasErrorUserNotified = (error: unknown): boolean =>
  error instanceof Error && Boolean((error as UserNotifiedError)[USER_NOTIFIED_FLAG])

const isPublicAuthRequest = (requestUrl: string) =>
  requestUrl.includes('/auth/login') || requestUrl.includes('/auth/register')

const isAuthOperation = (requestUrl: string) =>
  isPublicAuthRequest(requestUrl) || requestUrl.includes('/auth/verify')

export const attachAuthToken = (config: InternalAxiosRequestConfig) => {
  const requestUrl = config.url || ''
  const isPublicAuthOperation = isPublicAuthRequest(requestUrl)
  const token = localStorage.getItem('token')
  if (token !== lastObservedToken) {
    if (token) expiredSessionToken = undefined
    lastObservedToken = token
  }
  const authAwareConfig = config as AuthAwareRequestConfig
  authAwareConfig.__kinlinAuthToken = token

  if (token && !isPublicAuthOperation) {
    config.headers.Authorization = `Bearer ${token}`
  } else if (isPublicAuthOperation) {
    delete config.headers.Authorization
  }

  return config
}

const redirectToLoginAfterUnauthorized = () => {
  // Tauri uses hash history because a native WebView has no server-side
  // fallback for deep links. Change only the hash so Vue Router performs the
  // transition inside the current page, onto the standalone login surface.
  if (isDesktop()) {
    const currentRoute = window.location.hash.replace(/^#/, '') || '/'
    if (!currentRoute.startsWith('/login')) {
      window.location.hash = `/login?redirect=${encodeURIComponent(currentRoute)}`
    }
    return
  }

  if (!(window.location.pathname === '/' && window.location.search.includes('auth=1'))) {
    const redirect = encodeURIComponent(window.location.pathname + window.location.search)
    window.location.href = `/?auth=1&redirect=${redirect}`
  }
}

/**
 * Applies the shared expired-session policy. Auth form and token-verification
 * requests keep their existing caller-owned 401 behavior.
 */
export const handleUnauthorizedError = (error: AxiosError): boolean => {
  if (error.response?.status !== 401) return false

  const requestUrl = error.config?.url || ''
  if (isAuthOperation(requestUrl)) return true
  if (wasErrorUserNotified(error)) return true

  const requestToken =
    (error.config as AuthAwareRequestConfig | undefined)?.__kinlinAuthToken ?? null
  const activeToken = localStorage.getItem('token')
  // A response from an earlier session must not clear credentials established
  // after that request started. This also suppresses parallel 401s after the
  // first response has cleared the expired token.
  if (requestToken !== activeToken) return true
  if (
    expiredSessionToken === requestToken ||
    (!activeToken && expiredSessionToken !== undefined)
  ) {
    return true
  }

  ElMessage.error(EXPIRED_SESSION_MESSAGE)
  markErrorAsUserNotified(error)
  expiredSessionToken = requestToken
  localStorage.removeItem('token')
  localStorage.removeItem('userId')
  lastObservedToken = null
  redirectToLoginAfterUnauthorized()
  return true
}
