import type { AcgEdge, AcgNode } from '@/services/api/agentos'

/** Enhanced hierarchical layout with better spacing and visual clarity - Claude style */
export const executionLayout = (nodes: AcgNode[], edges: AcgEdge[]) => {
  const ordered = [...nodes].sort((a, b) =>
    (a.display?.displayOrder ?? nodes.indexOf(a)) - (b.display?.displayOrder ?? nodes.indexOf(b)))
  const adjacency = new Map(ordered.map(node => [node.nodeId, [] as string[]]))
  for (const edge of edges) {
    if (adjacency.has(edge.sourceId) && adjacency.has(edge.targetId)) adjacency.get(edge.sourceId)!.push(edge.targetId)
  }
  let index = 0
  const indices = new Map<string, number>()
  const low = new Map<string, number>()
  const stack: string[] = []
  const onStack = new Set<string>()
  const groups: string[][] = []
  const visit = (id: string) => {
    indices.set(id, index)
    low.set(id, index++)
    stack.push(id)
    onStack.add(id)
    for (const target of adjacency.get(id)!) {
      if (!indices.has(target)) {
        visit(target)
        low.set(id, Math.min(low.get(id)!, low.get(target)!))
      } else if (onStack.has(target)) low.set(id, Math.min(low.get(id)!, indices.get(target)!))
    }
    if (low.get(id) !== indices.get(id)) return
    const group: string[] = []
    let member: string
    do {
      member = stack.pop()!
      onStack.delete(member)
      group.push(member)
    } while (member !== id)
    groups.push(group)
  }
  for (const node of ordered) if (!indices.has(node.nodeId)) visit(node.nodeId)
  const groupById = new Map(groups.flatMap((group, i) => group.map(id => [id, i] as const)))
  const outgoing = groups.map(() => new Set<number>())
  const incoming = groups.map(() => 0)
  for (const edge of edges) {
    const source = groupById.get(edge.sourceId)
    const target = groupById.get(edge.targetId)
    if (source === undefined || target === undefined || source === target || outgoing[source]!.has(target)) continue
    outgoing[source]!.add(target)
    incoming[target]!++
  }
  const ranks = groups.map(() => 0)
  const queue = incoming.flatMap((count, i) => count === 0 ? [i] : [])
  for (let i = 0; i < queue.length; i++) {
    const source = queue[i]!
    for (const target of outgoing[source]!) {
      ranks[target] = Math.max(ranks[target]!, ranks[source]! + groups[source]!.length)
      if (--incoming[target]! === 0) queue.push(target)
    }
  }
  const columns = new Map<number, AcgNode[]>()
  const offsets = groups.map(() => 0)
  for (const node of ordered) {
    const group = groupById.get(node.nodeId)!
    const rank = ranks[group]! + offsets[group]!++
    if (!columns.has(rank)) columns.set(rank, [])
    columns.get(rank)!.push(node)
  }

  // Enhanced positioning with better spacing - Claude aesthetic
  const positions = new Map<string, { x: number; y: number }>()
  const columnWidth = 360  // Increased from 320 for more breathing room
  const rowHeight = 160    // Increased from 144 for better vertical spacing

  for (const [rank, column] of columns) {
    // Center-align nodes in each column with smooth vertical distribution
    const totalHeight = (column.length - 1) * rowHeight
    const startY = -totalHeight / 2

    column.forEach((node, row) => {
      positions.set(node.nodeId, {
        x: rank * columnWidth,
        y: startY + row * rowHeight
      })
    })
  }
  return positions
}

const labelLimit = 14
const labelLength = (text: string) => Array.from(text).length

/** 超长单词优先在下划线/连字符/驼峰边界断开，避免把 VERIFICATION_LOOP 切成残词 */
const breakLongToken = (token: string): string[] => {
  if (labelLength(token) <= labelLimit) return [token]
  const pieces = token.split(/(?<=[_-])|(?<=\p{Ll})(?=\p{Lu})/u).filter(Boolean)
  const soft: string[] = []
  let line = ''
  for (const piece of pieces) {
    if (line && labelLength(line + piece) > labelLimit) { soft.push(line); line = piece } else line += piece
  }
  if (line) soft.push(line)
  const hard: string[] = []
  for (const part of soft) {
    if (labelLength(part) <= labelLimit) { hard.push(part); continue }
    const chars = Array.from(part)
    for (let i = 0; i < chars.length; i += labelLimit) hard.push(chars.slice(i, i + labelLimit).join(''))
  }
  return hard
}

export const executionNodeLabel = (text: string) => {
  const words = text.replace(/\s+/g, ' ').trim().split(' ').filter(Boolean)
  const lines: string[] = []
  let current = ''
  for (const word of words) {
    const merged = current ? `${current} ${word}` : word
    if (labelLength(merged) <= labelLimit) { current = merged; continue }
    if (current) lines.push(current)
    const pieces = breakLongToken(word)
    lines.push(...pieces.slice(0, -1))
    current = pieces[pieces.length - 1] ?? ''
  }
  if (current) lines.push(current)
  if (lines.length <= 2) return lines.join('\n')
  const overflow = lines.slice(1).join(' ').trimEnd()
  return `${lines[0]}\n${Array.from(overflow).slice(0, labelLimit).join('')}…`
}
