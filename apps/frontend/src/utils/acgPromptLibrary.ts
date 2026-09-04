export interface AcgPromptTask {
  id: string
  group: string
  sourceHeading: string
  name: string
  materialText: string
  taskGoal: string
  constraints: string[]
  expectedArtifacts: string[]
}

type PromptField = 'name' | 'materialText' | 'taskGoal' | 'constraints' | 'expectedArtifacts'

interface MarkdownHeading {
  index: number
  level: number
  title: string
}

interface ParsedPromptTask {
  group: string
  sourceHeading: string
  name?: string
  materialText?: string
  taskGoal?: string
  constraints?: string[]
  expectedArtifacts?: string[]
}

const FIELD_NAMES: Record<string, PromptField> = {
  '任务名称': 'name',
  '文本材料': 'materialText',
  '任务目标': 'taskGoal',
  '执行约束': 'constraints',
  '预期交付物': 'expectedArtifacts'
}

const headingPattern = /^(#{2,6})\s+(.+?)\s*$/

const normalizeHeading = (title: string) => title
  .replace(/[`*_]/g, '')
  .replace(/[：:]\s*$/, '')
  .trim()

const fieldFromHeading = (title: string): PromptField | undefined => FIELD_NAMES[normalizeHeading(title)]

const splitList = (value: string): string[] => value
  .split(/[,，；;\n]+/)
  .map(item => item.trim())
  .filter(Boolean)

const readFieldValue = (lines: string[], start: number, end: number): string => {
  const fenceIndex = lines.findIndex((line, index) => index > start && index < end && line.trim().startsWith('```'))
  if (fenceIndex >= 0) {
    const content: string[] = []
    for (let index = fenceIndex + 1; index < end; index += 1) {
      if (lines[index].trim().startsWith('```')) break
      content.push(lines[index])
    }
    return content.join('\n').trim()
  }

  return lines.slice(start + 1, end).join('\n').trim()
}

const groupTitleFor = (headings: MarkdownHeading[], parentIndex: number): string => {
  const groupHeading = [...headings]
    .reverse()
    .find(heading => heading.index <= parentIndex && heading.level <= 2)
  return normalizeHeading(groupHeading?.title || 'ACG 提示词')
    .replace(/[（(]\d+个[）)]$/, '')
    .trim()
}

export const parseAcgPromptTasks = (markdown: string): AcgPromptTask[] => {
  const lines = markdown.replace(/\r\n?/g, '\n').split('\n')
  const headings: MarkdownHeading[] = []

  lines.forEach((line, index) => {
    const match = line.match(headingPattern)
    if (!match) return
    headings.push({ index, level: match[1].length, title: match[2] })
  })

  const tasks = new Map<number, ParsedPromptTask>()
  headings.forEach(heading => {
    const field = fieldFromHeading(heading.title)
    if (!field) return

    const parent = [...headings]
      .reverse()
      .find(candidate => candidate.index < heading.index && candidate.level < heading.level)
    if (!parent) return

    const nextBoundary = headings.find(candidate => candidate.index > heading.index && candidate.level <= heading.level)?.index ?? lines.length
    const value = readFieldValue(lines, heading.index, nextBoundary)
    if (!value) return

    const existing = tasks.get(parent.index) || {
      group: groupTitleFor(headings, parent.index),
      sourceHeading: normalizeHeading(parent.title)
    }
    if (field === 'constraints' || field === 'expectedArtifacts') existing[field] = splitList(value)
    else existing[field] = value
    tasks.set(parent.index, existing)
  })

  return [...tasks.entries()]
    .sort(([left], [right]) => left - right)
    .map(([headingIndex, task], index) => ({
      id: `prompt-task-${index + 1}-${headingIndex}`,
      group: task.group,
      sourceHeading: task.sourceHeading,
      name: task.name || '',
      materialText: task.materialText || '',
      taskGoal: task.taskGoal || '',
      constraints: task.constraints || [],
      expectedArtifacts: task.expectedArtifacts || []
    }))
    .filter(task => Boolean(task.name && (task.materialText || task.taskGoal)))
}
