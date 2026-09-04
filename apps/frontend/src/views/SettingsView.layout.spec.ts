import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const settingsViewSource = readFileSync(resolve(process.cwd(), 'src/views/SettingsView.vue'), 'utf8')

describe('SettingsView desktop layout', () => {
  it('uses a wider content canvas to avoid oversized side margins', () => {
    expect(settingsViewSource).toContain('width: min(100%, 1400px)')
  })
})
