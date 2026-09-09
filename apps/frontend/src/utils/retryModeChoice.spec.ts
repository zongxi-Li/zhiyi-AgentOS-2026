import { ElMessageBox } from 'element-plus'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { chooseFailedRunRetryMode } from './retryModeChoice'

describe('chooseFailedRunRetryMode', () => {
  afterEach(() => vi.restoreAllMocks())

  it('uses a successor Run as the recommended confirm action', async () => {
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm')
    await expect(chooseFailedRunRetryMode('run_failed')).resolves.toBe('successor_run')
  })

  it('maps the explicit secondary action to an in-place retry', async () => {
    vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('cancel')
    await expect(chooseFailedRunRetryMode('run_failed')).resolves.toBe('current_run')
  })

  it('does not run anything when the dialog is closed', async () => {
    vi.spyOn(ElMessageBox, 'confirm').mockRejectedValue('close')
    await expect(chooseFailedRunRetryMode('run_failed')).resolves.toBeNull()
  })
})
