import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  AsrUnavailableError, MAX_SEGMENT_FAILURES, SEGMENT_MS, SILENCE_STOP_MS, SPEECH_RMS_THRESHOLD,
  ServerSpeechRecognition, createResampler, createServerRecognition, floatToInt16, openMicrophoneSource, rms,
  type AudioSource
} from './serverAsr'
import type { RecognitionEventLike } from '../voice'

class FakeSource implements AudioSource {
  sampleRate = 16000
  onChunk: ((pcm: Float32Array) => void) | null = null
  started = false
  closed = false
  closeCount = 0
  async start(): Promise<void> { this.started = true }
  close(): void { this.closed = true; this.closeCount += 1 }
  pump(chunk: Float32Array): void { this.onChunk?.(chunk) }
}

const loud = (seconds: number): Float32Array => {
  const data = new Float32Array(Math.round(seconds * 16000))
  for (let i = 0; i < data.length; i += 1) data[i] = 0.3 * Math.sin((i / 16000) * 2 * Math.PI * 440)
  return data
}
const silence = (seconds: number): Float32Array => new Float32Array(Math.round(seconds * 16000))

interface Harness {
  recognition: ServerSpeechRecognition
  source: FakeSource
  clock: { now: number }
  uploads: Uint8Array[]
  results: RecognitionEventLike[]
  errors: string[]
  ends: number
}

const build = (options: { continuous?: boolean; failUploads?: number } = {}): Harness => {
  const source = new FakeSource()
  const clock = { now: 1_000_000 }
  const uploads: Uint8Array[] = []
  const results: RecognitionEventLike[] = []
  const errors: string[] = []
  let ends = 0
  let remaining = options.failUploads ?? 0
  const recognition = new ServerSpeechRecognition({
    openSource: async () => source,
    upload: (pcm) => {
      uploads.push(pcm)
      if (remaining > 0) {
        remaining -= 1
        return Promise.reject(new Error('boom'))
      }
      return Promise.resolve({ text: '知宝你好' })
    },
    now: () => clock.now
  })
  recognition.continuous = options.continuous === true
  recognition.onresult = (event) => results.push(event)
  recognition.onerror = (event) => errors.push(String(event.error))
  recognition.onend = () => { ends += 1 }
  const harness: Harness = {
    recognition, source, clock, uploads, results, errors,
    get ends() { return ends }
  }
  return harness
}

const settle = async (): Promise<void> => {
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
}

