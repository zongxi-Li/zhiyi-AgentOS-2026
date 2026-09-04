import { shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import IdentityHealthStrip from './IdentityHealthStrip.vue'
import type { IdentityProjectionHealth } from '@/services/api/workflow'

describe('IdentityHealthStrip', () => {
  it('keeps rendering when startup reconciliation data is missing', () => {
    const wrapper = shallowMount(IdentityHealthStrip, {
      props: {
        health: { status: 'healthy' } as IdentityProjectionHealth,
        loading: false,
        error: '',
        lastUpdatedAt: null
      }
    })

    expect(wrapper.find('.identity-health').exists()).toBe(true)
    expect(wrapper.find('.health-metrics').text()).toContain('0')
  })
})
