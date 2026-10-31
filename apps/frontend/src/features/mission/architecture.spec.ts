import { readdirSync, readFileSync } from 'node:fs'
import { resolve, relative } from 'node:path'
import { expect, it } from 'vitest'

const root = resolve('src')
const files = (directory: string): string[] => readdirSync(directory, { withFileTypes: true }).flatMap(entry =>
  entry.isDirectory() ? files(resolve(directory, entry.name)) : /\.(ts|vue)$/.test(entry.name) && !entry.name.endsWith('.spec.ts') ? [resolve(directory, entry.name)] : [])
const source = files(root).map(path => ({ path: relative(root, path).replace(/\\/g, '/'), text: readFileSync(path, 'utf8') }))

it('restricts all initial Mission API submission to the service and low-level API facade', () => {
  const allowed = new Set(['features/mission/launch.ts', 'services/api/workflow.ts', 'services/api/agentos/api/mission.ts'])
  expect(source.filter(file => /\.(startWorkflowAsync|startWorkflow)\s*\(/.test(file.text) && !allowed.has(file.path)).map(file => file.path)).toEqual([])
  expect(source.filter(file => /\.post(?:<[^\n]+>)?\(\s*['"]\/missions['"]/.test(file.text) && file.path !== 'services/api/agentos/api/mission.ts').map(file => file.path)).toEqual([])
})
it('admits raw service capabilities only through LaunchAttempt, and core construction only through adapters/compatibility builder', () => {
  expect(source.filter(file => /import.*prepareMissionLaunch\b/.test(file.text) && file.path !== 'features/mission/launchAttempt.ts').map(file => file.path)).toEqual([])
  expect(source.filter(file => /import.*\blaunchMission\b/.test(file.text) && file.path !== 'features/mission/launchAttempt.ts').map(file => file.path)).toEqual([])
  expect(source.filter(file => /restoreMissionLaunchCommand\(/.test(file.text) && !['features/mission/command.ts', 'features/mission/launchAttempt.ts'].includes(file.path)).map(file => file.path)).toEqual([])
  expect(source.filter(file => /buildWorkbenchStartRequest\(/.test(file.text) && !['features/acg/workbench.ts', 'features/mission/request.ts', 'views/AcgVisualizationView.vue'].includes(file.path)).map(file => file.path)).toEqual([])
  expect(source.filter(file => /buildConversationLaunchRequest\(/.test(file.text) && !['features/mission/command.ts', 'features/mission/request.ts'].includes(file.path)).map(file => file.path)).toEqual([])
})
it('keeps persistent launch identity and policy defaults out of business components', () => {
  const business = source.filter(file => /^(views|stores)\//.test(file.path))
  expect(business.filter(file => /mission\.launch\.(request|attempt)|chat\.workflow_submission|creationRetry|conversationLaunchRequestId|clearConversationLaunchIdentity/.test(file.text)).map(file => file.path)).toEqual([])
  expect(business.filter(file => /(?:domain|intent|reviewMode)\s*:\s*(?:options\.)?\w+\s*\|\||'legal'\s*,\s*intent\s*:\s*'case_analysis'/.test(file.text)).map(file => file.path)).toEqual([])
  expect(source.find(file => file.path === 'views/ChatView.vue')!.text).not.toMatch(/domain:\s*'general'|reviewMode:\s*'auto'/)
})
