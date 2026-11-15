import { afterEach, describe, expect, it, vi } from 'vitest'
import { ElMessage } from 'element-plus'
import request from '@/utils/request'
import { chatApi } from './chat'

const original = request.defaults.adapter
afterEach(() => { request.defaults.adapter = original; vi.restoreAllMocks() })

describe('approval terminal responses', () => {
  it.each([[404,'APPROVAL_NOT_FOUND'],[409,'APPROVAL_EXPIRED']])('normalizes %s %s without a global failure toast', async (status,code) => {
    const notify=vi.spyOn(ElMessage,'error')
    request.defaults.adapter=async config=>({status:status as number,statusText:'expired',headers:{},config,
      data:{detail:{code,message:'approval does not exist'}}})
    const result=await chatApi.resolveApproval('approval',{decision:'allow_once',sessionId:'session'})
    expect(result.status).toBe('expired')
    expect(notify).not.toHaveBeenCalled()
  })
  it.each([[404,'NOT_FOUND'],[409,'APPROVAL_SCOPE_MISMATCH'],[409,'APPROVAL_REPLAYED']])('does not disguise %s %s as expiry', async (status,code) => {
    request.defaults.adapter=async config=>({status:status as number,statusText:'error',headers:{},config,data:{detail:{code,message:'real error'}}})
    await expect(chatApi.resolveApproval('approval',{decision:'allow_once',sessionId:'session'})).rejects.toMatchObject({response:{status}})
  })
})
