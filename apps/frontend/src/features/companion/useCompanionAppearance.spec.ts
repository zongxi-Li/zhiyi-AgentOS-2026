import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'
import { useCompanionAppearance } from './useCompanionAppearance'
import { CUSTOMIZATION_STORAGE_KEY, DEFAULT_CUSTOMIZATION } from './customization'
import { BUILTIN_SKINS, COMPANION_SKIN_STORAGE_KEY, SkinRegistry } from './skins'
import type { AvatarRenderer, SkinManifest } from './types'

const build = () => {
  const data = new Map<string, string>()
  const storage = { getItem: (key: string) => data.get(key) ?? null, setItem: (key: string, value: string) => { data.set(key, value) } }
  const renderer = { mount: vi.fn(), setState: vi.fn(), setSpeaking: vi.fn(), setListening: vi.fn(), destroy: vi.fn() }
  const appearance = useCompanionAppearance({ stage: ref(document.createElement('div')), state: () => 'idle', speaking: () => false, listening: () => false, storage, rendererFactory: () => ({ ...renderer }) })
  return { ...appearance, data, renderer }
}

describe('Companion appearance editing transaction', () => {
  it('restores all unsaved fields and the persisted skin after cancelling', async () => {
    const a = build()
    await a.applySkin('companion-static')
    a.beginEdit()
    a.preview({ ...DEFAULT_CUSTOMIZATION, name: '草稿', lines: ['草稿话术'], voice: { ...DEFAULT_CUSTOMIZATION.voice, muted: true }, motion: false })
    expect(a.customization.value.name).toBe('草稿')
    a.cancelEdit()
    await Promise.resolve()
    expect(a.customization.value).toEqual(DEFAULT_CUSTOMIZATION)
    expect(a.skinId.value).toBe('companion-static')
    expect(a.data.get(COMPANION_SKIN_STORAGE_KEY)).toBe('companion-static')
    expect(a.data.has(CUSTOMIZATION_STORAGE_KEY)).toBe(false)
    a.dispose()
  })

  it('also restores a previously saved DIY avatar and commits new fields only on save', async () => {
    const a = build()
    const saved = { ...DEFAULT_CUSTOMIZATION, name: '已保存' }
    a.save(saved)
    a.beginEdit()
    a.preview({ ...saved, name: '没保存' })
    a.cancelEdit()
    expect(a.customization.value.name).toBe('已保存')
    expect(a.skinId.value).toBe('companion-diy')
    expect(JSON.parse(a.data.get(CUSTOMIZATION_STORAGE_KEY)!).name).toBe('已保存')
    a.dispose()
  })

  it('uses manifest fallback links and replays current state/voice on the surviving renderer', async () => {
    const mounted: string[] = []
    const survivor = { mount: vi.fn(), setState: vi.fn(), setSpeaking: vi.fn(), setListening: vi.fn(), destroy: vi.fn() }
    const a = useCompanionAppearance({
      stage: ref(document.createElement('div')), storage: null, state: () => 'working', speaking: () => true, listening: () => false,
      rendererFactory: skin => ({ ...survivor, mount: () => { mounted.push(skin.id); if (skin.id === 'companion-grok') throw new Error('engine failed') } })
    })
    await a.applySkin('companion-grok')
    expect(mounted).toEqual(['companion-grok', 'companion-static'])
    expect(a.skinId.value).toBe('companion-static')
    expect(survivor.setState).toHaveBeenCalledWith('working')
    expect(survivor.setSpeaking).toHaveBeenCalledWith(true)
    expect(survivor.setListening).toHaveBeenCalledWith(false)
    a.dispose()
  })

  it('falls back to static when manifest links cycle', async () => {
    const cyclic = { ...BUILTIN_SKINS[1], id: 'companion-loop', fallbackSkinId: 'companion-loop' }
    const mounted: string[] = []
    const a = useCompanionAppearance({
      stage: ref(document.createElement('div')), storage: null, state: () => 'idle', speaking: () => false, listening: () => false,
      registry: new SkinRegistry([BUILTIN_SKINS[0], cyclic, BUILTIN_SKINS[2]]),
      rendererFactory: skin => ({ mount() { mounted.push(skin.id); if (skin.id !== 'companion-static') throw new Error('failed') }, setState() {}, destroy() {} })
    })
    await a.applySkin('companion-loop')
    expect(mounted).toEqual(['companion-loop', 'companion-static'])
    a.dispose()
  })

  it('destroys a stale async mount and never lets it replace the latest selection', async () => {
    let release!: () => void
    const pending = new Promise<void>(resolve => { release = resolve })
    const made: { skin: SkinManifest; renderer: AvatarRenderer }[] = []
    const a = useCompanionAppearance({
      stage: ref(document.createElement('div')), storage: null, state: () => 'idle', speaking: () => false, listening: () => false,
      rendererFactory: skin => {
        const renderer = { mount: () => skin.id === 'companion-grok' ? pending : undefined, setState: vi.fn(), destroy: vi.fn() }
        made.push({ skin, renderer })
        return renderer
      }
    })
    const old = a.applySkin('companion-grok')
    await a.applySkin('companion-static')
    release()
    await old
    expect(a.skinId.value).toBe('companion-static')
    expect(made[0].renderer.destroy).toHaveBeenCalledOnce()
    expect(made[1].renderer.destroy).not.toHaveBeenCalled()
    a.dispose()
    expect(made[1].renderer.destroy).toHaveBeenCalledOnce()
  })

  it('cleans up a candidate that finishes mounting after disposal', async () => {
    let release!: () => void
    const pending = new Promise<void>(resolve => { release = resolve })
    const destroy = vi.fn()
    const a = useCompanionAppearance({ stage: ref(document.createElement('div')), storage: null, state: () => 'idle', speaking: () => false, listening: () => false,
      rendererFactory: () => ({ mount: () => pending, setState: vi.fn(), destroy }) })
    const mounting = a.applySkin('companion-grok')
    a.dispose()
    release()
    await mounting
    expect(destroy).toHaveBeenCalledOnce()
  })
})
