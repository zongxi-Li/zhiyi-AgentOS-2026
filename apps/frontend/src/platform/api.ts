type ViteRuntimeEnv = {
  DEV?: boolean
  MODE?: string
  VITE_API_BASE_URL?: string
}

const env = (import.meta as ImportMeta & { env?: ViteRuntimeEnv }).env || {}
const defaultDesktopApiOrigin = env.MODE === 'desktop' && !env.DEV
  ? 'http://127.0.0.1:9050'
  : ''
// Desktop hot reload always uses its local Vite proxy. In particular, do not
// inherit a shell-level VITE_API_BASE_URL left by another local service.
const configuredApiOrigin = (env.MODE === 'desktop' && env.DEV
  ? ''
  : env.VITE_API_BASE_URL || defaultDesktopApiOrigin
).trim().replace(/\/$/, '')
const absoluteApiOrigin = /^https?:\/\//i.test(configuredApiOrigin) ? configuredApiOrigin : ''

const normalizePath = (path: string): string => path.startsWith('/') ? path : `/${path}`

/**
 * Resolve an API path against the configured Backend origin.
 *
 * Web builds and the desktop hot-reload build keep relative URLs so they use
 * the active Vite proxy. Packaged desktop builds fall back to the host Gateway
 * because no Vite server is present there.
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
