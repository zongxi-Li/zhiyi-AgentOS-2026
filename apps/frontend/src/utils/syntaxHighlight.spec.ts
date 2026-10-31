import { expect, it } from 'vitest'
import { highlightCode, languageForFile } from './syntaxHighlight'

it('maps workspace files to the matching highlight language', () => {
  expect(languageForFile('main.py')).toBe('python')
  expect(languageForFile('C:\\ws\\src\\App.Vue')).toBe('xml')
  expect(languageForFile('Dockerfile')).toBe('bash')
  expect(languageForFile('README.md')).toBe('markdown')
  expect(languageForFile('AppConfig.java')).toBe('java')
  expect(languageForFile('build.gradle.kts')).toBe('kotlin')
  expect(languageForFile('schema.graphql')).toBe('graphql')
  expect(languageForFile('.gitignore')).toBeNull()
  expect(languageForFile('graph.acg')).toBeNull()
  expect(languageForFile('')).toBeNull()
})

it('highlights java sources', async () => {
  const html = await highlightCode('package a.b;\n\n@Configuration\npublic class AppConfig {\n  private int port = 8080;\n}\n', 'AppConfig.java')
  expect(html).toContain('hljs-keyword')
  expect(html).toContain('hljs-meta')
  expect(html).toContain('hljs-number')
})

it('covers every language the bundled engine ships', async () => {
  // 引擎用 highlight.js 的 common 包：这里锁住「映射表 ⊇ 引擎语言集」，
  // 避免以后换扩展名或换引擎时悄悄退化成纯文本。
  const { default: hljs } = await import('highlight.js/lib/common')
  const { languageForFile: resolve } = await import('./syntaxHighlight')
  const samples: Record<string, string> = {
    java: 'App.java', kotlin: 'App.kt', swift: 'App.swift', csharp: 'App.cs',
    go: 'main.go', rust: 'main.rs', ruby: 'app.rb', php: 'index.php',
    c: 'main.c', cpp: 'main.cpp', sql: 'schema.sql', r: 'plot.r',
    lua: 'init.lua', perl: 'script.pl', diff: 'change.diff', bash: 'run.sh',
    yaml: 'config.yaml', ini: 'app.ini', xml: 'layout.xml', css: 'style.css',
    scss: 'style.scss', less: 'style.less', json: 'package.json',
    markdown: 'README.md', python: 'main.py', javascript: 'app.js', typescript: 'app.ts',
    graphql: 'schema.graphql', vbnet: 'Module.vb', objectivec: 'App.mm',
    makefile: 'Makefile'
  }
  for (const [language, file] of Object.entries(samples)) {
    expect(hljs.getLanguage(language), language).toBeTruthy()
    expect(resolve(file), file).toBe(language)
  }
  // 没有独立语言支持的容器文件走近似语言，避免退化成纯文本。
  expect(resolve('Dockerfile')).toBe('bash')
  expect(resolve('App.vue')).toBe('xml')
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