const deferred = <T>() => {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

const buildDeferred = (continuous = false, opening?: Promise<AudioSource>) => {
  const source = new FakeSource()
  const clock = { now: 1_000_000 }
  const uploads: ReturnType<typeof deferred<{ text: string }>>[] = []
  const events: string[] = []
  const recognition = new ServerSpeechRecognition({
    openSource: () => opening ?? Promise.resolve(source),
    upload: () => {
      const upload = deferred<{ text: string }>()
      uploads.push(upload)
      return upload.promise
    },
    now: () => clock.now
  })
  recognition.continuous = continuous
  recognition.onresult = event => events.push(`result:${event.results[event.resultIndex][0].transcript}`)
  recognition.onerror = event => events.push(`error:${event.error}`)
  recognition.onend = () => events.push('end')
  return { recognition, source, clock, uploads, events }
}

describe('ServerSpeechRecognition 异步生命周期', () => {
  it('detaches capture before starting the final upload', async () => {
    const source = new FakeSource()
    const captureClosedAtUpload: boolean[] = []
    const upload = vi.fn(async () => {
      captureClosedAtUpload.push(source.closed && source.onChunk === null)
      return { text: 'final' }
    })
    const recognition = new ServerSpeechRecognition({
      openSource: async () => source, upload, now: () => 0
    })
    const errors: string[] = []
    recognition.onerror = event => errors.push(String(event.error))
    recognition.start()
    await settle()
    source.pump(loud(0.01))
    recognition.stop()
    await settle()
    expect(upload).toHaveBeenCalledOnce()
    expect(captureClosedAtUpload).toEqual([true])
    expect(errors).toEqual([])
  })

  it('stop closes capture immediately and drains accepted uploads before one end', async () => {
    const h = buildDeferred(true)
    h.recognition.start()
    await settle()
    h.source.pump(loud(0.01))
    h.clock.now += SEGMENT_MS
    h.source.pump(loud(0.01))
    await settle()
    h.source.pump(loud(0.01))
    h.recognition.stop()
    h.recognition.stop()
    expect(h.source.closed).toBe(true)
    expect(h.source.onChunk).toBeNull()
    expect(h.events).toEqual([])
    expect(h.uploads).toHaveLength(1)

    h.uploads[0].resolve({ text: 'first' })
    await settle()
    await settle()
    expect(h.events).toEqual(['result:first'])
    expect(h.uploads).toHaveLength(2)
    h.uploads[1].resolve({ text: 'last' })
    await settle()
    await settle()
    expect(h.events).toEqual(['result:first', 'result:last', 'end'])
    h.recognition.stop()
    h.recognition.abort()
    expect(h.source.closeCount).toBe(1)
    expect(h.events).toHaveLength(3)
  })

  it.each([
    ['network', new Error('offline')],
    ['asr-unavailable', new AsrUnavailableError()]
  ])('delivers delayed %s before end when its error callback stops again', async (code, error) => {
    const h = buildDeferred()
    h.recognition.onerror = event => {
      h.events.push(`error:${event.error}`)
      h.recognition.stop()
    }
    h.recognition.start()
    await settle()
    h.source.pump(loud(0.01))
    h.recognition.stop()
    await settle()
    expect(h.events).toEqual([])
    h.uploads[0].reject(error)
    await settle()
    await settle()
    expect(h.events).toEqual([`error:${code}`, 'end'])
    expect(h.source.closeCount).toBe(1)
  })

  it.each(['resolve', 'reject'] as const)('abort immediately drops queued work and suppresses in-flight %s', async outcome => {
    const h = buildDeferred(true)
    h.recognition.start()
    await settle()
    h.clock.now += SEGMENT_MS
    h.source.pump(loud(0.01))
    await settle()
    h.clock.now += SEGMENT_MS
    h.source.pump(loud(0.01))
    h.source.pump(loud(0.01))
    h.recognition.stop()
    h.recognition.abort()
    h.recognition.abort()
    h.recognition.stop()
    expect(h.events).toEqual(['end'])
    expect(h.source.closeCount).toBe(1)
    if (outcome === 'resolve') h.uploads[0].resolve({ text: 'late' })
    else h.uploads[0].reject(new Error('late failure'))
    await settle()
    await settle()
    expect(h.events).toEqual(['end'])
    expect(h.uploads).toHaveLength(1)
  })

  it.each(['stop', 'abort'] as const)('%s before queued upload starts discards it only on abort', async action => {
    const h = buildDeferred()
    h.recognition.start()
    await settle()
    h.source.pump(loud(0.01))
    h.recognition[action]()
    await settle()
    expect(h.uploads).toHaveLength(action === 'stop' ? 1 : 0)
    if (action === 'stop') {
      h.uploads[0].resolve({ text: 'accepted' })
      await settle()
      await settle()
      expect(h.events).toEqual(['result:accepted', 'end'])
    } else expect(h.events).toEqual(['end'])
  })

  it.each(['stop', 'abort'] as const)('%s closes a late permission source without new callbacks', async action => {
    const opening = deferred<AudioSource>()
    const h = buildDeferred(false, opening.promise)
    h.recognition.start()
    h.recognition[action]()
    await settle()
    expect(h.events).toEqual(['end'])
    opening.resolve(h.source)
    await settle()
    expect(h.source.closeCount).toBe(1)
    expect(h.source.onChunk).toBeNull()
    expect(h.events).toEqual(['end'])
    expect(h.uploads).toEqual([])
  })

  it.each(['stop', 'abort'] as const)('%s ignores a late permission rejection while an end callback remains installed', async action => {
    const opening = deferred<AudioSource>()
    const h = buildDeferred(false, opening.promise)
    h.recognition.start()
    h.recognition[action]()
    // Rejection races the queued end task, before callbacks have been cleared.
    opening.reject(new Error('permission denied'))
    await settle()
    await settle()
    expect(h.events).toEqual(['end'])
  })
})

describe('openMicrophoneSource resources', () => {
  afterEach(() => vi.unstubAllGlobals())

  const microphone = (failure?: 'constructor' | 'processor' | 'input-connect' | 'output-connect') => {
    const stop = vi.fn()
    const input = { connect: vi.fn(), disconnect: vi.fn() }
    const processor = { onaudioprocess: null as ((event: { inputBuffer: { getChannelData: () => Float32Array } }) => void) | null,
      connect: vi.fn(), disconnect: vi.fn() }
    const stream = { getTracks: () => [{ stop }] }
    const context = { sampleRate: 16000, destination: {}, resume: vi.fn().mockResolvedValue(undefined),
      close: vi.fn().mockResolvedValue(undefined),
      createMediaStreamSource: vi.fn(() => input), createScriptProcessor: vi.fn(() => processor) }
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn().mockResolvedValue(stream) } })
    vi.stubGlobal('AudioContext', class {
      constructor() { if (failure === 'constructor') throw new Error('setup failed'); return context }
    })
    if (failure === 'processor') context.createScriptProcessor.mockImplementation(() => { throw new Error('setup failed') })
    if (failure === 'input-connect') input.connect.mockImplementation(() => { throw new Error('setup failed') })
    if (failure === 'output-connect') processor.connect.mockImplementation(() => { throw new Error('setup failed') })
    return { context, stream, input, processor, stop }
  }

  it('connects the microphone to the processor and releases each resource once', async () => {
    const h = microphone()
    const source = await openMicrophoneSource()
    const chunk = vi.fn()
    source.onChunk = chunk
    expect(h.context.createMediaStreamSource).toHaveBeenCalledWith(h.stream)
    expect(h.input.connect).toHaveBeenCalledWith(h.processor)
    expect(h.processor.connect).toHaveBeenCalledWith(h.context.destination)
    h.processor.onaudioprocess?.({ inputBuffer: { getChannelData: () => loud(0.01) } })
    expect(chunk).toHaveBeenCalledOnce()
    source.close()
    source.close()
    expect(source.onChunk).toBeNull()
    expect(h.processor.onaudioprocess).toBeNull()
    expect(h.input.disconnect).toHaveBeenCalledOnce()
    expect(h.processor.disconnect).toHaveBeenCalledOnce()
    expect(h.stop).toHaveBeenCalledOnce()
    expect(h.context.close).toHaveBeenCalledOnce()
  })

  it.each(['constructor', 'processor', 'input-connect', 'output-connect'] as const)(
    'releases acquired microphone resources if %s setup fails', async failure => {
      const h = microphone(failure)
      await expect(openMicrophoneSource()).rejects.toThrow('setup failed')
      expect(h.stop).toHaveBeenCalledOnce()
      expect(h.context.close).toHaveBeenCalledTimes(failure === 'constructor' ? 0 : 1)
      if (failure === 'input-connect' || failure === 'output-connect') {
        expect(h.input.disconnect).toHaveBeenCalledOnce()
        expect(h.processor.disconnect).toHaveBeenCalledOnce()
        expect(h.processor.onaudioprocess).toBeNull()
      }
    }
  )
})

