/**
 * CodeMirror 6 的工作台主题：颜色全部取自现有 CSS 变量，
 * 和文件树 / 标签 / 状态栏共用同一套 `--wb-*`、`--sem-*` 色板。
 */
import { EditorView } from '@codemirror/view'
import { HighlightStyle } from '@codemirror/language'
import { tags } from '@lezer/highlight'

export const workbenchEditorTheme = EditorView.theme({
  '&': {
    height: '100%',
    backgroundColor: 'transparent',
    color: 'var(--wb-text)',
    fontSize: '13px',
    fontFamily: 'var(--font-mono, Consolas, monospace)'
  },
  '&.cm-focused': { outline: 'none' },
  '.cm-scroller': { fontFamily: 'inherit', lineHeight: '22px', overflow: 'auto' },
  '.cm-content': { padding: '14px 0', caretColor: 'var(--wb-accent)' },
  '.cm-line': { padding: '0 16px' },
  '.cm-gutters': { backgroundColor: 'transparent', color: 'var(--wb-text-muted)', border: 'none' },
  '.cm-lineNumbers .cm-gutterElement': { padding: '0 8px 0 16px', minWidth: '44px' },
  '.cm-activeLine': { backgroundColor: 'color-mix(in srgb, var(--wb-accent) 7%, transparent)' },
  '.cm-activeLineGutter': {
    backgroundColor: 'color-mix(in srgb, var(--wb-accent) 7%, transparent)',
    color: 'var(--wb-text-secondary)'
  },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--wb-accent)', borderLeftWidth: '2px' },
  '&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection': {
    backgroundColor: 'color-mix(in srgb, var(--wb-accent) 28%, transparent)'
  },
  '.cm-selectionMatch': { backgroundColor: 'color-mix(in srgb, var(--sem-artifact) 22%, transparent)' },
  '.cm-searchMatch': {
    backgroundColor: 'color-mix(in srgb, var(--sem-waiting) 26%, transparent)',
    outline: '1px solid color-mix(in srgb, var(--sem-waiting) 45%, transparent)'
  },
  '.cm-searchMatch.cm-searchMatch-selected': {
    backgroundColor: 'color-mix(in srgb, var(--sem-waiting) 46%, transparent)'
  },
  '.cm-matchingBracket, .cm-nonmatchingBracket': {
    backgroundColor: 'color-mix(in srgb, var(--sem-flow) 22%, transparent)',
    outline: '1px solid color-mix(in srgb, var(--sem-flow) 45%, transparent)'
  },
  '.cm-foldPlaceholder': {
    backgroundColor: 'var(--wb-surface-1)',
    border: '1px solid var(--wb-border)',
    color: 'var(--wb-text-secondary)',
    padding: '0 6px',
    borderRadius: '4px'
  },
  '.cm-panels': { backgroundColor: 'var(--wb-surface-1)', color: 'var(--wb-text)' },
  '.cm-panels.cm-panels-top': { borderBottom: '1px solid var(--wb-border)' },
  '.cm-panel.cm-search': { padding: '6px 10px', fontFamily: 'var(--font-sans, inherit)', fontSize: '12px' },
  '.cm-textfield': {
    backgroundColor: 'var(--wb-surface-inset, #161616)',
    border: '1px solid var(--wb-border-strong)',
    color: 'var(--wb-text)',
    borderRadius: '4px',
    padding: '2px 6px'
  },
  '.cm-button': {
    backgroundImage: 'none',
    backgroundColor: 'var(--wb-surface-1)',
    border: '1px solid var(--wb-border-strong)',
    color: 'var(--wb-text)',
    borderRadius: '4px',
    fontSize: '12px'
  },
  '.cm-tooltip': {
    backgroundColor: 'var(--wb-surface-1)',
    border: '1px solid var(--wb-border)',
    color: 'var(--wb-text)'
  }
}, { dark: true })

export const workbenchHighlightStyle = HighlightStyle.define([
  { tag: [tags.comment, tags.lineComment, tags.blockComment, tags.docComment], color: 'var(--wb-text-muted)', fontStyle: 'italic' },
  {
    tag: [
      tags.keyword,
      tags.controlKeyword,
      tags.definitionKeyword,
      tags.moduleKeyword,
      tags.operatorKeyword,
      tags.self,
      tags.null,
      tags.atom
    ],
    color: 'var(--sem-artifact)'
  },
  { tag: [tags.string, tags.special(tags.string), tags.regexp, tags.character], color: 'var(--sem-success)' },
  { tag: [tags.number, tags.bool, tags.unit, tags.literal], color: 'var(--sem-retry)' },
  {
    tag: [tags.function(tags.variableName), tags.function(tags.propertyName), tags.definition(tags.variableName), tags.macroName],
    color: 'var(--wb-accent)'
  },
  {
    tag: [tags.typeName, tags.className, tags.namespace, tags.tagName, tags.standard(tags.name)],
    color: 'var(--sem-flow)'
  },
  { tag: [tags.annotation, tags.meta], color: 'var(--sem-waiting)' },
  { tag: [tags.propertyName, tags.attributeName, tags.definition(tags.propertyName)], color: 'var(--wb-text)' },
  { tag: [tags.operator, tags.punctuation, tags.bracket], color: 'var(--wb-text-secondary)' },
  { tag: [tags.heading], color: 'var(--wb-accent)', fontWeight: '600' },
  { tag: [tags.strong], color: 'var(--wb-text)', fontWeight: '600' },
  { tag: [tags.emphasis], color: 'var(--wb-text-secondary)', fontStyle: 'italic' },
  { tag: [tags.link, tags.url], color: 'var(--wb-accent)', textDecoration: 'underline' },
  { tag: [tags.invalid], color: 'var(--sem-failed)' }
])
