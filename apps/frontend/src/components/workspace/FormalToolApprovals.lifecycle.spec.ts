import { defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import FormalToolApprovals from './FormalToolApprovals.vue'
import { agentosRequest } from '@/services/api/agentos/client'

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks() })
it('stops approval polling while cached, ignores its late read, and releases the resumed loop', async () => {
  vi.useFakeTimers()
  let finish!: (value: any) => void
  const read = vi.spyOn(agentosRequest, 'get').mockImplementationOnce(() => new Promise(ok => { finish = ok }))
    .mockResolvedValue({ data: { items: [] } } as any)
  const visible = ref(true)
  const host = defineComponent({ setup: () => () => h(KeepAlive, null, { default: () => visible.value
    ? h(FormalToolApprovals, { runId: 'run', active: true }) : null }) })
  const wrapper = mount(host)
  visible.value = false; await nextTick()
  finish({ data: { items: [{ approvalId: 'late', operationSummary: 'obsolete' }] } }); await flushPromises()
  await vi.advanceTimersByTimeAsync(5000)
  expect(read).toHaveBeenCalledTimes(1)
  visible.value = true; await nextTick(); await flushPromises()
  expect(wrapper.text()).not.toContain('obsolete')
  expect(read).toHaveBeenCalledTimes(2)
  await vi.advanceTimersByTimeAsync(1000); expect(read).toHaveBeenCalledTimes(3)
  wrapper.unmount(); await vi.advanceTimersByTimeAsync(5000)
  expect(read).toHaveBeenCalledTimes(3)
})
