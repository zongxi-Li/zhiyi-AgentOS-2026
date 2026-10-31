import { defineComponent, h, KeepAlive, nextTick, ref } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { EditorView } from '@codemirror/view'
import { afterEach, expect, it, vi } from 'vitest'
import WorkspaceCodeEditor from './WorkspaceCodeEditor.vue'
import { TextDocument } from '@/workbench/core/documents'
import { lspClose, lspDiagnostics, lspOpen } from '@/services/lsp'

vi.mock('@/services/lsp', async original => ({ ...await original<any>(),
  lspAvailable: () => true, lspOpen: vi.fn(async () => ({ languageId: 'plaintext' })),
  lspClose: vi.fn(async () => {}), lspDiagnostics: vi.fn(async () => []), lspChange: vi.fn(async () => {})
}))
const rangeRectDescriptors = ['getClientRects', 'getBoundingClientRect'].map(key => [key, Object.getOwnPropertyDescriptor(Range.prototype, key)] as const)
afterEach(() => {
  vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals()
  for (const [key, descriptor] of rangeRectDescriptors) {
    if (descriptor) Object.defineProperty(Range.prototype, key, descriptor)
    else delete (Range.prototype as any)[key]
  }
})

it('keeps the real CodeMirror document, cursor and view while pausing hidden diagnostics', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('ResizeObserver', class { observe() {}; unobserve() {}; disconnect() {} })
  // jsdom has no text layout engine; provide the browser geometry API, keeping
  // the actual EditorView, selection, document and lifecycle code under test.
  const rect = { left: 0, top: 0, right: 500, bottom: 200, width: 500, height: 200, x: 0, y: 0, toJSON() {} }
  Object.defineProperty(Range.prototype, 'getClientRects', { configurable: true, value: () => [] })
  Object.defineProperty(Range.prototype, 'getBoundingClientRect', { configurable: true, value: () => rect })
  const visible = ref(true), document = new TextDocument('file:editor', 'first\nsecond', 'v1')
  const host = defineComponent({ setup: () => () => h(KeepAlive, null, { default: () => visible.value
    ? h(WorkspaceCodeEditor, { document, fileName: 'notes.txt', filePath: 'notes.txt', workspaceRoot: '/workspace' }) : null }) })
  const wrapper = mount(host, { attachTo: globalThis.document.body })
  try {
    await flushPromises(); await vi.advanceTimersByTimeAsync(1000)
    const editor = EditorView.findFromDOM(wrapper.get('.cm-editor').element as HTMLElement)!
    editor.dispatch({ changes: { from: 0, to: 5, insert: 'dirty' }, selection: { anchor: 8 } })
    await vi.advanceTimersByTimeAsync(1000)
    expect(document.dirty).toBe(true)
    const reads = vi.mocked(lspDiagnostics).mock.calls.length
    visible.value = false; await nextTick(); await vi.advanceTimersByTimeAsync(6000)
    expect(lspDiagnostics).toHaveBeenCalledTimes(reads)
    visible.value = true; await nextTick(); await flushPromises()
    expect(EditorView.findFromDOM(wrapper.get('.cm-editor').element as HTMLElement) === editor).toBe(true)
    expect(editor.state.selection.main.anchor).toBe(8)
    expect(editor.state.doc.toString()).toBe('dirty\nsecond')
    expect(lspOpen).toHaveBeenCalledTimes(1); expect(lspClose).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(2500)
    expect(vi.mocked(lspDiagnostics).mock.calls.length).toBeGreaterThan(reads)
  } finally { wrapper.unmount() }
  expect(lspClose).toHaveBeenCalledTimes(1)
})
