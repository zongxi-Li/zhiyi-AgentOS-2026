import { expect, it } from 'vitest'
import { highlightCode, languageForFile } from './syntaxHighlight'

it('maps workspace files to the matching highlight language', () => {
  expect(languageForFile('main.py')).toBe('python')
  expect(languageForFile('C:\\ws\\src\\App.Vue')).toBe('xml')
  expect(languageForFile('Dockerfile')).toBe('bash')
  expect(languageForFile('README.md')).toBe('markdown')
  expect(languageForFile('.gitignore')).toBeNull()
  expect(languageForFile('graph.acg')).toBeNull()
  expect(languageForFile('')).toBeNull()
})

it('escapes source and marks python tokens', async () => {
  const html = await highlightCode('def solve():\n    return "<unsafe>"\n', 'main.py')
  expect(html).toContain('hljs-keyword')
  expect(html).not.toContain('<unsafe>')
  expect(html).toContain('&quot;&lt;unsafe&gt;&quot;')
})

it('falls back to plain text for unknown or oversized files', async () => {
  expect(await highlightCode('node a -> b', 'graph.acg')).toBeNull()
  expect(await highlightCode('x'.repeat(200_001), 'main.py')).toBeNull()
})
