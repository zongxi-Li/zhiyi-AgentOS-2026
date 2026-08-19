const DEFAULT_ACG_TASK_TITLE = '未命名 ACG 任务'

type AcgTaskTitleSource = {
  title?: string | null
  workflowId?: string | null
  input?: Record<string, unknown> | null
}

type AcgTaskTitleAutoUpdate = {
  currentTitle: string
  previousAutoTitle: string
  taskGoal: string
  defaultTitle: string
}

const compactWhitespace = (value: string) => value.replace(/\s+/g, ' ').trim()

const stripLegacyChatPrefix = (value: string) => value
  .replace(/^(?:lawyer|writer|teacher|programmer)\s+agent\s+chat\s*[:：-]?\s*/i, '')
  .replace(/^【任务材料】\s*/, '')
  .trim()

const concisePartyName = (value: string) => value
  .replace(/(?:有限责任公司|股份有限公司|有限公司)$/u, '')
  .trim()

const inferLegacyTaskTitle = (value: string): string => {
  const candidate = stripLegacyChatPrefix(value)
  if (!candidate) return ''

  const parties = candidate.match(/甲方[：:]\s*([^\s，。；：]{2,24})\s+乙方[：:]\s*([^\s，。；：]{2,24})/u)
  if (parties) {
    const partyA = concisePartyName(parties[1])
    const partyB = concisePartyName(parties[2])
    if (partyA && partyB) return `${partyA}与${partyB}合同审查`.slice(0, 30)
  }

  const typedContract = candidate.match(
    /(?:[：:]\s*)?((?:软件开发|采购|销售|劳动|服务|租赁|保密|合作|技术|建设工程|委托|股权|数据处理|许可)[\u4e00-\u9fa5]{0,4}(?:合同|协议))/u
  )
  if (typedContract && /(审查|复核|分析|风险)/u.test(candidate)) return `${typedContract[1]}审查`

  const objectMatch = candidate.match(/(审查|复核|分析)(?:这份|该份|本份|该|本)?([^，。；：:\n]{2,24}?(?:合同|协议|材料|文档|数据|项目))/u)
  if (objectMatch) return `${objectMatch[2]}${objectMatch[1]}`

  const firstClause = candidate.split(/[，。；：:\n]/, 1)[0]
    .replace(/^请(?:以[^，。；]{0,24})?/, '')
    .replace(/^执行/, '')
    .trim()
  if (!firstClause || /^(?:合同)?审查工作流$/u.test(firstClause)) return ''
  return firstClause.length > 30 ? `${firstClause.slice(0, 30)}…` : firstClause
}

export const resolveAcgTaskTitle = ({ title, workflowId, input }: AcgTaskTitleSource): string => {
  const explicitName = typeof input?.taskName === 'string' ? compactWhitespace(input.taskName) : ''
  if (explicitName) return explicitName.slice(0, 80)

  const rawCandidate = compactWhitespace(title || '')
  const candidate = stripLegacyChatPrefix(rawCandidate)
  const inferredTitle = inferLegacyTaskTitle(rawCandidate)
  if (rawCandidate !== candidate && inferredTitle) return inferredTitle

  const looksLikeWorkflowCommand = /^(?:请)?(?:执行)?(?:合同)?审查工作流/u.test(candidate)
  if (candidate && candidate.length <= 36 && !looksLikeWorkflowCommand) return candidate

  if (candidate) {
    if (inferredTitle) return inferredTitle
  }

  return workflowId || DEFAULT_ACG_TASK_TITLE
}

export const resolveAcgTaskTitleAutoUpdate = ({
  currentTitle,
  previousAutoTitle,
  taskGoal,
  defaultTitle
}: AcgTaskTitleAutoUpdate): { title: string; autoTitle: string } => {
  const normalizedCurrent = compactWhitespace(currentTitle)
  const normalizedPreviousAuto = compactWhitespace(previousAutoTitle)
  const canReplace = !normalizedCurrent
    || normalizedCurrent === compactWhitespace(defaultTitle)
    || (Boolean(normalizedPreviousAuto) && normalizedCurrent === normalizedPreviousAuto)

  if (!canReplace) {
    return { title: currentTitle, autoTitle: previousAutoTitle }
  }

  if (!compactWhitespace(taskGoal)) {
    return { title: '', autoTitle: '' }
  }

  const inferred = resolveAcgTaskTitle({ title: taskGoal })
  return { title: inferred, autoTitle: inferred }
}
