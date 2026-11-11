import { beforeEach, describe, expect, it } from 'vitest'
import { initBrand, useBrand } from './useBrand'

// 品牌标三选一：持久化读取、非法值回退、favicon 跟随、弈章按主题换用深浅变体资产。
// 变体口径：浅色主题显示黑线 logo-light.png，深色主题显示白线 logo-dark.png，无滤镜反相。

const favicon = () => document.querySelector<HTMLLinkElement>("link[rel='icon']")

describe('useBrand', () => {
  beforeEach(() => {
    localStorage.clear()
    document.head.innerHTML = ''
    document.documentElement.removeAttribute('data-color-scheme')
  })

  it('defaults to ember (current visuals unchanged) and rewrites the favicon', () => {
    document.head.innerHTML = '<link rel="icon" href="/logo-compact.svg" type="image/svg+xml">'
    initBrand()
    const { activePack } = useBrand()
    expect(activePack.value.id).toBe('ember')
    expect(favicon()?.getAttribute('href')).toBe('/logo.webp')
    expect(favicon()?.getAttribute('type')).toBe('image/webp')
  })

  it('creates the favicon link when the document has none', () => {
    initBrand()
    expect(favicon()).not.toBeNull()
    expect(favicon()?.getAttribute('href')).toBe('/logo.webp')
  })

  it('reads a persisted ink pack and points the favicon at the compact plate', () => {
    localStorage.setItem('appSettings', JSON.stringify({ brand: 'ink' }))
    initBrand()
    const { activePack } = useBrand()
    expect(activePack.value.id).toBe('ink')
    expect(favicon()?.getAttribute('href')).toBe('/brand/ink/logo-compact.png')
    expect(favicon()?.getAttribute('type')).toBe('image/png')
  })

  it('falls back to ember on an unknown persisted pack', () => {
    localStorage.setItem('appSettings', JSON.stringify({ brand: 'nope' }))
    initBrand()
    const { activePack } = useBrand()
    expect(activePack.value.id).toBe('ember')
  })

  it('survives a corrupt appSettings payload', () => {
    localStorage.setItem('appSettings', '{broken')
    expect(() => initBrand()).not.toThrow()
    const { activePack } = useBrand()
    expect(activePack.value.id).toBe('ember')
  })

  it('serves the ink pack the light asset under a light scheme and the dark asset under a dark scheme', () => {
    const root = document.documentElement
    const { setBrand, activePack } = useBrand()

    root.dataset.colorScheme = 'claude-warm'
    setBrand('ink')
    expect(activePack.value.main).toBe('/brand/ink/logo-light.png')
    expect(activePack.value.mark).toBe('/brand/ink/logo-light.png')

    root.dataset.colorScheme = 'codex-dark'
    setBrand('ink')
    expect(activePack.value.main).toBe('/brand/ink/logo-dark.png')
    expect(activePack.value.mark).toBe('/brand/ink/logo-dark.png')
    expect(activePack.value.favicon).toBe('/brand/ink/logo-compact.png')

    setBrand('ember')
    expect(activePack.value.main).toBe('/logo.svg')
  })
})
