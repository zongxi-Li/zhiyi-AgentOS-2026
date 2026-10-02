<template>
  <div
    class="graph-demo"
    :class="{ 'is-dark': dark, 'is-live': playing }"
    data-testid="acg-graph-demo"
    role="group"
    aria-label="ACG 计算图演示：从一句话意图动态组网"
  >
    <header class="graph-demo__bar">
      <span class="graph-demo__title">ACG GRAPH · 动态组网</span>
      <span class="graph-demo__status" :class="playing ? 'is-running' : 'is-done'">
        <i aria-hidden="true"></i>{{ playing ? '组网运行中' : '图已编译' }}
      </span>
    </header>

    <div class="graph-demo__stage">
      <svg class="graph-demo__svg" viewBox="0 0 700 340" role="img" aria-hidden="true">
        <defs>
          <marker id="graph-demo-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
            <path d="M0,0 L7,3.5 L0,7 Z" class="graph-demo__arrow-head" />
          </marker>
        </defs>

        <path
          v-for="edge in edges"
          :key="edge.id"
          class="graph-demo__edge"
          :class="{ 'is-hot': hotEdges.has(edge.id) }"
          :d="edge.d"
          marker-end="url(#graph-demo-arrow)"
        ></path>

        <g
          v-for="node in nodes"
          :key="node.id"
          class="graph-demo__node"
          :class="[`is-${node.kind}`, { 'is-hot': hoverNode === node.id }]"
          :transform="`translate(${node.x}, ${node.y})`"
          @mouseenter="hoverNode = node.id"
          @mouseleave="hoverNode = ''"
        >
          <rect class="graph-demo__node-box" :width="node.w" :height="node.h" rx="11"></rect>
          <text class="graph-demo__node-glyph" :x="20" :y="node.h / 2 + 1">{{ node.glyph }}</text>
          <text class="graph-demo__node-name" :x="38" :y="node.h / 2 + 4.5">{{ node.name }}</text>
        </g>

        <text class="graph-demo__hint" :x="287" :y="130" text-anchor="middle">条件路由</text>
        <text class="graph-demo__hint" :x="287" :y="212" text-anchor="middle">并行 superstep</text>
      </svg>
    </div>

    <footer class="graph-demo__chips" aria-label="组网机制">
      <span v-for="chip in mechanisms" :key="chip" class="graph-demo__chip">{{ chip }}</span>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'

/* ACG 计算图演示：意图 → Planner 动态组网 → RAG 检索 ∥ 写作 Agent
   并行 superstep → Review barrier → outputRef 交付。节点/边全部来自
   真实运行时概念；流动虚线为纯 CSS 动画，仅在区块进入视口且未开启
   "减少动效"时播放（is-live 门控）。悬停节点高亮关联边。 */
const props = withDefaults(defineProps<{ active?: boolean; dark?: boolean }>(), { active: false, dark: false })

const motionAllowed = () => {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return !window.matchMedia('(prefers-reduced-motion: reduce)').matches
}
const playing = computed(() => props.active && motionAllowed())

type GraphNode = { id: string; glyph: string; name: string; kind: 'intent' | 'runtime' | 'agent' | 'output'; x: number; y: number; w: number; h: number; edges: string[] }
const nodes: GraphNode[] = [
  { id: 'intent', glyph: '意', name: '意图', kind: 'intent', x: 16, y: 148, w: 84, h: 44, edges: [] },
  { id: 'planner', glyph: '划', name: 'Planner 规划', kind: 'runtime', x: 152, y: 148, w: 122, h: 44, edges: ['intent-planner', 'planner-rag', 'planner-writer'] },
  { id: 'rag', glyph: '检', name: 'RAG 检索', kind: 'agent', x: 332, y: 54, w: 112, h: 44, edges: ['planner-rag', 'rag-review'] },
  { id: 'writer', glyph: '写', name: '写作 Agent', kind: 'agent', x: 332, y: 242, w: 112, h: 44, edges: ['planner-writer', 'writer-review'] },
  { id: 'review', glyph: '审', name: 'Review barrier', kind: 'runtime', x: 496, y: 148, w: 112, h: 44, edges: ['rag-review', 'writer-review', 'review-output'] },
  { id: 'output', glyph: '交', name: 'outputRef', kind: 'output', x: 626, y: 148, w: 60, h: 44, edges: [] }
]

const edges = [
  { id: 'intent-planner', d: 'M100,170 C126,170 126,170 152,170' },
  { id: 'planner-rag', d: 'M274,148 C300,120 306,76 332,76' },
  { id: 'planner-writer', d: 'M274,192 C300,220 306,264 332,264' },
  { id: 'rag-review', d: 'M444,76 C470,104 470,148 496,170' },
  { id: 'writer-review', d: 'M444,264 C470,236 470,192 496,170' },
  { id: 'review-output', d: 'M608,170 C617,170 617,170 626,170' }
]

const mechanisms = ['ACG', '条件路由', '并行 superstep', 'RAG 检索', 'outputRef'] as const

const hoverNode = ref('')
const hotEdges = computed(() => {
  const node = nodes.find(item => item.id === hoverNode.value)
  return new Set(node ? node.edges : [])
})
</script>

