import { describe, expect, it, vi } from 'vitest'
import { parseChatStreamFrame, readSseFrames, type SseFrame } from './sse'

const encoder = new TextEncoder()
const streamOf = (chunks: Uint8Array[]) => new ReadableStream<Uint8Array>({ start(controller) {
  chunks.forEach(chunk => controller.enqueue(chunk))
  controller.close()
} })
const collect = async (stream: ReadableStream<Uint8Array>, options?: Parameters<typeof readSseFrames>[1]) => {
  const frames: SseFrame[] = []
  for await (const frame of readSseFrames(stream, options)) frames.push(frame)
  return frames
}

describe('shared SSE reader', () => {
  it('decodes split UTF-8 and CRLF, joining data fields without trimming their content', async () => {
    const bytes = encoder.encode(': heartbeat\r\n\r\nevent: update\r\ndata:  你好😀\r\ndata:second\r\n\r\ndata: last\n\n')
    const stream = streamOf(Array.from(bytes, byte => Uint8Array.of(byte)))
    const onActivity = vi.fn()
    expect(await collect(stream, { onActivity })).toEqual([
      { event: 'update', data: ' 你好😀\nsecond' }, { event: '', data: 'last' }
    ])
    expect(onActivity).toHaveBeenCalledTimes(bytes.length)
    expect(stream.locked).toBe(false)
  })

  it('reports comment-only chunks as activity without dispatching a business frame', async () => {
    const onActivity = vi.fn()
    expect(await collect(streamOf([encoder.encode(': ping\n\n')]), { onActivity })).toEqual([])
    expect(onActivity).toHaveBeenCalledOnce()
  })

  it('keeps EOF tail compatibility explicit for endpoints that need it', async () => {
    expect(await collect(streamOf([encoder.encode('data: tail')]))).toEqual([])
    expect(await collect(streamOf([encoder.encode('data: tail')]), { flushAtEof: true }))
      .toEqual([{ event: '', data: 'tail' }])
  })

  it('cancels and releases the reader when the caller reaches its terminal event', async () => {
    const cancel = vi.fn()
    const stream = new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(encoder.encode('data: terminal\n\ndata: late\n\n')) }, cancel
    })
    const frames: SseFrame[] = []
    for await (const frame of readSseFrames(stream)) { frames.push(frame); break }
    expect(frames).toEqual([{ event: '', data: 'terminal' }])
    expect(cancel).toHaveBeenCalledOnce()
    expect(stream.locked).toBe(false)
  })

  it('aborts a pending read and releases its lock', async () => {
    const cancel = vi.fn()
    const stream = new ReadableStream<Uint8Array>({ cancel })
    const controller = new AbortController()
    const reading = collect(stream, { signal: controller.signal })
    controller.abort()
    await expect(reading).rejects.toMatchObject({ name: 'AbortError' })
    expect(cancel).toHaveBeenCalledOnce()
    expect(stream.locked).toBe(false)
  })

  it('does not dispatch already buffered frames after the caller aborts', async () => {
    const controller = new AbortController()
    const stream = streamOf([encoder.encode('data: first\n\ndata: stale\n\n')])
    const frames: SseFrame[] = []
    const reading = (async () => {
      for await (const frame of readSseFrames(stream, { signal: controller.signal })) {
        frames.push(frame)
        controller.abort()
      }
    })()
    await expect(reading).rejects.toMatchObject({ name: 'AbortError' })
    expect(frames).toEqual([{ event: '', data: 'first' }])
    expect(stream.locked).toBe(false)
  })

  it('preserves transport and consumer errors while releasing the reader', async () => {
    const transportError = new Error('transport failed')
    const failed = new ReadableStream<Uint8Array>({ start(controller) { controller.error(transportError) } })
    await expect(collect(failed)).rejects.toBe(transportError)
    expect(failed.locked).toBe(false)

    const cancel = vi.fn().mockRejectedValue(new Error('cleanup failed'))
    const stream = new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(encoder.encode('data: hello\n\n')) }, cancel
    })
    const businessError = new Error('business failed')
    const reading = (async () => {
      for await (const _frame of readSseFrames(stream)) throw businessError
    })()
    await expect(reading).rejects.toBe(businessError)
    expect(cancel).toHaveBeenCalledOnce()
    expect(stream.locked).toBe(false)
  })

  it('retains gateway chat error decoding through the shared field parser', () => {
    expect(parseChatStreamFrame('event: error\r\ndata: {"code":"AI_UPSTREAM_TIMEOUT","message":"timeout"}'))
      .toMatchObject({ event: 'error', data: { code: 'AI_UPSTREAM_TIMEOUT', message: 'timeout' } })
  })
})
