import { describe, expect, it } from 'vitest'
import { connectionGuidance, customerResourceType, deploymentGroup } from './resourceCenterPresentation'

describe('resource center presentation', () => {
  it('maps runtime catalog categories to customer resource names', () => {
    expect(customerResourceType('model_server')).toBe('模型')
    expect(customerResourceType('tool_service')).toBe('工具')
    expect(customerResourceType('execution_backend')).toBe('设备服务')
  })

  it('groups local, edge, and cloud deployments into customer topology columns', () => {
    expect(deploymentGroup('local')).toEqual({ id: 'device', label: '我的设备' })
    expect(deploymentGroup('edge')).toEqual({ id: 'edge', label: '边缘节点' })
    expect(deploymentGroup('cloud')).toEqual({ id: 'cloud', label: '云端服务' })
    expect(deploymentGroup('satellite')).toEqual({ id: 'other', label: '其他位置' })
    expect(deploymentGroup('terminal')).toEqual({ id: 'device', label: '我的设备' })
  })

  it('explains an offline resource with a direct next action', () => {
    expect(connectionGuidance('offline')).toEqual({ tone: 'danger', action: '检测连接' })
  })
})