<style scoped lang="scss">
/* 与任务工作区同一「纸上对弈」调色板；星弈变体由落地页 CSS 变量穿透。 */
.graph-demo {
  --demo-ink: #2a241c;
  --demo-ink-soft: #6f665a;
  --demo-muted: #948a7b;
  --demo-line: rgba(58, 50, 38, .18);
  --demo-card: rgba(252, 250, 245, .66);
  --demo-card-strong: rgba(252, 250, 245, .94);
  --demo-accent: #c15f3c;
  --demo-tan: #8a6a3d;
  --demo-success: #3e7c4f;
  --demo-on-ink: #f5f1e8;
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--demo-line);
  border-radius: 12px;
  background: var(--demo-card-strong);
  font-family: var(--font-sans, sans-serif);
  text-align: left;
}
.graph-demo.is-dark {
  --demo-ink: #f2ede4;
  --demo-ink-soft: #c9bfad;
  --demo-muted: #9a8f7e;
  --demo-line: rgba(242, 237, 228, .14);
  --demo-card: rgba(31, 28, 25, .5);
  --demo-card-strong: rgba(42, 37, 31, .92);
  --demo-accent: #d97757;
  --demo-tan: #c99a6b;
  --demo-success: #8fbf9a;
  --demo-on-ink: #1f1c19;
  border-color: var(--demo-line);
}

.graph-demo__bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px 18px; border-bottom: 1px solid var(--demo-line); }
.graph-demo__title { color: var(--demo-muted); font: 700 10px var(--font-mono, monospace); letter-spacing: .16em; }
.graph-demo__status { display: inline-flex; align-items: center; gap: 7px; padding: 3px 11px; border-radius: 999px; color: var(--demo-ink-soft); border: 1px solid var(--demo-line); background: var(--demo-card); font-size: 11px; font-weight: 650; white-space: nowrap; }
.graph-demo__status i { width: 6px; height: 6px; border-radius: 50%; background: var(--demo-muted); }
.graph-demo__status.is-running { color: var(--demo-accent); border-color: color-mix(in srgb, var(--demo-accent) 42%, transparent); }
.graph-demo__status.is-running i { background: var(--demo-accent); animation: graph-pulse 1.1s ease-in-out infinite; }
.graph-demo__status.is-done { color: var(--demo-success); border-color: color-mix(in srgb, var(--demo-success) 42%, transparent); }
.graph-demo__status.is-done i { background: var(--demo-success); }

.graph-demo__stage { width: min(780px, 100%); margin: 0 auto; padding: 6px 10px 0; }
.graph-demo__svg { display: block; width: 100%; height: auto; }

.graph-demo__edge {
  fill: none;
  stroke: color-mix(in srgb, var(--demo-ink) 30%, transparent);
  stroke-width: 1.6;
  marker-end: url(#graph-demo-arrow);
  transition: stroke 240ms ease, stroke-width 240ms ease;
}
.graph-demo__edge.is-hot { stroke: var(--demo-accent); stroke-width: 2.4; }
.graph-demo.is-live .graph-demo__edge {
  stroke-dasharray: 7 9;
  animation: graph-flow 1.15s linear infinite;
}
.graph-demo.is-live .graph-demo__edge.is-hot { animation-duration: .7s; }
.graph-demo__arrow-head { fill: color-mix(in srgb, var(--demo-ink) 38%, transparent); }

.graph-demo__node { cursor: default; }
.graph-demo__node-box {
  fill: var(--demo-card-strong);
  stroke: color-mix(in srgb, var(--demo-ink) 26%, transparent);
  stroke-width: 1.2;
  transition: stroke 240ms ease, fill 240ms ease;
  transform-box: fill-box;
  transform-origin: center;
}
.graph-demo__node-glyph {
  font-family: var(--font-serif, serif);
  font-size: 14px;
  font-weight: 680;
  fill: var(--demo-ink);
}
.graph-demo__node-name {
  font-size: 11.5px;
  font-weight: 640;
  fill: var(--demo-ink-soft);
  transition: fill 240ms ease;
}
.graph-demo__node.is-hot .graph-demo__node-box { stroke: var(--demo-accent); fill: color-mix(in srgb, var(--demo-accent) 7%, var(--demo-card-strong)); }
.graph-demo__node.is-hot .graph-demo__node-name { fill: var(--demo-ink); }
.graph-demo__node.is-intent .graph-demo__node-glyph { fill: var(--demo-muted); }
.graph-demo__node.is-agent .graph-demo__node-box { stroke: color-mix(in srgb, var(--demo-tan) 52%, transparent); }
.graph-demo__node.is-agent .graph-demo__node-glyph { fill: var(--demo-tan); }
.graph-demo__node.is-output .graph-demo__node-box { fill: var(--demo-ink); stroke: var(--demo-ink); }
.graph-demo__node.is-output .graph-demo__node-glyph { fill: var(--demo-on-ink); }
.graph-demo__node.is-output .graph-demo__node-name { fill: var(--demo-on-ink); }
.graph-demo.is-live .graph-demo__node.is-runtime .graph-demo__node-box { stroke: color-mix(in srgb, var(--demo-accent) 55%, transparent); }

.graph-demo__hint { font-size: 9.5px; font-weight: 650; letter-spacing: .08em; fill: var(--demo-muted); }

.graph-demo__chips { display: flex; flex-wrap: wrap; gap: 6px; padding: 11px 16px; border-top: 1px solid var(--demo-line); margin-top: 6px; }
.graph-demo__chip { padding: 3px 9px; border-radius: 6px; color: var(--demo-ink-soft); border: 1px solid var(--demo-line); background: var(--demo-card); font: 600 9.5px var(--font-mono, monospace); letter-spacing: .03em; }

@keyframes graph-flow { to { stroke-dashoffset: -32; } }
@keyframes graph-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .3; } }

@media (prefers-reduced-motion: reduce) {
  .graph-demo__edge, .graph-demo__node-box, .graph-demo__node-name { transition: none; }
  .graph-demo.is-live .graph-demo__edge { animation: none; }
  .graph-demo__status.is-running i { animation: none; }
}
</style>
