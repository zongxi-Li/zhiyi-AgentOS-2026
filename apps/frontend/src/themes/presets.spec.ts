import { describe, expect, it } from 'vitest'
import { colorSchemes } from './presets'

const SEM_KEYS = [
  '--sem-success',
  '--sem-running',
  '--sem-waiting',
  '--sem-retry',
  '--sem-failed',
  '--sem-artifact',
  '--sem-flow',
  '--sem-text-1',
  '--sem-text-2',
  '--sem-text-3'
]

describe('color scheme semantic tokens', () => {
  it('every scheme defines the full semantic token set', () => {
    expect(colorSchemes).toHaveLength(5)
    for (const scheme of colorSchemes) {
      for (const key of SEM_KEYS) {
        const value = scheme.variables[key]
        expect(value, `${scheme.id} missing ${key}`).toBeTruthy()
      }
    }
  })

  it('light schemes carry darkened variants distinct from the dark spec values', () => {
    const dark = colorSchemes.filter(scheme => scheme.id === 'codex-dark' || scheme.id === 'one-dark-modern')
    const light = colorSchemes.filter(scheme => !dark.includes(scheme))
    for (const scheme of light) {
      expect(scheme.variables['--sem-running'], scheme.id).not.toBe('#6EA8FE')
      expect(scheme.variables['--sem-text-1'], scheme.id).toMatch(/^var\(--text-/)
    }
    for (const scheme of dark) {
      expect(scheme.variables['--sem-running']).toBe('#6EA8FE')
      expect(scheme.variables['--sem-success']).toBe('#8BCB78')
    }
  })
})
