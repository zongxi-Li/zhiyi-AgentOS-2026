import { EditorState } from '@codemirror/state'
import { expect, it } from 'vitest'
import { toDiagnostics } from './lsp'
import type { LspDiagnosticItem } from '@/services/lsp'

const stateOf = () => EditorState.create({ doc: 'const a = 1\nsecond line\n' })

const item = (overrides: Partial<LspDiagnosticItem>): LspDiagnosticItem => ({
  path: 'a.ts',
  line: 1,
  column: 7,
  severity: 'error',
  message: 'boom',
  source: 'typescript',
  ...overrides
})

it('maps LSP diagnostics to CodeMirror ranges and filters by path', () => {
  const state = stateOf()
  const diagnostics = toDiagnostics(state, [
    item({}),
    item({ path: 'b.ts', message: 'other file' }),
    item({ line: 2, column: 1, message: 'second line' })
  ], 'a.ts')

  expect(diagnostics).toHaveLength(2)
  expect(diagnostics[0]).toMatchObject({ from: 6, to: 7, severity: 'error', message: 'boom', source: 'typescript' })
  expect(diagnostics[1].from).toBe(state.doc.line(2).from)
})

it('clamps out-of-range positions to the document bounds', () => {
  const state = stateOf()
  const [diagnostic] = toDiagnostics(state, [item({ line: 99, column: 99 })], 'a.ts')
  expect(diagnostic.from).toBe(state.doc.length)
  expect(diagnostic.to).toBe(state.doc.length)
})

it('keeps severity and message untouched', () => {
  const [diagnostic] = toDiagnostics(stateOf(), [
    item({ severity: 'warning', message: 'careful', source: 'eslint' })
  ], 'a.ts')
  expect(diagnostic).toMatchObject({ severity: 'warning', message: 'careful', source: 'eslint' })
})
