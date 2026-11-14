import { vi } from 'vitest'

/** Add the real start acknowledgement contract to existing stream fixtures. */
export function chatExecutionFetch(stream: (...args: any[]) => any, cancel?: (...args: any[]) => any) {
  let count = 0
  return vi.fn(async (url: any, init?: any) => {
    if (String(url).endsWith('/api/chat/executions')) {
      const payload = JSON.parse(init.body)
      return Response.json({chatExecutionId: `execution-${++count}`, contextId: payload.context_id || 'new-context'})
    }
    if (String(url).endsWith('/cancel')) return cancel ? cancel(url, init) : Response.json({cancelled: true})
    return stream(url, init)
  })
}
