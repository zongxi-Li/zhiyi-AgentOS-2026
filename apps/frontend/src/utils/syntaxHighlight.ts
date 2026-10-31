/**
 * 工作区文件的只读语法着色：按文件名映射 highlight.js 语言，输出已转义的 HTML。
 * 引擎体积不小，只在确实需要着色时动态加载一次；未知扩展名或超大文件返回 null，
 * 由调用方回退到纯文本，避免为了着色拖慢打开速度。
 */
const MAX_HIGHLIGHT_CHARS = 200_000

/** 工作区里常见的文本格式 → highlight.js 语言名。 */
const LANGUAGE_BY_EXTENSION: Record<string, string> = {
  py: 'python',
  pyi: 'python',
  pyw: 'python',
  js: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  jsx: 'javascript',
  ts: 'typescript',
  tsx: 'typescript',
  vue: 'xml',
  json: 'json',
  jsonc: 'json',
  json5: 'json',
  md: 'markdown',
  markdown: 'markdown',
  mdx: 'markdown',
  html: 'xml',
  htm: 'xml',
  xhtml: 'xml',
  xml: 'xml',
  svg: 'xml',
  css: 'css',
  scss: 'scss',
  less: 'less',
  sh: 'bash',
  bash: 'bash',
  zsh: 'bash',
  fish: 'bash',
  ps1: 'bash',
  bat: 'bash',
  cmd: 'bash',
  yml: 'yaml',
  yaml: 'yaml',
  toml: 'ini',
  ini: 'ini',
  cfg: 'ini',
  conf: 'ini',
  env: 'ini',
  properties: 'ini',
  java: 'java',
  kt: 'kotlin',
  kts: 'kotlin',
  go: 'go',
  rs: 'rust',
  rb: 'ruby',
  php: 'php',
  graphql: 'graphql',
  gql: 'graphql',
  vb: 'vbnet',
  mm: 'objectivec',
  c: 'c',
  h: 'cpp',
  cc: 'cpp',
  cpp: 'cpp',
  cxx: 'cpp',
  hpp: 'cpp',
  cs: 'csharp',
  swift: 'swift',
  sql: 'sql',
  r: 'r',
  lua: 'lua',
  pl: 'perl',
  diff: 'diff',
  patch: 'diff',
  dockerfile: 'bash',
  makefile: 'makefile',
  mk: 'makefile',
}

/** 没有扩展名、但一眼能认出来的文件。 */
const LANGUAGE_BY_NAME: Record<string, string> = {
  dockerfile: 'bash',
  makefile: 'makefile',
  'cmakelists.txt': 'makefile',
  gemfile: 'ruby',
  rakefile: 'ruby',
}

export const languageForFile = (name: string): string | null => {
  const base = (name || '').split(/[\\/]/).pop()?.trim().toLowerCase() || ''
  if (!base) return null
  const known = LANGUAGE_BY_NAME[base]
  if (known) return known
  const dot = base.lastIndexOf('.')
  // dot <= 0：没有扩展名，或 ".gitignore" 这类以点开头的文件名。
  if (dot <= 0 || dot === base.length - 1) return null
  return LANGUAGE_BY_EXTENSION[base.slice(dot + 1)] || null
}

type HighlightEngine = (typeof import('highlight.js/lib/common'))['default']

let engine: Promise<HighlightEngine | null> | undefined

const loadEngine = (): Promise<HighlightEngine | null> => {
  engine ??= import('highlight.js/lib/common')
    .then(module => module.default)
    .catch(() => null)
  return engine
}

/** 返回可直接 v-html 的高亮 HTML；不支持的文件返回 null。 */
export const highlightCode = async (code: string, fileName: string): Promise<string | null> => {
  if (!code || code.length > MAX_HIGHLIGHT_CHARS) return null
  const language = languageForFile(fileName)
  if (!language) return null
  const hljs = await loadEngine()
  if (!hljs?.getLanguage(language)) return null
  try {
    return hljs.highlight(code, { language, ignoreIllegals: true }).value
  } catch {
    return null
  }
}