describe('serverAsr 纯函数', () => {
  it('resampler：16k 恒等，48k→16k 长度正确且相位连续', () => {
    const identity = createResampler(16000, 16000)
    const chunk = new Float32Array([0.1, 0.2, 0.3])
    expect(identity(chunk)).toBe(chunk)

    const down = createResampler(48000, 16000)
    const first = down(new Float32Array(48000).fill(0.5))
    // 首块：可输出 floor((48000-1)/3) 个样本
    expect(first.length).toBeGreaterThan(15800)
    expect(first.length).toBeLessThanOrEqual(16000)
    expect([...first.slice(0, 5)]).toEqual([0.5, 0.5, 0.5, 0.5, 0.5])
    const second = down(new Float32Array(48000).fill(0.5))
    expect(second.length).toBe(16000)
  })

  it('floatToInt16 钳位与量化', () => {
    expect([...floatToInt16(new Float32Array([0, 0.5, -0.5, 2, -2]))])
      .toEqual([0, 16384, -16384, 32767, -32768])
  })

  it('rms：静音接近 0，语音超过阈值', () => {
    expect(rms(silence(0.1))).toBeLessThan(SPEECH_RMS_THRESHOLD)
    expect(rms(loud(0.1))).toBeGreaterThan(SPEECH_RMS_THRESHOLD)
  })

  it('createServerRecognition：无 mediaDevices 的宿主返回 null', () => {
    expect(createServerRecognition()).toBeNull()
  })
})

