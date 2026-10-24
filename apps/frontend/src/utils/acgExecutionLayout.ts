import type { AcgEdge, AcgNode } from '@/services/api/agentos'

const COLUMN_GAP = 420
const ROW_GAP = 160

/**
 * Stable layered execution layout. SCCs bound feedback loops; virtual vertices
 * let long dependencies participate in crossing minimization. Parent task IDs
 * are layout hints only: they never introduce dependencies or execution stages.
 */
export const executionLayout = (
  nodes: AcgNode[], edges: AcgEdge[], parentByNode: ReadonlyMap<string, string> = new Map()
) => {
  const ordered = nodes.map((node, index) => ({ node, index })).sort((a, b) =>
    (a.node.display?.displayOrder ?? a.index) - (b.node.display?.displayOrder ?? b.index)
    || a.index - b.index).map(({ node }) => node.nodeId)
  const order = new Map(ordered.map((id, index) => [id, index]))
  const outgoing = new Map(ordered.map(id => [id, new Set<string>()]))
  const undirected = new Map(ordered.map(id => [id, new Set<string>()]))
  for (const edge of edges) {
    if (!outgoing.has(edge.sourceId) || !outgoing.has(edge.targetId) || edge.sourceId === edge.targetId) continue
    outgoing.get(edge.sourceId)!.add(edge.targetId)
    undirected.get(edge.sourceId)!.add(edge.targetId)
    undirected.get(edge.targetId)!.add(edge.sourceId)
  }

  // Collapse strongly connected components before assigning dependency ranks.
  let nextIndex = 0
  const indices = new Map<string, number>(), low = new Map<string, number>()
  const stack: string[] = [], active = new Set<string>(), groups: string[][] = []
  const visit = (id: string) => {
    indices.set(id, nextIndex); low.set(id, nextIndex++)
    stack.push(id); active.add(id)
    for (const target of outgoing.get(id)!) {
      if (!indices.has(target)) {
        visit(target)
        low.set(id, Math.min(low.get(id)!, low.get(target)!))
      } else if (active.has(target)) low.set(id, Math.min(low.get(id)!, indices.get(target)!))
    }
    if (low.get(id) !== indices.get(id)) return
    const group: string[] = []
    let member: string
    do { member = stack.pop()!; active.delete(member); group.push(member) } while (member !== id)
    groups.push(group.sort((a, b) => order.get(a)! - order.get(b)!))
  }
  ordered.forEach(id => { if (!indices.has(id)) visit(id) })
  const groupById = new Map(groups.flatMap((group, i) => group.map(id => [id, i] as const)))
  const successors = groups.map(() => new Set<number>()), incoming = groups.map(() => 0)
  for (const [source, targets] of outgoing) for (const target of targets) {
    const a = groupById.get(source)!, b = groupById.get(target)!
    if (a !== b && !successors[a]!.has(b)) { successors[a]!.add(b); incoming[b]!++ }
  }
  const groupRanks = groups.map(() => 0)
  const queue = incoming.flatMap((count, i) => count === 0 ? [i] : [])
  for (let i = 0; i < queue.length; i++) {
    const source = queue[i]!
    for (const target of successors[source]!) {
      groupRanks[target] = Math.max(groupRanks[target]!, groupRanks[source]! + groups[source]!.length)
      if (--incoming[target]! === 0) queue.push(target)
    }
  }
  const rank = new Map(groups.flatMap((group, i) => group.map((id, j) => [id, groupRanks[i]! + j] as const)))

  // Independent components occupy separate horizontal bands, including isolated nodes.
  const components: string[][] = [], seen = new Set<string>()
  for (const id of ordered) {
    if (seen.has(id)) continue
    const component = [id]; seen.add(id)
    for (let i = 0; i < component.length; i++) for (const peer of undirected.get(component[i]!)!) {
      if (!seen.has(peer)) { seen.add(peer); component.push(peer) }
    }
    components.push(component.sort((a, b) => order.get(a)! - order.get(b)!))
  }
  const positions = new Map<string, { x: number; y: number }>()
  let bandTop = 0
  for (const component of components) {
    // Numeric virtual IDs cannot collide with real node IDs.
    const ids = new Map(component.map((id, i) => [id, i]))
    const real = new Map(component.map((id, i) => [i, id]))
    const layers: number[][] = []
    const before = new Map<number, number[]>(), after = new Map<number, number[]>()
    const add = (vertex: number, depth: number) => {
      ;(layers[depth] ??= []).push(vertex)
      before.set(vertex, []); after.set(vertex, [])
    }
    for (const id of component) add(ids.get(id)!, rank.get(id)!)
    let virtual = component.length
    const segments: Array<[number, number, number]> = []
    const connect = (a: number, b: number, depth: number) => {
      after.get(a)!.push(b); before.get(b)!.push(a); segments.push([a, b, depth])
    }
    for (const source of component) for (const target of [...outgoing.get(source)!].sort((a, b) => order.get(a)! - order.get(b)!)) {
      const start = rank.get(source)!, end = rank.get(target)!
      if (end <= start) continue // Feedback stays visible, but does not reverse the forward layout.
      let previous = ids.get(source)!
      for (let depth = start + 1; depth < end; depth++) {
        const vertex = virtual++; add(vertex, depth); connect(previous, vertex, depth - 1); previous = vertex
      }
      connect(previous, ids.get(target)!, end - 1)
    }
    const slots = () => new Map(layers.flatMap(layer => layer.map((v, i) => [v, i] as const)))
    const crossings = () => {
      const slot = slots()
      let count = 0
      const byDepth = new Map<number, Array<[number, number]>>()
      for (const [a, b, depth] of segments) {
        if (!byDepth.has(depth)) byDepth.set(depth, [])
        byDepth.get(depth)!.push([slot.get(a)!, slot.get(b)!])
      }
      for (const [depth, links] of byDepth) {
        links.sort((a, b) => a[0] - b[0] || a[1] - b[1])
        const tree = new Array<number>(layers[depth + 1]!.length + 1).fill(0)
        let inserted = 0
        for (let start = 0; start < links.length;) {
          let end = start + 1
          while (end < links.length && links[end]![0] === links[start]![0]) end++
          // Query each shared-source batch before inserting it. Shared sources
          // and shared targets are joins, not crossings.
          for (let i = start; i < end; i++) {
            let prefix = 0
            for (let j = links[i]![1] + 1; j > 0; j -= j & -j) prefix += tree[j]!
            count += inserted - prefix
          }
          for (let i = start; i < end; i++) {
            for (let j = links[i]![1] + 1; j < tree.length; j += j & -j) tree[j]!++
            inserted++
          }
          start = end
        }
      }
      return count
    }
    let best = layers.map(layer => [...layer]), bestScore = crossings()
    // Alternate predecessor/successor barycentres. Retain the best arrangement;
    // a later sweep must not undo an earlier reduction in crossings.
    for (let pass = 0; pass < 8; pass++) {
      const forward = pass % 2 === 0
      for (let step = 0; step < layers.length; step++) {
        const depth = forward ? step : layers.length - step - 1
        const layer = layers[depth]!
        const slot = slots(), peers = forward ? before : after
        const barycentre = (v: number) => {
          const neighbors = peers.get(v)!
          return neighbors.length ? neighbors.reduce((sum, peer) => sum + slot.get(peer)!, 0) / neighbors.length : slot.get(v)!
        }
        // Keep siblings contiguous when an explicit semantic parent exists.
        const blocks = new Map<string, number[]>()
        for (const vertex of layer) {
          const parent = parentByNode.get(real.get(vertex) || '')
          const key = parent ? `parent:${parent}` : `vertex:${vertex}`
          if (!blocks.has(key)) blocks.set(key, [])
          blocks.get(key)!.push(vertex)
        }
        const average = (block: number[]) => block.reduce((sum, v) => sum + barycentre(v), 0) / block.length
        layers[depth] = [...blocks.values()].sort((a, b) => average(a) - average(b) || slot.get(a[0]!)! - slot.get(b[0]!)!)
          .flatMap(block => block.sort((a, b) => barycentre(a) - barycentre(b) || slot.get(a)! - slot.get(b)!))
      }
      const score = crossings()
      if (score < bestScore || (pass === 0 && score === bestScore)) { best = layers.map(layer => [...layer]); bestScore = score }
    }
    const height = Math.max(...best.map(layer => layer.length), 1) * ROW_GAP
    for (let depth = 0; depth < best.length; depth++) {
      const layer = best[depth]!
      layer.forEach((vertex, row) => {
        const id = real.get(vertex)
        if (id) positions.set(id, { x: depth * COLUMN_GAP, y: bandTop + height / 2 + (row - (layer.length - 1) / 2) * ROW_GAP })
      })
    }
    bandTop += height + ROW_GAP
  }
  const center = components.length ? (bandTop - ROW_GAP) / 2 : 0
  for (const position of positions.values()) position.y -= center
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
