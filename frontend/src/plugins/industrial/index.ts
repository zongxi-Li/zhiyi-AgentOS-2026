import type { PluginUiExtension } from '@/features/acg/workbench'

const DEFAULT_ARTIFACTS = [
  '工业实施方案主报告',
  '产能与节拍计算表',
  '工位及设备清单',
  'OT/IT 架构与数据流图',
  '安全风险与验收矩阵'
]

export const industrialUiExtension: PluginUiExtension = {
  pluginId: 'industrial',
  displayName: '工业设计能力包',
  createDefaults: () => ({
    title: '智能制造产线工业设计',
    taskGoal: '形成可计算、可追溯、可验证的完整工业实施方案，并明确假设、证据缺口与验收边界。',
    expectedArtifacts: [...DEFAULT_ARTIFACTS],
    capabilityProfile: 'full',
    planningDiversity: 'exploratory',
    webSearchEnabled: true,
    reviewMode: 'human_in_loop',
    pluginData: { industrial: { evidenceFirst: true, maxRevisions: 2 } }
  }),
  buildStartRequest: () => ({
    domain: 'industrial',
    intent: 'industrial_design',
    workflowId: 'industrial_design_v1',
    reviewMode: 'human_in_loop',
    input: {
      planningMode: 'dynamic',
      industrialDesign: true,
      verificationMaxRevisions: 2
    }
  })
}
