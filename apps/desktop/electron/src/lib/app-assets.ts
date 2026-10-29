import * as path from 'node:path'

/**
 * 自定义协议资产解析的纯逻辑：不 import electron，可被 node --test 单测。
 * 生产环境页面经 kinlin-app://shell/<path> 加载，落盘目录是 asar 内的
 * renderer/；这里的解析器负责把 URL 路径安全映射到文件系统路径。
 */

/** URL pathname → 相对路径；解码失败或包含非法成分返回 null。 */
export function decodeAppPath(pathname: string): string | null {
  let decoded: string
  try {
    decoded = decodeURIComponent(pathname)
  } catch {
    return null
  }
  if (decoded.includes('\0')) return null
  // 反斜杠统一按路径分隔符处理，杜绝 Windows 盘符与 ..\ 穿越变体。
  const normalized = decoded.replace(/\\/g, '/')
  if (normalized.includes('..')) return null
  return normalized.replace(/^\/+/, '')
}

export interface PathModule {
  join(...segments: string[]): string
  normalize(p: string): string
  sep: string
}

/**
 * 相对路径 → rootDir 内的绝对路径；越界（目录穿越、绝对路径）返回 null。
 * 允许注入 path 实现（posix/win32）以便测试两种分隔符语义。
 */
export function resolveAppPath(rootDir: string, relativePath: string, pathModule: PathModule = path): string | null {
  if (relativePath === '') return pathModule.normalize(rootDir)
  if (/^[a-zA-Z]:/.test(relativePath)) return null
  const resolved = pathModule.normalize(pathModule.join(rootDir, relativePath))
  const root = pathModule.normalize(rootDir)
  if (resolved !== root && !resolved.startsWith(root + pathModule.sep)) return null
  return resolved
}

const CONTENT_TYPES: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.webp': 'image/webp',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.map': 'application/json; charset=utf-8',
  '.txt': 'text/plain; charset=utf-8',
  '.webmanifest': 'application/manifest+json'
}

export function contentTypeFor(filePath: string): string {
  const ext = path.extname(filePath).toLowerCase()
  return CONTENT_TYPES[ext] ?? 'application/octet-stream'
}

/**
 * 生产 CSP：比 Tauri 版更紧——script-src 不含 'unsafe-eval'，
 * 桌面产物无 HMR 需求。connect 显式放行宿主 Gateway 的 HTTP/WS 与
 * 上层 HTTPS/WSS；origin 由 Main 启动参数注入（默认 9050）。
 */
export function buildCsp(apiOrigin: string): string {
  const origin = /^https?:\/\//i.test(apiOrigin) ? apiOrigin.replace(/\/$/, '') : 'http://127.0.0.1:9050'
  const wsOrigin = origin.replace(/^http:/i, 'ws:').replace(/^https:/i, 'wss:')
  return [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' data: blob: ${origin} https:`,
    `media-src 'self' blob: data: https:`,
    "font-src 'self' data:",
    `connect-src 'self' ${origin} ${wsOrigin} https: wss:`,
    "worker-src 'self' blob:",
    "manifest-src 'self'",
    "form-action 'self'",
    "base-uri 'none'",
    "object-src 'none'",
    "frame-ancestors 'none'"
  ].join('; ')
}
