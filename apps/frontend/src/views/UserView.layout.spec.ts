import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const userViewSource = readFileSync(resolve(process.cwd(), 'src/views/UserView.vue'), 'utf8')

describe('UserView desktop layout', () => {
  it('uses a wider content canvas to avoid oversized side margins', () => {
    expect(userViewSource).toContain('width: min(100%, 1400px)')
  })
})
