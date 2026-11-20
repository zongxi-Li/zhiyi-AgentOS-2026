import { ref, type Ref } from 'vue'
import { buildDiySkin, DIY_SKIN_ID, loadCustomization, sanitizeCustomization, saveCustomization, type CustomizationStorage } from './customization'
import { createRenderer } from './renderers'
import { COMPANION_SKIN_STORAGE_KEY, SkinRegistry } from './skins'
import { createSwitchGuard } from './switchGuard'
import type { AvatarRenderer, CompanionCustomization, CompanionState, SkinManifest } from './types'

interface AppearanceOptions {
  stage: Ref<HTMLElement | null>
  storage: CustomizationStorage | null
  state(): CompanionState
  speaking(): boolean
  listening(): boolean
  registry?: SkinRegistry
  rendererFactory?: (skin: SkinManifest) => AvatarRenderer
}

/** Owns effective appearance, editing rollback and latest-wins renderer lifetime. */
export function useCompanionAppearance(options: AppearanceOptions) {
  const customization = ref(loadCustomization(options.storage))
  const registry = options.registry ?? new SkinRegistry()
  const readSkin = () => { try { return options.storage?.getItem(COMPANION_SKIN_STORAGE_KEY) || 'companion-static' } catch { return 'companion-static' } }
  const skinId = ref(readSkin())
  const skins = ref(registry.list())
  const editing = ref(false)
  let snapshot: { skinId: string; value: CompanionCustomization } | null = null
  let renderer: AvatarRenderer | null = null
  let disposed = false
  let previewTimer: ReturnType<typeof setTimeout> | null = null
  const guard = createSwitchGuard()
  const factory = options.rendererFactory ?? createRenderer
  const clone = (value: CompanionCustomization) => sanitizeCustomization(value)
  const register = () => { registry.upsert(buildDiySkin(customization.value)); skins.value = registry.list() }
  register()

  const persistSkin = () => { try { options.storage?.setItem(COMPANION_SKIN_STORAGE_KEY, skinId.value) } catch { /* optional */ } }
  const replay = () => {
    renderer?.setState(options.state())
    renderer?.setSpeaking?.(options.speaking())
    renderer?.setListening?.(options.listening())
  }
  const applySkin = async (id: string): Promise<void> => {
    const stage = options.stage.value
    if (!stage || disposed) return
    const latest = guard.begin()
    const visited = new Set<string>()
    let skin: SkinManifest | null = registry.resolve(id)
    while (skin && !visited.has(skin.id)) {
      visited.add(skin.id)
      // Runtime preferences also apply to built-in skins; registry declarations stay immutable.
      const effective = { ...skin, custom: clone(customization.value) }
      const next = factory(effective)
      try {
        await next.mount(stage, effective)
        if (disposed || !latest()) { next.destroy(); return }
        const previous = renderer
        renderer = next
        replay()
        previous?.destroy()
        skinId.value = skin.id
        if (!editing.value) persistSkin()
        return
      } catch {
        next.destroy()
        if (disposed || !latest()) return
        skin = skin.fallbackSkinId ? registry.resolve(skin.fallbackSkinId) : null
        if ((!skin || visited.has(skin.id)) && !visited.has('companion-static')) skin = registry.resolve(null)
      }
    }
  }
  const clearPreview = () => { if (previewTimer !== null) clearTimeout(previewTimer); previewTimer = null }
  const beginEdit = () => {
    if (editing.value) return
    snapshot = { skinId: skinId.value, value: clone(customization.value) }
    editing.value = true
    void applySkin(DIY_SKIN_ID)
  }
  const preview = (value: CompanionCustomization) => {
    customization.value = clone(value)
    register()
    clearPreview()
    previewTimer = setTimeout(() => { previewTimer = null; void applySkin(editing.value ? DIY_SKIN_ID : skinId.value) }, 180)
  }
  const cancelEdit = () => {
    clearPreview()
    if (!editing.value || !snapshot) return
    customization.value = clone(snapshot.value)
    skinId.value = snapshot.skinId
    snapshot = null
    editing.value = false
    register()
    void applySkin(skinId.value)
  }
  const save = (value: CompanionCustomization) => {
    clearPreview()
    customization.value = clone(value)
    saveCustomization(options.storage, customization.value)
    snapshot = null
    editing.value = false
    register()
    skinId.value = DIY_SKIN_ID
    persistSkin()
    void applySkin(DIY_SKIN_ID)
  }
  const dispose = () => { disposed = true; clearPreview(); renderer?.destroy(); renderer = null }
  return {
    customization, skinId, skins, editing, applySkin, beginEdit, preview, cancelEdit, save, dispose,
    setState: (state: CompanionState) => renderer?.setState(state),
    setSpeaking: (on: boolean) => renderer?.setSpeaking?.(on),
    setListening: (on: boolean) => renderer?.setListening?.(on)
  }
}
