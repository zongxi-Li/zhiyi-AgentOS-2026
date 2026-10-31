import { describe, expect, it } from 'vitest'
import { buildConversationLaunchRequest, buildWorkbenchLaunchRequest, type ConversationLaunchContext } from './request'
import { createNativeWorkbenchDraft, type PluginUiExtension } from '@/features/acg/workbench'

const context: ConversationLaunchContext = {
  goal: '发布工程', conversationId: 'conversation:local-draft', chatContextId: 'chat:server', chatRoleId: 'role:1',
  source: 'chat', messages: [{ role: 'user', content: '约束讨论' }]
}

describe('Mission request adapters', () => {
  it.each(['chat', 'agent'] as const)('normalizes %s semantics while preserving independent conversation identities and origin', source => {
    const request = buildConversationLaunchRequest({ ...context, source,
      execution: { thinkingMode: 'deep', reasoningEffort: 'high', webSearchEnabled: false },
      attachmentIds: ['attachment'], materialRefs: ['material'], sourceRefs: ['evidence']
    }, 'operation')
    expect(request.semantics).toEqual({ objective: '发布工程', constraints: [], sourceRefs: ['evidence'] })
    expect(request.input).toMatchObject({ source, userIntent: '发布工程', taskGoal: '发布工程',
      conversationId: 'conversation:local-draft', chatContextId: 'chat:server', chatRoleId: 'role:1',
      chatContext: [{ role: 'user', content: '约束讨论' }], thinkingMode: 'deep', reasoningEffort: 'high', webSearchEnabled: false })
    if (source === 'chat') expect(request.input).toMatchObject({ caseText: '发布工程', chatText: '发布工程' })
    expect(request.attachmentIds).toEqual(['attachment'])
    expect(request.materialRefs).toEqual(['material'])
    expect(request.clientRequestId).toBe('operation')
  })

  it('captures at most the last eight messages without mutating the source', () => {
    const messages = Array.from({ length: 10 }, (_, i) => ({ role: 'user', content: String(i) }))
    expect(buildConversationLaunchRequest({ ...context, messages }, 'op').input.chatContext.map(m => m.content))
      .toEqual(['2', '3', '4', '5', '6', '7', '8', '9'])
    expect(messages).toHaveLength(10)
  })

  it('reuses the Workbench builder, preserving advanced options and plugin contributions with user authority', () => {
    const draft = { ...createNativeWorkbenchDraft(), title: '工程', taskGoal: '正式目标', constraints: ['边界'],
      expectedArtifacts: ['交付'], materialIds: ['legacy-material'], enabledPluginIds: ['plugin'],
      planningMode: 'template_preferred' as const, planningDiversity: 'exploratory' as const,
      planningSeed: 42, capabilityProfile: 'full' as const, reasoningEffort: 'high',
      thinkingMode: 'deep' as const, webSearchEnabled: false, pluginData: { plugin: { enabled: true } } }
    const plugin: PluginUiExtension = { pluginId: 'plugin', displayName: 'plugin', buildStartRequest: () => ({
      domain: 'industrial', intent: 'design', workflowId: 'workflow', reviewMode: 'human_in_loop',
      clientRequestId: 'hijack', enabledPluginIds: ['escape'], input: { webSearchEnabled: true, pluginFact: true }
    }) }
    const request = buildWorkbenchLaunchRequest(draft, [plugin], 'user-operation', {
      attachmentIds: ['att'], materialRefs: ['sealed'], sourceRefs: ['ref'], input: { debugTrace: true, webSearchEnabled: true }
    })
    expect(request).toMatchObject({ title: '工程', domain: 'industrial', intent: 'design', workflowId: 'workflow',
      reviewMode: 'human_in_loop', enabledPluginIds: ['plugin'], clientRequestId: 'user-operation',
      attachmentIds: ['att'], materialRefs: ['sealed'],
      semantics: { objective: '正式目标', constraints: [{ constraintId: 'constraint-1', text: '边界', sourceRefs: [] }], sourceRefs: ['ref'] } })
    expect(request.input).toMatchObject({ taskGoal: '正式目标', constraints: ['边界'], expectedArtifacts: ['交付'],
      materialIds: ['legacy-material'], planningMode: 'template_preferred', planningDiversity: 'exploratory',
      planningSeed: 42, capabilityProfile: 'full', reasoningEffort: 'high', thinkingMode: 'deep',
      webSearchEnabled: false, pluginData: { plugin: { enabled: true } }, pluginFact: true, debugTrace: true })
  })
})
