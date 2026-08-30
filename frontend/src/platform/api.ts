const env = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env || {}
const configuredApiOrigin = (env.VITE_API_BASE_URL || '').trim().replace(/\/$/, '')
const absoluteApiOrigin = /^https?:\/\//i.test(configuredApiOrigin) ? configuredApiOrigin : ''

const normalizePath = (path: string): string => path.startsWith('/') ? path : `/${path}`

/**
 * Resolve an API path against the configured Backend origin.
 *
 * Web builds keep relative URLs so the existing Vite/Nginx proxy contract is
 * unchanged. The desktop build sets VITE_API_BASE_URL to that same host
 * Gateway, so the API path semantics remain identical on both platforms.
 */
export const apiUrl = (path: string): string => `${absoluteApiOrigin}${normalizePath(path)}`

/** Resolve Backend health/readiness endpoints through the same /api Gateway path. */
export const backendUrl = (path: string): string => {
  const normalizedPath = normalizePath(path)
  const gatewayPath = normalizedPath === '/api' || normalizedPath.startsWith('/api/')
    ? normalizedPath
    : `/api${normalizedPath}`
  return `${absoluteApiOrigin}${gatewayPath}`
}

export const websocketUrl = (path: string): string => {
  const normalizedPath = normalizePath(path)
  if (absoluteApiOrigin) {
    const parsed = new URL(absoluteApiOrigin)
    const protocol = parsed.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${parsed.host}${normalizedPath}`
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${normalizedPath}`
}
