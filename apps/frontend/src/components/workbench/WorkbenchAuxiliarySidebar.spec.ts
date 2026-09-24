import { defineComponent, markRaw } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import WorkbenchAuxiliarySidebar from './WorkbenchAuxiliarySidebar.vue'

const OpenFileChild = defineComponent({
  emits: ['open-file'],
  template: '<button type="button" @click="$emit(\'open-file\', { relativePath: \'README.md\' })">Open</button>'
})

describe('WorkbenchAuxiliarySidebar', () => {
  it('forwards the file-open event from its active auxiliary view', async () => {
    const wrapper = mount(WorkbenchAuxiliarySidebar, {
      props: {
        view: { id: 'files', title: '文件', order: 50, component: markRaw(OpenFileChild), when: () => true }
      }
    })

    await wrapper.get('button').trigger('click')

    expect(wrapper.emitted('open-file')?.[0]?.[0]).toEqual({ relativePath: 'README.md' })
    wrapper.unmount()
  })
})
