import { KeepAlive, defineComponent, h, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { DockviewVue, type DockviewReadyEvent } from 'dockview-vue'
import DockingWorkbenchLayout from './DockingWorkbenchLayout.vue'
import { DOCK_STORAGE_KEY } from './dockingLayout'

let wrapper: ReturnType<typeof mount> | undefined
beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
})
afterEach(() => { wrapper?.unmount(); wrapper = undefined; vi.unstubAllGlobals() })

it('keeps one business instance through merge, hide, reset and KeepAlive reactivation', async () => {
  const mounts: Record<string, number> = {}
  const unmounts: string[] = []
  const contents: Record<string, ReturnType<typeof ref<string>>> = {}
  const Content = defineComponent({ props: { id: { type: String, required: true } }, setup(props) {
    const text = ref('original')
    contents[props.id] = text
    onMounted(() => { mounts[props.id] = (mounts[props.id] || 0) + 1 })
    onUnmounted(() => unmounts.push(props.id))
    return () => h('p', text.value)
  } })
  const visible = ref(true)
  wrapper = mount(defineComponent({ setup: () => () => h(KeepAlive, null, { default: () => visible.value
    ? h(DockingWorkbenchLayout, {}, Object.fromEntries(['left', 'main', 'right', 'bottom'].map(id => [id, () => h(Content, { id })])))
    : h('div', 'OScode') }) }), { attachTo: document.body })
  await flushPromises()
  const layout = wrapper.findComponent(DockingWorkbenchLayout)
  const api = (layout.findComponent(DockviewVue).emitted('ready')![0][0] as DockviewReadyEvent).api
  expect(api.groups.every(group => group.header.hidden)).toBe(true)
  expect(mounts).toEqual({ left: 1, main: 1, right: 1, bottom: 1 })
  contents.main.value = 'unsaved editor state'
  const editor = api.getPanel('editor')!
  api.getPanel('inspector')!.api.moveTo({ group: editor.group, position: 'center' })
  await flushPromises()
  expect(editor.group.header.hidden).toBe(false)
  await layout.findAll('button').find(button => button.attributes('aria-label') === '隐藏 Inspector')!.trigger('click')
  expect(api.getPanel('inspector')!.api.isVisible).toBe(false)
  await layout.get('.docking-workbench__menu-trigger').trigger('click')
  await layout.findAll('[role="menuitemcheckbox"]').find(button => button.text().includes('Inspector'))!.trigger('click')
  expect(api.getPanel('inspector')!.api.isVisible).toBe(true)
  ;(layout.vm as any).resetLayout()
  await nextTick()
  expect(api.getPanel('editor')).toBe(editor)
  visible.value = false
  await nextTick()
  expect(localStorage.getItem(DOCK_STORAGE_KEY)).not.toBeNull()
  visible.value = true
  await flushPromises()
  expect(contents.main.value).toBe('unsaved editor state')
  expect(mounts).toEqual({ left: 1, main: 1, right: 1, bottom: 1 })
  expect(unmounts).toEqual([])
  wrapper.unmount()
  wrapper = undefined
  expect(unmounts.sort()).toEqual(['bottom', 'left', 'main', 'right'])
})

it('falls back to four panels for damaged state and preserves the original layout storage key', async () => {
  localStorage.setItem(DOCK_STORAGE_KEY, '{broken')
  localStorage.setItem('zhiyi.mission.workspace.layout.v3', 'original')
  wrapper = mount(DockingWorkbenchLayout)
  await flushPromises()
  const api = (wrapper.findComponent(DockviewVue).emitted('ready')![0][0] as DockviewReadyEvent).api
  expect(api.panels).toHaveLength(4)
  expect(localStorage.getItem('zhiyi.mission.workspace.layout.v3')).toBe('original')
  expect(wrapper.get('.docking-workbench__canvas').element.tagName).toBe('DIV')
  await wrapper.get('.docking-workbench__menu-trigger').trigger('click')
  await wrapper.findAll('[role="menuitemcheckbox"]').find(button => button.text() === '调整布局')!.trigger('click')
  expect(api.groups.every(group => !group.header.hidden)).toBe(true)
  await wrapper.findAll('[role="menuitemcheckbox"]').find(button => button.text() === '完成布局调整')!.trigger('click')
  expect(api.groups.every(group => group.header.hidden)).toBe(true)
})

it('puts the layout menu in the topbar host and removes it on unmount', async () => {
  const host = document.createElement('div')
  host.id = 'mission-workspace-layout-menu'
  document.body.append(host)
  wrapper = mount(DockingWorkbenchLayout, { attachTo: document.body })
  await flushPromises()
  expect(host.querySelector('button')?.textContent).toBe('布局')
  expect(wrapper.element.querySelector('.docking-workbench__toolbar')).toBeNull()
  ;(host.querySelector('button') as HTMLButtonElement).click()
  await nextTick()
  expect(host.querySelector('[role="menu"]')).not.toBeNull()
  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
  await nextTick()
  expect(host.querySelector('[role="menu"]')).toBeNull()
  wrapper.unmount(); wrapper = undefined
  expect(host.querySelector('button')).toBeNull()
  host.remove()
})
