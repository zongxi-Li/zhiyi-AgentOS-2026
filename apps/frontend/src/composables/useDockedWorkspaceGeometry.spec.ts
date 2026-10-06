import { defineComponent, h, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useDockedWorkspaceGeometry } from './useDockedWorkspaceGeometry'
import { useWorkbenchLayout } from './useWorkbenchLayout'

const hosts: Array<ReturnType<typeof mount>> = []
const mountGeometry = () => {
  let geometry!: ReturnType<typeof useDockedWorkspaceGeometry>
  const host = mount(defineComponent({ setup() {
    geometry = useDockedWorkspaceGeometry()
    return () => h('div')
  } }))
  hosts.push(host)
  return { geometry, host }
}

describe('shared dock geometry', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => { hosts.splice(0).forEach(host => host.unmount()) })

  it('keeps the shell aligned and restores widths after a page is replaced', () => {
    const shell = mountGeometry()
    const chat = mountGeometry()
    chat.geometry.persist({ rightWidth: 416 })
    shell.geometry.persist({ leftWidth: 360 })
    expect(chat.geometry.leftWidth.value).toBe(360)
    expect(shell.geometry.rightWidth.value).toBe(416)
    chat.host.unmount()
    hosts.splice(hosts.indexOf(chat.host), 1)
    const workspace = mountGeometry()
    expect(workspace.geometry.leftWidth.value).toBe(360)
    expect(workspace.geometry.rightWidth.value).toBe(416)
    workspace.geometry.persist({ rightWidth: 384 })
    expect(shell.geometry.leftWidth.value).toBe(360)
    expect(shell.geometry.rightWidth.value).toBe(384)
  })

  it('keeps shared panes visible at minimum widths while allowing explicit collapse', async () => {
    const shell = mountGeometry()
    let layout!: ReturnType<typeof useWorkbenchLayout>
    hosts.push(mount(defineComponent({ setup() {
      layout = useWorkbenchLayout({ sharedDockGeometry: true, right: { minWidth: 280, defaultWidth: 320 } })
      return () => h('div', { ref: layout.containerRef })
    } })))
    shell.geometry.persist({ leftWidth: 240, rightWidth: 280 })
    await nextTick()
    expect(layout.leftPaneWidth.value).toBe(240)
    expect(layout.rightPaneWidth.value).toBe(280)
    expect(layout.leftPaneVisible.value).toBe(true)
    expect(layout.rightPaneVisible.value).toBe(true)
    layout.toggleRightPane()
    expect(layout.rightPaneVisible.value).toBe(false)
    layout.toggleRightPane()
    expect(layout.rightPaneVisible.value).toBe(true)
  })
})
