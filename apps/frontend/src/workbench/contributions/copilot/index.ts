import { MagicStick } from '@element-plus/icons-vue'
import AcgCopilotPanel from '@/components/workbench/AcgCopilotPanel.vue'
import type { WorkbenchContribution } from '@/workbench/types'

export const copilotContribution: WorkbenchContribution = {
  id: 'acg-copilot',
  auxiliaryViews: [
    {
      id: 'acg-copilot.sidebar',
      title: 'ACG Copilot',
      order: 100,
      icon: MagicStick,
      component: AcgCopilotPanel,
      when: () => true
    }
  ]
}