describe('ServerSpeechRecognition 单次模式', () => {
  it('说话后静音自动断句：先 onresult(final) 再 onend，音频只上传一次', async () => {
    const harness = build()
    harness.recognition.start()
    await settle()
    harness.source.pump(loud(0.4))
    harness.clock.now += 400
    harness.source.pump(silence(SILENCE_STOP_MS / 1000 + 0.1))
    harness.clock.now += SILENCE_STOP_MS + 100
    // 静音断句在下一块音频到达时判定；再泵一块触发。
    harness.source.pump(silence(0.05))
    await settle()
    await settle()

    expect(harness.uploads).toHaveLength(1)
    expect(harness.results).toHaveLength(1)
    expect(harness.results[0].results[0].isFinal).toBe(true)
    expect(harness.results[0].results[0][0].transcript).toBe('知宝你好')
    expect(harness.errors).toEqual([])
    expect(harness.ends).toBe(1)
    expect(harness.source.closed).toBe(true)
  })

  it('手动 stop()：等完在途上传再 onend（结果先于结束）', async () => {
    const harness = build()
    const order: string[] = []
    harness.recognition.onresult = () => order.push('result')
    harness.recognition.onend = () => order.push('end')
    harness.recognition.start()
    await settle()
    harness.source.pump(loud(0.5))
    harness.recognition.stop()
    await settle()
    await settle()
    expect(order).toEqual(['result', 'end'])
    expect(harness.uploads).toHaveLength(1)
  })

  it('abort()：丢弃音频不上传，只触发 onend', async () => {
    const harness = build()
    harness.recognition.start()
    await settle()
    harness.source.pump(loud(0.5))
    harness.recognition.abort()
    await settle()
    await settle()
    expect(harness.uploads).toHaveLength(0)
    expect(harness.results).toHaveLength(0)
    expect(harness.ends).toBe(1)
  })

  it('识别为空且说过话 → no-speech 错误', async () => {
    const source = new FakeSource()
    const clock = { now: 1_000_000 }
    const errors: string[] = []
    let ends = 0
    const recognition = new ServerSpeechRecognition({
      openSource: async () => source,
      upload: async () => ({ text: '' }),
      now: () => clock.now
    })
    recognition.onerror = (event) => errors.push(String(event.error))
    recognition.onend = () => { ends += 1 }
    recognition.start()
    await settle()
    source.pump(loud(0.4))
    recognition.stop()
    await settle()
    await settle()
    expect(errors).toEqual(['no-speech'])
    expect(ends).toBe(1)
  })

  it('上传失败 → network 错误并结束', async () => {
    const harness = build({ failUploads: 1 })
    harness.recognition.start()
    await settle()
    harness.source.pump(loud(0.4))
    harness.recognition.stop()
    await settle()
    await settle()
    expect(harness.errors).toEqual(['network'])
    expect(harness.ends).toBe(1)
  })

  it('模型缺失（503 语义）→ asr-unavailable', async () => {
    const source = new FakeSource()
    const clock = { now: 0 }
    const errors: string[] = []
    const recognition = new ServerSpeechRecognition({
      openSource: async () => source,
      upload: () => Promise.reject(new AsrUnavailableError()),
      now: () => clock.now
    })
    recognition.onerror = (event) => errors.push(String(event.error))
    recognition.start()
    await settle()
    source.pump(loud(0.4))
    recognition.stop()
    await settle()
    await settle()
    expect(errors).toEqual(['asr-unavailable'])
  })

  it('openSource 失败 → audio-capture', async () => {
    const recognition = new ServerSpeechRecognition({
      openSource: () => Promise.reject(new Error('no mic')),
      upload: async () => ({ text: '' }),
      now: () => 0
    })
    const errors: string[] = []
    let ends = 0
    recognition.onerror = (event) => errors.push(String(event.error))
    recognition.onend = () => { ends += 1 }
    recognition.start()
    await settle()
    await settle()
    expect(errors).toEqual(['audio-capture'])
    expect(ends).toBe(1)
  })
})

describe('ServerSpeechRecognition 常驻模式', () => {
  it('每 SEGMENT_MS 切一段：多段结果 resultIndex 递增，不提前 onend', async () => {
    const harness = build({ continuous: true })
    harness.recognition.start()
    await settle()

    harness.source.pump(loud(0.3))
    harness.clock.now += SEGMENT_MS + 100
    harness.source.pump(loud(0.3)) // 触发切段
    await settle()
    harness.clock.now += SEGMENT_MS + 100
    harness.source.pump(loud(0.3))
    await settle()
    await settle()

    expect(harness.uploads).toHaveLength(2)
    expect(harness.results).toHaveLength(2)
    expect(harness.results[0].resultIndex).toBe(0)
    expect(harness.results[1].resultIndex).toBe(1)
    expect(harness.ends).toBe(0)
    expect(harness.source.closed).toBe(false)

    harness.recognition.stop()
    await settle()
    await settle()
    expect(harness.ends).toBe(1)
    expect(harness.source.closed).toBe(true)
  })

  it(`连续 ${MAX_SEGMENT_FAILURES} 段失败才放弃，之前的失败不致命`, async () => {
    const harness = build({ continuous: true, failUploads: MAX_SEGMENT_FAILURES })
    harness.recognition.start()
    await settle()
    for (let round = 0; round < MAX_SEGMENT_FAILURES; round += 1) {
      harness.source.pump(loud(0.3))
      harness.clock.now += SEGMENT_MS + 100
      harness.source.pump(silence(0.05))
      await settle()
      await settle()
    }
    expect(harness.errors).toEqual(['network'])
    expect(harness.ends).toBe(1)
  })
})
