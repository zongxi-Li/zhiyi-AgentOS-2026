import { h } from 'vue'
import { ElMessageBox } from 'element-plus'

export type FailedRunRetryMode = 'successor_run' | 'current_run'

export const chooseFailedRunRetryMode = async (runId: string): Promise<FailedRunRetryMode | null> => {
  try {
    await ElMessageBox.confirm(
      h('div', { class: 'retry-mode-choice' }, [
        h('p', '已完成节点都会复用，只重新执行失败节点及其未完成下游。'),
        h('div', { class: 'retry-mode-choice__option' }, [
          h('strong', '创建新 Run（推荐）'),
          h('span', '保留失败现场，生成新的 Run ID，便于比较和回退。')
        ]),
        h('div', { class: 'retry-mode-choice__option retry-mode-choice__option--mutating' }, [
          h('strong', '在当前 Run 上重试'),
          h('span', `继续使用 ${runId}，追加新的节点 Attempt，当前 Run 将从失败状态重新进入执行。`)
        ])
      ]),
      '选择恢复方式',
      {
        confirmButtonText: '创建新 Run',
        cancelButtonText: '当前 Run 重试',
        distinguishCancelAndClose: true,
        closeOnClickModal: false,
        customClass: 'retry-mode-dialog'
      }
    )
    return 'successor_run'
  } catch (action) {
    return action === 'cancel' ? 'current_run' : null
  }
}
