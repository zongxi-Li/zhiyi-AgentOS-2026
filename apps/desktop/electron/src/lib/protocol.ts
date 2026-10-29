import { protocol } from 'electron'
import { readFile, stat } from 'node:fs/promises'
import * as path from 'node:path'
import { buildCsp, contentTypeFor, decodeAppPath, resolveAppPath } from './app-assets'

/**
 * 生产环境用注册为 standard+secure 的自定义应用协议加载本地资源，
 * Origin 固定为 kinlin-app://shell（最小 CORS 面，无通配符）。
 * 开发环境走 Vite dev server，不经此协议。
 */
export const APP_SCHEME = 'kinlin-app'
export const APP_HOST = 'shell'
export const APP_INDEX_URL = `${APP_SCHEME}://${APP_HOST}/index.html`

function notFound(): Response {
  return new Response('Not found', { status: 404, headers: { 'content-type': 'text/plain; charset=utf-8' } })
}

/** 必须在 app ready 之前调用。 */
export function registerAppScheme(): void {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: APP_SCHEME,
      privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true, corsEnabled: true }
    }
  ])
}

/** 生产资源服务：只读 renderer 目录、无目录列表、HTML 注入 CSP。 */
export function handleAppProtocol(rendererDir: string, apiOrigin: string): void {
  const root = path.resolve(rendererDir)
  const csp = buildCsp(apiOrigin)
  protocol.handle(APP_SCHEME, async (request): Promise<Response> => {
    let url: URL
    try {
      url = new URL(request.url)
    } catch {
      return notFound()
    }
    if (url.host !== APP_HOST) return notFound()
    const relative = decodeAppPath(url.pathname)
    if (relative === null) return notFound()
    const resolved = resolveAppPath(root, relative)
    if (resolved === null) return notFound()

    let target = resolved
    try {
      const info = await stat(target)
      if (info.isDirectory()) {
        // SPA 根路径落到 index.html；hash 路由不产生其他历史回退需求。
        if (relative === '') target = path.join(root, 'index.html')
        else return notFound()
      }
    } catch {
      return notFound()
    }

    let body: Buffer
    try {
      body = await readFile(target)
    } catch {
      return notFound()
    }
    const contentType = contentTypeFor(target)
    const headers: Record<string, string> = {
      'content-type': contentType,
      'x-content-type-options': 'nosniff'
    }
    if (contentType.startsWith('text/html')) {
      headers['content-security-policy'] = csp
      headers['cache-control'] = 'no-store'
    }
    return new Response(new Uint8Array(body), { status: 200, headers })
  })
}
