<template>
  <main
    ref="landingRoot"
    class="landing-view"
    :class="{ 'is-desktop-shell': desktopShell, 'is-theme-dark': isDarkTheme, 'is-scrolled': scrolled, 'is-style-star': landingStyle === 'star' }"
    aria-label="知弈 AgentOS 公开首页"
  >
    <header class="landing-header" v-bind="dragRegionProps" aria-label="应用窗口标题栏">
      <a class="landing-brand" href="/" aria-label="知弈 AgentOS 首页" @click.prevent="goHome">
        <span class="landing-brand__logo"><img src="/logo.webp" alt="" aria-hidden="true" /></span>
        <span class="landing-brand__wordmark">知弈 <strong>AgentOS</strong></span>
      </a>

      <nav class="landing-nav" aria-label="主导航">
        <a
          v-for="item in navigation"
          :key="item.id"
          :class="{ 'is-active': activeSection === item.id }"
          :href="`#${item.id}`"
          :aria-current="activeSection === item.id ? 'page' : undefined"
          @click.prevent="goToSection(item.id)"
        >{{ item.label }}</a>
      </nav>

      <div class="landing-header__actions">
        <span class="landing-header__note">More Agents <i aria-hidden="true">·</i> More Possibilities</span>
        <div ref="styleMenuRef" class="landing-style-picker" :class="{ 'is-open': stylePickerOpen }">
          <button
            class="landing-island-btn"
            data-testid="landing-style-toggle"
            type="button"
            aria-label="选择整体风格"
            title="选择整体风格"
            :aria-expanded="stylePickerOpen"
            aria-haspopup="menu"
            @click="stylePickerOpen = !stylePickerOpen"
          >
            <el-icon aria-hidden="true"><Brush /></el-icon>
          </button>
          <div class="landing-style-picker__menu" role="menu" aria-label="整体风格">
            <button
              v-for="opt in styleOptions"
              :key="opt.id"
              type="button"
              role="menuitemradio"
              class="landing-style-picker__option"
              :class="{ 'is-active': landingStyle === opt.id }"
              :aria-checked="landingStyle === opt.id"
              @click="chooseStyleFx(opt.id, $event)"
            >
              <i class="landing-style-picker__swatch" :class="`is-${opt.id}`" aria-hidden="true"></i>
              <span>{{ opt.name }}</span>
              <small>{{ opt.note }}</small>
            </button>
          </div>
        </div>
        <button
          class="landing-island-btn landing-theme-toggle"
          data-testid="landing-theme-toggle"
          type="button"
          :aria-label="themeToggleLabel"
          :title="themeToggleLabel"
          @click="toggleThemeFx($event)"
        >
          <el-icon aria-hidden="true"><Sunny v-if="isDarkTheme" /><Moon v-else /></el-icon>
        </button>
      </div>
      <DesktopWindowControls v-if="desktopShell" />
    </header>

    <div class="landing-scroll">
      <section id="home" data-testid="landing-page-home" class="landing-hero" :class="{ 'is-auth-open': authOpen }" aria-labelledby="landing-title">
        <span class="landing-watermark" aria-hidden="true">局</span>
        <div class="landing-hero__inner">
          <div class="landing-hero-row">
            <div class="landing-hero__copy">
              <p class="landing-eyebrow">LONG-HORIZON · COLLECTIVE INTELLIGENCE</p>
              <h1 id="landing-title">知弈 <span>AgentOS</span></h1>
              <h2>把超长程复杂任务，<br /><em>做成可交付的闭环</em></h2>
              <p class="landing-lead">目标为局，智能体为子。从一句模糊的自然语言意图，到规划、执行、恢复、审计、交付——超长程任务在一个统一运行时里全程闭环，通用场景随取随用。</p>
              <div class="landing-hero__actions">
                <button class="landing-cta" type="button" data-testid="landing-cta" @click="goToLogin">
                  进入知弈 AgentOS
                  <el-icon aria-hidden="true"><ArrowRight /></el-icon>
                </button>
                <button class="landing-cta landing-cta--ghost" type="button" @click="goToSection('mission')">
                  观看任务演示
                  <el-icon aria-hidden="true"><VideoPlay /></el-icon>
                </button>
              </div>
            </div>
            <div class="landing-agent-slot" data-testid="landing-agent-slot">
              <LoginView v-if="authOpen" embedded @back="closeAuth" />
              <GlassConstellation v-else />
            </div>
          </div>
          <nav class="landing-capability-strip" data-testid="landing-capability-strip" aria-label="系统模块入口">
            <span class="landing-capability-strip__label">SYSTEM MAP · 模块入口</span>
            <button
              v-for="cap in capabilities"
              :key="cap.route"
              type="button"
              class="landing-capability-strip__item"
              :title="`进入 ${cap.label} · ${cap.route}`"
              :aria-label="`进入${cap.label}模块`"
              @click="openAuth(cap.route)"
            >
              <span>{{ cap.label }}</span><code>{{ cap.tag }}</code>
            </button>
          </nav>
        </div>
        <span class="landing-scroll-cue" aria-hidden="true"><el-icon><ArrowDown /></el-icon>SCROLL</span>
      </section>

      <section id="mission" data-testid="landing-page-mission" class="landing-section landing-section--panel" aria-labelledby="mission-title">
        <span class="landing-watermark" aria-hidden="true">弈</span>
        <div class="landing-section__inner">
          <div class="landing-section__heading" data-reveal>
            <p class="landing-eyebrow">弈 · MISSION LOOP</p>
            <h2 id="mission-title">从目标，到结果</h2>
            <p class="landing-section__intro">一局任务从意图到交付的完整对弈：规划组网、并行执行、中途变更、复核交付，全程建模为 Agentic Computation Graph——有类型的节点与边，每一步都有迹可循。</p>
          </div>
          <div class="landing-mission-layout">
            <MissionRunDemo data-reveal :active="missionDemoActive" :dark="isDarkTheme" />
            <div class="landing-info-grid landing-info-grid--features">
              <article v-for="item in missionFeatures" :key="item.title" class="landing-info-card" data-reveal>
                <span class="landing-info-card__index">{{ item.index }}</span>
                <h3>{{ item.title }}</h3>
                <p>{{ item.description }}</p>
                <span class="landing-info-card__meta">{{ item.meta }}</span>
              </article>
            </div>
          </div>
        </div>
      </section>

      <section id="horizon" data-testid="landing-page-horizon" class="landing-section" aria-labelledby="horizon-title">
        <span class="landing-watermark" aria-hidden="true">恒</span>
        <div class="landing-section__inner">
          <div class="landing-section__heading" data-reveal>
            <p class="landing-eyebrow">恒 · LONG-HORIZON</p>
            <h2 id="horizon-title">千步长程，不散不塌</h2>
            <p class="landing-section__intro">超长程任务常见的五种失败模式，知弈各有一个工程答案——每一项都有对应实现与测试。</p>
          </div>
          <div class="landing-info-grid landing-info-grid--horizon">
            <article v-for="item in horizonFeatures" :key="item.title" class="landing-info-card" data-reveal>
              <span class="landing-info-card__index">{{ item.index }}</span>
              <h3>{{ item.title }}</h3>
              <p>{{ item.description }}</p>
              <span class="landing-info-card__meta">{{ item.meta }}</span>
            </article>
          </div>
        </div>
      </section>

      <section id="scenes" data-testid="landing-page-scenes" class="landing-section landing-section--panel" aria-labelledby="scenes-title">
        <span class="landing-watermark" aria-hidden="true">泛</span>
        <div class="landing-section__inner">
          <div class="landing-section__heading" data-reveal>
            <p class="landing-eyebrow">泛 · GENERAL SCENARIOS</p>
            <h2 id="scenes-title">一套系统，通用场景</h2>
            <p class="landing-section__intro">领域 Pack 即插即用；没有现成模板，就从一句话意图开始动态组网。</p>
          </div>
          <div class="landing-info-grid landing-info-grid--scenes">
            <article v-for="item in sceneFeatures" :key="item.title" class="landing-info-card" :class="{ 'landing-info-card--featured': item.featured }" data-reveal>
              <span class="landing-info-card__index">{{ item.index }}</span>
              <h3>{{ item.title }}</h3>
              <p>{{ item.description }}</p>
              <span v-if="item.chips" class="landing-info-card__chips">
                <i v-for="chip in item.chips" :key="chip">{{ chip }}</i>
              </span>
              <span class="landing-info-card__meta">{{ item.meta }}</span>
            </article>
          </div>
        </div>
      </section>

      <section id="ecosystem" data-testid="landing-page-ecosystem" class="landing-section" aria-labelledby="ecosystem-title">
        <span class="landing-watermark" aria-hidden="true">势</span>
        <div class="landing-section__inner">
          <div class="landing-section__heading" data-reveal>
            <p class="landing-eyebrow">势 · ECOSYSTEM</p>
            <h2 id="ecosystem-title">连接模型、知识与运行时</h2>
            <p class="landing-section__intro">模型、知识与角色汇成一局之势，需要什么，就调用什么。</p>
          </div>
          <div class="landing-info-grid landing-info-grid--four">
            <article v-for="item in ecosystemFeatures" :key="item.title" class="landing-info-card" data-reveal>
              <span class="landing-info-card__index">{{ item.index }}</span>
              <h3>{{ item.title }}</h3>
              <p>{{ item.description }}</p>
              <span class="landing-info-card__meta">{{ item.meta }}</span>
            </article>
          </div>
          <div class="landing-store-ribbon" data-reveal aria-label="六类独立状态存储">
            <span class="landing-store-ribbon__label">STATE STORES · 六类独立状态存储</span>
            <div class="landing-store-ribbon__items">
              <span v-for="store in stateStores" :key="store.name"><b>{{ store.name }}</b><small>{{ store.note }}</small></span>
            </div>
          </div>
        </div>
      </section>

      <section id="about" data-testid="landing-page-about" class="landing-section landing-section--panel" aria-labelledby="about-title">
        <span class="landing-watermark landing-watermark--pair" aria-hidden="true">复盘</span>
        <div class="landing-about__inner">
          <div class="about-team__copy" data-reveal>
            <p class="landing-eyebrow">复盘 · ABOUT THE TEAM</p>
            <h2 id="about-title">二龙山<br /><span>游击队</span></h2>
            <p class="about-team__lead">保持好奇，保持行动。</p>
            <p class="about-team__note">我们在想法、技术与作品之间穿行，寻找值得被看见的答案。知弈 AgentOS 响应挑战杯赛题 XH-202631——面向超长程复杂任务的动态异构群体智能架构与深度协同推理技术。</p>
            <div class="about-team__stack" aria-label="技术栈">
              <span v-for="chip in teamStack" :key="chip">{{ chip }}</span>
            </div>
          </div>
          <aside class="about-contact-card" data-reveal aria-label="二龙山游击队联系方式">
            <div class="about-contact-card__top">
              <span>CONTACT</span>
              <i class="about-contact-card__seal" aria-hidden="true">弈</i>
            </div>
            <div class="about-contact-card__item">
              <span class="about-contact-card__label">PHONE / 电话</span>
              <span class="about-contact-card__value">18703442157</span>
            </div>
            <div class="about-contact-card__item">
              <span class="about-contact-card__label">EMAIL / 邮箱</span>
              <span class="about-contact-card__value">2293581974@qq.com</span>
            </div>
            <p class="about-contact-card__hint">欢迎交流项目、合作与新的想法。</p>
            <button class="landing-cta landing-cta--small about-team__cta" type="button" @click="goToLogin">
              进入 AgentOS
              <el-icon aria-hidden="true"><ArrowRight /></el-icon>
            </button>
          </aside>
        </div>
      </section>

      <footer class="landing-footer" aria-label="页脚">
        <a class="landing-footer__brand" href="/" @click.prevent="goHome">知弈 AgentOS</a>
        <span class="landing-footer__meta">MIT License · 挑战杯 XH-202631 · 二龙山游击队</span>
        <button class="landing-footer__top" type="button" aria-label="回到顶部" @click="goToSection('home')">
          <el-icon aria-hidden="true"><Top /></el-icon>
        </button>
      </footer>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowDown, ArrowRight, Brush, Moon, Sunny, Top, VideoPlay } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import DesktopWindowControls from '@window-controls'
import { isDesktop, platform } from '@/platform'
import { useTheme } from '@/composables/useTheme'
import MissionRunDemo from '@/components/landing/MissionRunDemo.vue'
const GlassConstellation = defineAsyncComponent(() => import('@/components/landing/GlassConstellation.vue').then(module => module.default))
const LoginView = defineAsyncComponent(() => import('@/views/LoginView.vue').then(module => module.default))

const router = useRouter()
const route = useRoute()
const { currentScheme, toggleColorScheme } = useTheme()
const isDarkTheme = computed(() => currentScheme.value === 'codex-dark' || currentScheme.value === 'one-dark-modern')
const themeToggleLabel = computed(() => `切换到${isDarkTheme.value ? '明亮' : '黑暗'}模式`)
const desktopShell = isDesktop()
const dragRegionProps = platform.dragRegionProps
const landingRoot = ref<HTMLElement | null>(null)
const scrolled = ref(false)
const missionDemoActive = ref(false)

/* 整体风格：纸弈（暖纸·铜橘，默认）/ 星弈（星空·青紫），选择持久化。 */
type LandingStyle = 'paper' | 'star'
const LANDING_STYLE_KEY = 'kinlin:landing-style'
const readSavedStyle = (): LandingStyle => {
  try { return localStorage.getItem(LANDING_STYLE_KEY) === 'star' ? 'star' : 'paper' } catch { return 'paper' }
}
const landingStyle = ref<LandingStyle>(readSavedStyle())
const styleOptions = [
  { id: 'paper' as const, name: '纸弈', note: '暖纸 · 铜橘' },
  { id: 'star' as const, name: '星弈', note: '星空 · 青紫' }
]
const stylePickerOpen = ref(false)
const styleMenuRef = ref<HTMLElement | null>(null)
const applyLandingStyle = (style: LandingStyle) => {
  document.documentElement.dataset.landingStyle = style
}
applyLandingStyle(landingStyle.value)
watch(landingStyle, applyLandingStyle)
const chooseStyle = (id: 'paper' | 'star') => {
  landingStyle.value = id
  try { localStorage.setItem(LANDING_STYLE_KEY, id) } catch { /* 无痕/禁用存储时仅本次会话生效 */ }
  stylePickerOpen.value = false
}
const handleDocumentClick = (event: MouseEvent) => {
  if (styleMenuRef.value && !styleMenuRef.value.contains(event.target as Node)) stylePickerOpen.value = false
}

/* 常规滚动长页：吸顶导航 + 滚动渐显 + 滚动高亮当前区块。 */
const navigation = [
  { id: 'home', label: '首页' },
  { id: 'mission', label: '任务' },
  { id: 'horizon', label: '长程' },
  { id: 'scenes', label: '场景' },
  { id: 'ecosystem', label: '生态' },
  { id: 'about', label: '关于' }
] as const
const activeSection = ref<string>('home')
const authOpen = ref(route.query.auth === '1')

/* 模块入口条：全部指向真实路由，点击后经嵌入式登录直达对应工作区。 */
const capabilities = [
  { label: '任务编排', tag: 'missions', route: '/agentos/missions/new' },
  { label: '群体图谱', tag: 'acg', route: '/agentos/acg' },
  { label: '运行记忆', tag: 'memory', route: '/agentos/memory' },
  { label: '知识库', tag: 'rag', route: '/rag' },
  { label: '模型资源', tag: 'resources', route: '/agentos/resources' },
  { label: '历史审计', tag: 'history', route: '/history' }
] as const

const missionFeatures = [
  { index: '01 / PLAN', title: '理解与组网', description: 'Planner 将高层意图拆解为 ACG 计算图：条件路由、并行 superstep、动态组网。', meta: 'Context → Graph' },
  { index: '02 / EXECUTE', title: '并行与协同', description: '多步并行执行，Communication Broker 按字段白名单投递上下文，熵预算抑制噪声。', meta: 'Superstep → Actions' },
  { index: '03 / DELIVER', title: '复核与交付', description: 'Review barrier 把关，Evidence 引用支撑每个结论，outputRef 解引用交付。', meta: 'Evidence → Outcome' },
  { index: '04 / RECOVER', title: '中断与恢复', description: 'Checkpoint CAS 断点续跑，GraphPatch 局部重组，需求变更不整链重跑。', meta: 'Patch → Resume' }
]

const horizonFeatures = [
  { index: 'MEMORY', title: '记忆不坍缩', description: '六类独立 Store、Checkpoint CAS、Evidence Memory 与引用式状态，长程上下文不漂移、不丢失。', meta: 'Stores · Evidence' },
  { index: 'LOW-ENTROPY', title: '低熵通信', description: 'Communication Broker 字段级投递、稀疏拓扑与熵预算，Token 不在无关广播里烧掉。', meta: 'Broker · 预算' },
  { index: 'RECOVERY', title: '动态恢复', description: 'GraphPatch、review barrier、Recovery Recipe 与 alternate rebind，节点失效后局部重生。', meta: 'Patch · Recipe' },
  { index: 'GOVERNANCE', title: '多模型治理', description: 'AgentProfile binding、版本协商、健康刷新、failover 与 key rotation，异构模型可治理。', meta: 'Binding · Failover' },
  { index: 'ACCOUNTABLE', title: '可解释交付', description: 'Trace、Provenance、Checkpoint、Review 全程留痕，每个产出都能回溯到依据。', meta: 'Trace · Provenance' }
]

const sceneFeatures = [
  { index: 'PACK · LEGAL', title: '法律 · 黄金纵切', description: '合同起草、条款审查、修订建议、证据引用——全链路可复核的完整领域纵切。', meta: '已完成 · 可验收', chips: ['合同起草', '条款审查', '证据引用'], featured: true },
  { index: 'PACK · PROGRAMMER', title: '编程', description: '代码生成、调试与审查的工程场景。', meta: 'Domain Pack' },
  { index: 'PACK · EDUCATION', title: '教育', description: '教学设计、课程内容与习题生成。', meta: 'Domain Pack' },
  { index: 'PACK · WRITER', title: '写作', description: '长文写作、改稿与多风格表达。', meta: 'Domain Pack' },
  { index: 'PACK · GENERAL', title: '通用', description: 'General-Native 默认执行包，兜底任意任务。', meta: 'Domain Pack' },
  { index: 'MISSION · 自由任务', title: '自定义任务', description: '没有现成模板？从一句话意图开始，Planner 动态组网。', meta: 'Intent → Graph' }
]

const ecosystemFeatures = [
  { index: 'MODEL LAYER', title: '模型与资源', description: '统一管理模型与工具：多供应商接入、热切换、failover 与 key rotation。', meta: '/agentos/resources' },
  { index: 'KNOWLEDGE LAYER', title: '知识与工作流', description: 'RAG 检索让知识进入工作流，引用式上下文，处处可追溯。', meta: '/rag' },
  { index: 'ROLE LAYER', title: '角色与执行体', description: '执行角色统一管理：创建、配置、绑定模型与技能，按任务需要取用。', meta: '/agentos/resources' },
  { index: 'RUNTIME LAYER', title: '运行与审计', description: '运行记忆、历史审计与群体图谱，一局任务的全过程可回放。', meta: '/agentos/memory' }
]

const stateStores = [
  { name: 'Workflow', note: '流程' },
  { name: 'Checkpoint', note: '检查点' },
  { name: 'Value', note: '值' },
  { name: 'Memory', note: '记忆' },
  { name: 'Provenance', note: '溯源' },
  { name: 'Decision', note: '决策' }
] as const

const teamStack = ['Vue 3 Workbench', 'Spring Gateway', 'FastAPI Runtime', 'MIT License'] as const

let revealObserver: IntersectionObserver | undefined
let spyObserver: IntersectionObserver | undefined

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
    : false

const goToSection = (id: string) => {
  activeSection.value = id
  const target = landingRoot.value?.querySelector(`#${id}`)
  target?.scrollIntoView?.({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' })
  const hash = `#${id}`
  if (route.hash !== hash) void router.replace({ path: '/', hash })
}

const handleScroll = () => {
  const el = scrollEl ?? landingRoot.value
  if (!el) return
  scrolled.value = el.scrollTop > 24
  const max = Math.max(1, el.scrollHeight - el.clientHeight)
  // 变量写在根元素上：进度条在 .landing-header（滚动容器的兄弟子树），靠继承取值
  if (landingRoot.value) landingRoot.value.style.setProperty('--scroll-progress', String(Math.min(1, el.scrollTop / max)))
  const demo = landingRoot.value.querySelector('.mission-demo')
  if (demo) {
    const rect = demo.getBoundingClientRect()
    missionDemoActive.value = rect.top < window.innerHeight * 0.9 && rect.bottom > 0
  }
}

/* 真正滚动的是内层 .landing-scroll（scroll 事件不冒泡，监听必须挂在它身上；
   此前挂在 overflow:hidden 的根元素上，scrolled/演示卡激活等滚动联动一直是死的）。 */
let scrollEl: Element | null = null

onMounted(() => {
  const root = landingRoot.value
  if (!root) return
  document.addEventListener('click', handleDocumentClick)
  scrollEl = root.querySelector('.landing-scroll')
  scrollEl?.addEventListener('scroll', handleScroll, { passive: true })
  if ('IntersectionObserver' in window) {
    root.classList.add('supports-reveal')
    revealObserver = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-in')
          revealObserver?.unobserve(entry.target)
        }
      }
    }, { root, threshold: 0.12, rootMargin: '0px 0px -6% 0px' })
    root.querySelectorAll('[data-reveal]').forEach(el => revealObserver?.observe(el))
    spyObserver = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (entry.isIntersecting && entry.target instanceof HTMLElement) activeSection.value = entry.target.id
      }
    }, { root, rootMargin: '-42% 0px -52% 0px', threshold: 0 })
    navigation.forEach(item => {
      const el = root.querySelector(`#${item.id}`)
      if (el) spyObserver?.observe(el)
    })
  }
  if (route.hash) {
    const id = route.hash.replace(/^#/, '')
    if (navigation.some(item => item.id === id)) {
      requestAnimationFrame(() => goToSection(id))
    }
  }
  handleScroll()
  setupPointerMotion(root)
})

/* 指针微动效：磁吸按钮 + 卡片聚光。只在精细指针（鼠标）且未开启
   "减少动效" 时启用；touch/降级环境下页面行为不变。 */
const motionCleanups: Array<() => void> = []
const setupPointerMotion = (root: HTMLElement) => {
  if (typeof window.matchMedia !== 'function') return
  if (!window.matchMedia('(hover: hover) and (pointer: fine)').matches) return
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

  root.querySelectorAll<HTMLElement>('.landing-cta, .landing-island-btn, .landing-footer__top').forEach(el => {
    const onMove = (e: MouseEvent) => {
      const r = el.getBoundingClientRect()
      const dx = Math.max(-7, Math.min(7, (e.clientX - r.left - r.width / 2) * 0.3))
      const dy = Math.max(-5, Math.min(5, (e.clientY - r.top - r.height / 2) * 0.3))
      el.style.transform = `translate(${dx}px, ${dy}px)`
    }
    const onLeave = () => { el.style.transform = '' }
    el.addEventListener('mousemove', onMove, { passive: true })
    el.addEventListener('mouseleave', onLeave, { passive: true })
    motionCleanups.push(() => {
      el.removeEventListener('mousemove', onMove)
      el.removeEventListener('mouseleave', onLeave)
      el.style.transform = ''
    })
  })

  root.querySelectorAll<HTMLElement>('.landing-info-card, .about-contact-card').forEach(el => {
    const onMove = (e: MouseEvent) => {
      const r = el.getBoundingClientRect()
      el.style.setProperty('--spot-x', `${Math.round(e.clientX - r.left)}px`)
      el.style.setProperty('--spot-y', `${Math.round(e.clientY - r.top)}px`)
    }
    el.addEventListener('mousemove', onMove, { passive: true })
    motionCleanups.push(() => el.removeEventListener('mousemove', onMove))
  })
}

onUnmounted(() => {
  revealObserver?.disconnect()
  spyObserver?.disconnect()
  motionCleanups.splice(0).forEach(fn => fn())
  document.removeEventListener('click', handleDocumentClick)
  scrollEl?.removeEventListener('scroll', handleScroll)
})

watch(() => route.hash, (hash) => {
  const id = (hash || '').replace(/^#/, '')
  if (id && navigation.some(item => item.id === id) && id !== activeSection.value) goToSection(id)
})

watch(() => route.query.auth, (value) => {
  authOpen.value = value === '1'
  if (authOpen.value) {
    activeSection.value = 'home'
    landingRoot.value?.querySelector('#home')?.scrollIntoView?.({ behavior: 'auto', block: 'start' })
  }
})

const goHome = () => {
  activeSection.value = 'home'
  landingRoot.value?.scrollTo?.({ top: 0, behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
  if (route.hash) void router.replace({ path: '/', hash: '' })
}
const toggleTheme = () => toggleColorScheme()

/* 主题/风格切换动效：View Transitions API 圆形扩散——旧快照静止，新快照从
   点击处 clip-path: circle() 展开。模式取自开源实现 rudrodip/theme-toggle-effect
   与 MaxiGarcia13/js-theme-animation-monorepo（零依赖、特性检测降级）；
   不支持的浏览器或开启"减少动效"时退化为瞬时切换。 */
type ViewTransitionDoc = Document & {
  startViewTransition?: (update: () => void | Promise<void>) => { ready: Promise<void> }
}
const revealFromClick = (event: MouseEvent, apply: () => void | Promise<void>) => {
  const doc = document as ViewTransitionDoc
  if (typeof doc.startViewTransition !== 'function' || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    void apply()
    return
  }
  const x = event.clientX || Math.round(window.innerWidth / 2)
  const y = event.clientY || Math.round(window.innerHeight / 2)
  const radius = Math.hypot(Math.max(x, window.innerWidth - x), Math.max(y, window.innerHeight - y))
  const transition = doc.startViewTransition(async () => {
    await apply()
    await nextTick()
  })
  void transition.ready.then(() => {
    document.documentElement.animate(
      { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
      { duration: 620, easing: 'cubic-bezier(.3, .8, .3, 1)', pseudoElement: '::view-transition-new(root)' }
    )
  }).catch(() => { /* 过渡被打断（快速连点/离开页面）时无需处理 */ })
}
const toggleThemeFx = (event: MouseEvent) => revealFromClick(event, () => toggleTheme())
const chooseStyleFx = (id: 'paper' | 'star', event: MouseEvent) => revealFromClick(event, () => chooseStyle(id))
const openAuth = (redirect = '/chat') => {
  authOpen.value = true
  activeSection.value = 'home'
  landingRoot.value?.scrollTo?.({ top: 0, behavior: 'auto' })
  void router.replace({ path: '/', query: { ...route.query, auth: '1', redirect }, hash: '' })
}
const closeAuth = () => {
  authOpen.value = false
  const { auth: _auth, redirect: _redirect, from: _from, ...query } = route.query
  void router.replace({ path: '/', query, hash: route.hash })
}
const goToLogin = () => openAuth()
</script>

<style scoped lang="scss">
/* 「纸上对弈」——Claude 式暖纸编辑部语言 × 知弈的弈主题。
   全部表面走 CSS 变量，深色主题只换变量值：纸→暖炭、墨→象牙、铜提亮。 */
.landing-view {
  --paper: #f5f1e8;
  --panel: #ece6d7;
  --card: #fcfaf5;
  --ink: #26231f;
  --ink-soft: #5f594c;
  --muted: #8d8676;
  --line: #e0d8c6;
  --line-strong: rgba(38, 35, 31, .22);
  --copper: #c15f3c;
  --copper-deep: #a84e30;
  --success: #3e7c4f;
  --wm: rgba(38, 35, 31, .05);
  --grid: rgba(150, 128, 92, .07);
  --grid-dot: rgba(150, 128, 92, .16);
  /* 顶栏胶囊随主题走：浅色=纸面同色系，深色=暖炭浮动岛。 */
  --header-bg: rgba(252, 250, 245, .84);
  --header-border: rgba(38, 35, 31, .12);
  --header-shadow: 0 10px 24px rgba(24, 19, 12, .1), inset 0 1px 0 rgba(255, 255, 255, .85);
  --header-shadow-scrolled: 0 16px 40px rgba(24, 19, 12, .16), inset 0 1px 0 rgba(255, 255, 255, .9);
  position: relative;
  height: 100vh;
  height: 100dvh;
  width: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  color: var(--ink);
  /* 背景挂在滚动容器的父级上，天然不随内容滚动；切勿加 background-attachment: fixed——
     该属性在 Chromium/WebView 的 overflow 滚动容器上会造成滚动跳底/触控失效。 */
  background: var(--paper);
  isolation: isolate;
}
/* 顶栏在文档流里占位（sticky 只负责悬浮视觉），滚动区吃掉剩余高度，
   否则 100% 高度会把首屏内容顶出折叠线以下 55px。 */
.landing-scroll { flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; overscroll-behavior: contain; -webkit-overflow-scrolling: touch; scroll-behavior: smooth; }

/* 极淡棋盘格 + 360px 周期星位，呼应「弈」；不夺纸面的静。 */
.landing-view::after { content: ''; position: absolute; inset: 0; z-index: 0; pointer-events: none; background: radial-gradient(circle 2.5px at 60px 60px, var(--grid-dot) 98%, transparent), radial-gradient(circle 2.5px at 240px 240px, var(--grid-dot) 98%, transparent), repeating-linear-gradient(90deg, transparent 0, transparent 119px, var(--grid) 120px), repeating-linear-gradient(0deg, transparent 0, transparent 119px, var(--grid) 120px); }

/* 顶栏胶囊：底色/边框/阴影走主题变量——浅色主题融入纸面，深色主题保持浮动暖炭岛。
   入场一次轻落（backwards 结束后释放 transform，滚动位移照常生效）。 */
@keyframes landing-header-in { from { opacity: 0; transform: translateY(-16px); } to { opacity: 1; transform: none; } }
.landing-header { position: sticky; top: 14px; z-index: 12; width: min(1180px, calc(100% - 48px)); margin: 0 auto; min-height: 54px; display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 8px 10px 8px 20px; border-radius: 999px; border: 1px solid var(--header-border); background: var(--header-bg); box-shadow: var(--header-shadow); backdrop-filter: blur(18px) saturate(140%); animation: landing-header-in 720ms cubic-bezier(.2, .8, .2, 1) backwards; transition: box-shadow 280ms ease, transform 280ms cubic-bezier(.2, .8, .2, 1), background-color 280ms ease; }
@media (prefers-reduced-motion: reduce) { .landing-header { animation: none; } .landing-brand__logo img { transition: none; } .landing-brand:hover .landing-brand__logo img { transform: none; } }
.landing-view.is-scrolled .landing-header { box-shadow: var(--header-shadow-scrolled); transform: translateY(-2px); }
/* 阅读进度：顶栏下缘细铜线，scaleX(--scroll-progress) 由滚动句柄写入。 */
.landing-header::after { content: ''; position: absolute; left: 22px; right: 22px; bottom: 3px; height: 2px; border-radius: 2px; background: color-mix(in srgb, var(--copper) 72%, transparent); transform-origin: 0 50%; transform: scaleX(var(--scroll-progress, 0)); }
/* 品牌区：花环原标 + 全衬线字标，与首屏大标题同一语言。
   花环图自带留白，直接裸放比塞进色块徽章更干净；深色主题下补一枚软边象牙圆托保对比度。 */
.landing-brand { display: inline-flex; align-items: center; gap: 9px; color: var(--ink); font-family: var(--font-serif, serif); font-size: 19px; font-weight: 600; letter-spacing: -.02em; text-decoration: none; white-space: nowrap; }
.landing-brand__wordmark { display: inline-flex; align-items: baseline; gap: 6px; }
.landing-brand strong { color: var(--copper); font-size: .95em; font-weight: 500; letter-spacing: -.01em; transition: color 220ms ease; }
.landing-brand:hover strong { color: var(--copper-deep); }
.landing-brand__logo { width: 33px; height: 33px; display: block; }
.landing-brand__logo img { width: 100%; height: 100%; display: block; object-fit: contain; transition: transform 480ms cubic-bezier(.34, 1.56, .64, 1); transform-origin: 50% 50%; }
.landing-brand:hover .landing-brand__logo img { transform: rotate(14deg) scale(1.07); }
.landing-view.is-theme-dark .landing-brand__logo { border-radius: 50%; background: radial-gradient(circle, #f6f1e2 72%, rgba(246, 241, 226, 0) 100%); }
.landing-nav { display: flex; align-items: center; gap: 2px; }
.landing-nav a { position: relative; padding: 8px 14px; border-radius: 999px; color: var(--ink-soft); font-size: 13.5px; text-decoration: none; transition: color 200ms ease, background-color 200ms ease; }
.landing-nav a:hover { color: var(--ink); background: color-mix(in srgb, var(--ink) 7%, transparent); }
.landing-nav a.is-active { color: var(--ink); background: color-mix(in srgb, var(--ink) 11%, transparent); animation: landing-nav-pill-in 280ms cubic-bezier(.2, .8, .2, 1); }
.landing-header__actions { display: flex; align-items: center; gap: 9px; margin-left: auto; }
.landing-header__note { margin-right: 8px; color: var(--muted); font-size: 10.5px; letter-spacing: .1em; white-space: nowrap; }
.landing-header__note i { padding: 0 7px; font-style: normal; color: var(--copper); }
@media (max-width: 1359px) { .landing-header__note { display: none; } }
.landing-island-btn { width: 36px; height: 36px; display: grid; place-items: center; border: 1px solid color-mix(in srgb, var(--ink) 16%, transparent); border-radius: 999px; color: var(--ink); background: color-mix(in srgb, var(--ink) 5%, transparent); cursor: pointer; font: inherit; transition: border-color 200ms ease, background-color 200ms ease, color 200ms ease, transform 200ms ease; }
.landing-island-btn .el-icon { font-size: 16px; }
.landing-island-btn:hover { border-color: color-mix(in srgb, var(--ink) 34%, transparent); background: color-mix(in srgb, var(--ink) 12%, transparent); transform: translateY(-1px); }
.landing-island-btn[aria-expanded='true'] { border-color: color-mix(in srgb, var(--copper) 55%, transparent); color: var(--copper); background: color-mix(in srgb, var(--copper) 16%, transparent); }

/* 风格选择弹出菜单 */
.landing-style-picker { position: relative; }
.landing-style-picker__menu { position: absolute; top: calc(100% + 12px); right: 0; min-width: 216px; padding: 6px; border: 1px solid var(--line); border-radius: 15px; background: var(--card); box-shadow: 0 22px 48px rgba(38, 35, 31, .18); opacity: 0; transform: translateY(-6px) scale(.97); transform-origin: top right; pointer-events: none; transition: opacity 200ms ease, transform 200ms cubic-bezier(.2, .8, .2, 1); }
.landing-style-picker.is-open .landing-style-picker__menu { opacity: 1; transform: none; pointer-events: auto; }
.landing-style-picker__option { width: 100%; display: grid; grid-template-columns: auto auto 1fr; align-items: center; gap: 9px; padding: 10px 11px; border: 1px solid transparent; border-radius: 11px; color: var(--ink); background: transparent; cursor: pointer; font: inherit; text-align: left; transition: border-color 180ms ease, background-color 180ms ease; }
.landing-style-picker__option:hover { background: color-mix(in srgb, var(--copper) 7%, transparent); }
.landing-style-picker__option.is-active { border-color: color-mix(in srgb, var(--copper) 45%, transparent); background: color-mix(in srgb, var(--copper) 9%, transparent); }
.landing-style-picker__swatch { width: 22px; height: 22px; border-radius: 7px; border: 1px solid var(--line); }
.landing-style-picker__swatch.is-paper { background: linear-gradient(135deg, #f5f1e8 52%, #c15f3c); }
.landing-style-picker__swatch.is-star { background: linear-gradient(135deg, #0c1430 52%, #38bdeb); }
.landing-style-picker__option span { font-size: 13.5px; font-weight: 680; }
.landing-style-picker__option small { color: var(--muted); font-size: 10.5px; text-align: right; }

/* 首屏 */
/* 首屏占满滚动区可视高度（100% 而非 100vh：顶栏已占走流内高度）。 */
.landing-hero { position: relative; min-height: 100%; display: flex; flex-direction: column; justify-content: flex-start; padding: clamp(118px, 14vh, 168px) 0 clamp(48px, 7vh, 84px); box-sizing: border-box; overflow: hidden; }
/* 登录卡态收紧上下留白，保证卡 + SYSTEM MAP 条一屏内完整呈现。 */
.landing-hero.is-auth-open { padding-top: clamp(100px, 12vh, 132px); padding-bottom: 44px; }
.landing-hero__inner { position: relative; z-index: 1; flex: 1; width: min(1180px, calc(100% - 48px)); margin: 0 auto; display: flex; flex-direction: column; gap: 26px; }
.landing-hero-row { display: flex; align-items: center; justify-content: space-between; gap: 44px; }
.landing-agent-slot { position: relative; width: min(42vw, 560px); height: min(42vw, 540px); min-width: 380px; min-height: 400px; margin-left: auto; display: grid; place-items: center; }
.landing-agent-slot :deep(.agent-constellation) { width: 100%; height: 100%; min-width: 0; min-height: 0; margin-left: 0; transform: none; }
/* 登录卡态：文案与卡片顶对齐（编辑部级构图），槽位高度交给卡片自己，避免 540px 固定槽装不下 ~600px 的卡。 */
.landing-hero.is-auth-open .landing-hero-row { align-items: flex-start; }
.landing-hero.is-auth-open .landing-agent-slot { width: min(42vw, 540px); height: auto; min-height: 0; }
.landing-hero.is-auth-open .landing-scroll-cue { display: none; }
.landing-hero.is-auth-open .landing-watermark { opacity: .55; }
.landing-hero__copy { position: relative; z-index: 1; width: min(560px, 48vw); animation: landing-content-in 900ms cubic-bezier(.2, .8, .2, 1) both; }
.landing-eyebrow { margin: 0 0 18px; color: var(--copper); font-size: 11px; font-weight: 750; letter-spacing: .22em; }
.landing-eyebrow::before { content: ''; display: inline-block; width: 7px; height: 7px; margin-right: 9px; border-radius: 2px; background: var(--copper); vertical-align: 1px; }
.landing-hero h1 { margin: 0; color: var(--ink); font-family: var(--font-serif, serif); font-size: clamp(52px, 5vw, 82px); font-weight: 600; line-height: .98; letter-spacing: -.05em; }
.landing-hero h1 span { color: var(--ink-soft); font-weight: 500; }
.landing-hero h2 { margin: 20px 0 0; color: var(--ink); font-family: var(--font-serif, serif); font-size: clamp(25px, 2.3vw, 38px); font-weight: 600; letter-spacing: -.03em; }
.landing-hero h2 em { font-style: normal; background-image: linear-gradient(color-mix(in srgb, var(--copper) 55%, transparent), color-mix(in srgb, var(--copper) 55%, transparent)); background-size: 100% .16em; background-position: 0 94%; background-repeat: no-repeat; padding-bottom: .06em; }
.landing-lead { margin: 18px 0 0; color: var(--ink-soft); font-size: 15.5px; line-height: 1.8; max-width: 54ch; }
.landing-hero__actions { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.landing-cta { min-height: 50px; margin-top: 34px; padding: 0 26px; display: inline-flex; align-items: center; gap: 18px; border: 1px solid var(--ink); border-radius: 12px; color: var(--paper); background: var(--ink); box-shadow: 0 10px 22px rgba(38, 35, 31, .16); font: inherit; font-size: 14px; font-weight: 700; cursor: pointer; transition: transform 220ms ease, background-color 220ms ease, border-color 220ms ease, box-shadow 220ms ease; }
.landing-cta:hover { background: var(--copper); border-color: var(--copper); transform: translateY(-2px); box-shadow: 0 14px 28px rgba(193, 95, 60, .28); }
.landing-cta:active { transform: translateY(0); }
.landing-cta .el-icon { font-size: 17px; }
.landing-cta--ghost { color: var(--ink); background: transparent; border-color: var(--line-strong); box-shadow: none; gap: 12px; }
.landing-cta--ghost:hover { color: var(--copper-deep); background: transparent; border-color: var(--copper); box-shadow: none; }

/* 模块入口条：纸片标签 */
.landing-capability-strip { position: relative; z-index: 1; margin-top: auto; display: flex; align-items: stretch; gap: 8px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 14px; background: var(--card); animation: landing-content-in 900ms cubic-bezier(.2, .8, .2, 1) 140ms both; }
.landing-capability-strip__label { flex: 0 0 auto; display: grid; place-items: center; padding: 0 8px 0 6px; color: var(--muted); font-size: 9.5px; font-weight: 750; letter-spacing: .16em; white-space: nowrap; }
.landing-capability-strip__item { min-height: 40px; padding: 0 16px; display: inline-flex; align-items: center; gap: 9px; flex: 1 1 0; min-width: 0; border: 1px solid var(--line); border-radius: 10px; color: var(--ink); background: transparent; cursor: pointer; font: inherit; font-size: 12.5px; font-weight: 650; white-space: nowrap; justify-content: center; transition: transform 200ms ease, border-color 200ms ease, background-color 200ms ease; }
.landing-capability-strip__item code { color: var(--copper); font: 600 10px var(--font-mono, monospace); letter-spacing: .02em; transition: color 200ms ease; }
.landing-capability-strip__item:hover { transform: translateY(-2px); border-color: var(--copper); background: color-mix(in srgb, var(--copper) 6%, transparent); }
.landing-scroll-cue { position: absolute; bottom: 18px; left: 50%; transform: translateX(-50%); z-index: 1; display: inline-flex; flex-direction: column; align-items: center; gap: 2px; color: var(--muted); font-size: 9px; font-weight: 750; letter-spacing: .22em; animation: landing-cue 2.4s ease-in-out infinite; }
.landing-scroll-cue .el-icon { color: var(--copper); font-size: 14px; }

/* 通用区块：纸色与深纸色交替分带 */
.landing-section { position: relative; padding: clamp(64px, 8vh, 110px) 0; overflow: hidden; scroll-margin-top: 64px; background: var(--paper); }
.landing-section--panel { background: var(--panel); box-shadow: inset 0 1px 0 var(--line), inset 0 -1px 0 var(--line); }
.landing-section__inner { position: relative; z-index: 1; width: min(1180px, calc(100% - 48px)); margin: 0 auto; }
.landing-section__heading { text-align: center; margin-bottom: clamp(26px, 4vh, 44px); }
.landing-section__heading .landing-eyebrow { margin-bottom: 14px; }
.landing-section__heading h2 { margin: 0; color: var(--ink); font-family: var(--font-serif, serif); font-size: clamp(32px, 3.6vw, 52px); font-weight: 600; letter-spacing: -.045em; }
.landing-section__heading::after { content: ''; display: block; width: 52px; height: 3px; margin: 18px auto 0; border-radius: 2px; background: var(--copper); }
.landing-section__intro { margin: 16px auto 0; max-width: 62ch; color: var(--ink-soft); font-size: 15px; line-height: 1.8; }

.landing-watermark { position: absolute; z-index: 0; top: 50%; right: clamp(-40px, 2vw, 60px); transform: translateY(-50%); color: var(--wm); font-family: var(--font-serif, serif); font-size: clamp(260px, 28vw, 430px); font-weight: 700; line-height: 1; letter-spacing: -.04em; pointer-events: none; user-select: none; }
.landing-watermark--pair { font-size: clamp(180px, 20vw, 320px); letter-spacing: .06em; }
/* 水印视差：随区块进出视口轻微漂移。用 translate 属性叠加在定位 transform 之上，
   原生 view() 时间线驱动，不支持的浏览器自动静止。 */
.landing-watermark { animation: landing-wm-drift linear both; animation-timeline: view(); }
@keyframes landing-wm-drift { from { translate: 0 -30px; } to { translate: 0 30px; } }

/* 滚动渐显：仅支持 IO 的真实浏览器启用，jsdom / 降级环境默认可见。 */
.landing-view.supports-reveal [data-reveal] { opacity: 0; transform: translate3d(0, 26px, 0); transition: opacity 700ms cubic-bezier(.2, .8, .2, 1), transform 700ms cubic-bezier(.2, .8, .2, 1); }
.landing-view.supports-reveal [data-reveal].is-in { opacity: 1; transform: none; }
.landing-view.supports-reveal .landing-info-grid [data-reveal]:nth-child(2) { transition-delay: 70ms; }
.landing-view.supports-reveal .landing-info-grid [data-reveal]:nth-child(3) { transition-delay: 140ms; }
.landing-view.supports-reveal .landing-info-grid [data-reveal]:nth-child(4) { transition-delay: 210ms; }
.landing-view.supports-reveal .landing-info-grid [data-reveal]:nth-child(5) { transition-delay: 280ms; }
.landing-view.supports-reveal .landing-info-grid [data-reveal]:nth-child(6) { transition-delay: 350ms; }

/* 任务闭环布局 */
.landing-mission-layout { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(0, .9fr); gap: 16px; align-items: stretch; }
.landing-info-grid { display: grid; width: 100%; gap: 14px; text-align: left; }
.landing-info-grid--features { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.landing-info-grid--horizon { grid-template-columns: repeat(6, minmax(0, 1fr)); }
.landing-info-grid--horizon .landing-info-card { grid-column: span 2; }
.landing-info-grid--horizon .landing-info-card:nth-child(4), .landing-info-grid--horizon .landing-info-card:nth-child(5) { grid-column: span 3; }
.landing-info-grid--scenes { grid-template-columns: repeat(6, minmax(0, 1fr)); }
.landing-info-grid--scenes .landing-info-card { grid-column: span 2; }
.landing-info-grid--scenes .landing-info-card--featured { grid-column: span 3; }
.landing-info-grid--scenes .landing-info-card:nth-child(2) { grid-column: span 3; }
.landing-info-grid--four { grid-template-columns: repeat(2, minmax(0, 1fr)); max-width: 1060px; margin: 0 auto; }
.landing-info-card { position: relative; display: flex; flex-direction: column; min-height: 0; padding: 20px 22px; box-sizing: border-box; border: 1px solid var(--line); border-radius: 10px; background: var(--card); transition: transform 220ms ease, border-color 220ms ease, box-shadow 220ms ease; }
.landing-info-card:hover { border-color: color-mix(in srgb, var(--copper) 45%, var(--line)); transform: translateY(-4px); box-shadow: 0 14px 30px rgba(38, 35, 31, .08); }
.landing-info-card--featured { border-color: color-mix(in srgb, var(--copper) 40%, var(--line)); background: color-mix(in srgb, var(--copper) 4%, var(--card)); }
.landing-info-card__index, .landing-info-card__meta { display: block; color: var(--copper); font-size: 10px; font-weight: 750; letter-spacing: .14em; }
.landing-info-card h3 { margin: 13px 0 0; color: var(--ink); font-family: var(--font-serif, serif); font-size: 19px; font-weight: 650; letter-spacing: -.02em; }
.landing-info-card p { margin: 9px 0 0; color: var(--ink-soft); font-size: 12.5px; line-height: 1.75; }
.landing-info-card__chips { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 10px; }
.landing-info-card__chips i { padding: 2px 8px; border-radius: 6px; border: 1px solid color-mix(in srgb, var(--copper) 38%, transparent); color: var(--copper-deep); background: color-mix(in srgb, var(--copper) 7%, transparent); font: 650 9.5px var(--font-mono, monospace); font-style: normal; letter-spacing: .03em; }
.landing-info-card__meta { margin-top: auto; padding-top: 12px; color: var(--muted); font-size: 9px; font-weight: 600; letter-spacing: .06em; font-family: var(--font-mono, monospace); }
/* 卡片聚光：--spot-x/y 由指针写入，铜色柔光随鼠标游走（铜色变量随主题自动换色）。 */
.landing-info-card::after, .about-contact-card::after { content: ''; position: absolute; inset: 0; border-radius: inherit; pointer-events: none; opacity: 0; transition: opacity 360ms ease; background: radial-gradient(230px circle at var(--spot-x, 50%) var(--spot-y, 40%), color-mix(in srgb, var(--copper) 10%, transparent), transparent 72%); }
.landing-info-card:hover::after, .about-contact-card:hover::after { opacity: 1; }

/* 生态 Store 徽章带 */
.landing-store-ribbon { display: flex; align-items: center; gap: 14px; margin-top: 16px; padding: 13px 18px; border: 1px solid var(--line); border-radius: 12px; background: var(--card); }
.landing-store-ribbon__label { flex: 0 0 auto; color: var(--copper); font-size: 9.5px; font-weight: 750; letter-spacing: .16em; white-space: nowrap; }
.landing-store-ribbon__items { display: flex; flex: 1 1 auto; align-items: stretch; justify-content: space-between; gap: 6px; min-width: 0; }
.landing-store-ribbon__items span { flex: 1 1 0; min-width: 0; display: grid; gap: 3px; justify-items: center; padding: 7px 4px; border: 1px solid var(--line); border-radius: 8px; background: transparent; transition: border-color 200ms ease, background-color 200ms ease, transform 200ms ease; }
.landing-store-ribbon__items span:hover { transform: translateY(-2px); border-color: var(--copper); background: color-mix(in srgb, var(--copper) 6%, transparent); }
.landing-store-ribbon__items b { color: var(--ink); font: 650 11.5px var(--font-mono, monospace); letter-spacing: .01em; }
.landing-store-ribbon__items small { color: var(--muted); font-size: 10px; }

/* 关于 */
.landing-about__inner { position: relative; z-index: 1; width: min(1180px, calc(100% - 48px)); margin: 0 auto; display: flex; align-items: center; justify-content: space-between; gap: clamp(44px, 9vw, 150px); text-align: left; }
.about-team__copy { flex: 1 1 auto; max-width: 640px; }
.about-team__copy .landing-eyebrow { margin-bottom: 21px; }
.about-team__copy h2 { margin: 0; color: var(--ink); font-family: var(--font-serif, serif); font-size: clamp(54px, 7vw, 106px); font-weight: 600; line-height: .91; letter-spacing: -.06em; }
.about-team__copy h2 span { color: var(--copper); font-weight: 500; }
.about-team__lead { margin: 26px 0 0; color: var(--ink); font-size: clamp(18px, 1.5vw, 23px); font-weight: 560; letter-spacing: -.03em; }
.about-team__note { max-width: 470px; margin: 14px 0 0; color: var(--ink-soft); font-size: 13.5px; line-height: 1.85; }
.about-team__stack { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 22px; }
.about-team__stack span { padding: 4px 11px; border-radius: 999px; border: 1px solid var(--line); color: var(--ink-soft); background: var(--card); font: 650 10.5px var(--font-mono, monospace); letter-spacing: .04em; transition: transform 200ms ease, border-color 200ms ease, color 200ms ease; }
.about-team__stack span:hover { transform: translateY(-2px); border-color: color-mix(in srgb, var(--copper) 45%, var(--line)); color: var(--ink); }
.about-contact-card { position: relative; width: min(480px, 100%); min-height: 350px; flex: 0 0 auto; overflow: hidden; padding: 33px 36px 31px; box-sizing: border-box; border: 1px solid var(--line); border-radius: 12px; background: var(--card); transition: transform 280ms cubic-bezier(.22, .78, .24, 1), box-shadow 280ms ease, border-color 280ms ease; }
.about-contact-card::before { content: ''; position: absolute; top: 0; left: 36px; width: 44px; height: 3px; border-radius: 0 0 3px 3px; background: var(--copper); }
.about-contact-card:hover { border-color: color-mix(in srgb, var(--copper) 45%, var(--line)); box-shadow: 0 14px 30px rgba(38, 35, 31, .08); transform: translateY(-4px); }
.about-contact-card__top { display: flex; align-items: center; justify-content: space-between; color: var(--copper); font-size: 11px; font-weight: 760; letter-spacing: .2em; }
/* 联系卡右上角的小印章：呼应全页「弈」水印母题，悬停时随卡片轻转。 */
.about-contact-card__seal { width: 27px; height: 27px; display: grid; place-items: center; border: 1px solid color-mix(in srgb, var(--copper) 55%, transparent); border-radius: 8px; color: var(--copper); background: color-mix(in srgb, var(--copper) 7%, transparent); font: 600 14px/1 var(--font-serif, serif); font-style: normal; letter-spacing: 0; transition: transform 480ms cubic-bezier(.34, 1.56, .64, 1); }
.about-contact-card:hover .about-contact-card__seal { transform: rotate(8deg); }
/* 信息行改编辑部式排版：小标签在上、衬线值在下，比单行两端对齐更满。 */
.about-contact-card__item { display: flex; flex-direction: column; gap: 5px; padding: 15px 2px 14px; border-bottom: 1px solid var(--line); transition: background-color 220ms ease; }
.about-contact-card__item:first-of-type { margin-top: 14px; border-top: 1px solid var(--line); }
.about-contact-card__label { color: var(--muted); font: 700 10px var(--font-mono, monospace); letter-spacing: .14em; }
.about-contact-card__value { color: var(--ink); font-family: var(--font-serif, serif); font-size: 20px; font-weight: 600; letter-spacing: -.01em; }
.about-contact-card__hint { margin: 18px 0 0; color: var(--ink-soft); font-size: 13px; line-height: 1.75; }
.about-team__cta { width: 100%; min-height: 50px; padding: 0 24px; justify-content: center; gap: 12px; font-size: 13px; }
.about-contact-card .about-team__cta { margin-top: 20px; }
.about-team__cta:hover { box-shadow: 0 14px 28px rgba(193, 95, 60, .28); }
.landing-cta--small { margin-top: 34px; }

/* 页脚 */
.landing-footer { position: relative; z-index: 1; display: flex; align-items: center; justify-content: space-between; gap: 16px; width: min(1180px, calc(100% - 48px)); margin: 0 auto; padding: 26px 0 30px; border-top: 1px solid var(--line); color: var(--muted); }
.landing-footer__brand { color: var(--ink); font-size: 13px; font-weight: 700; text-decoration: none; letter-spacing: -.01em; }
.landing-footer__meta { font-size: 10.5px; letter-spacing: .06em; }
.landing-footer__top { width: 38px; height: 38px; display: grid; place-items: center; border: 1px solid var(--line); border-radius: 999px; color: var(--ink-soft); background: var(--card); cursor: pointer; transition: border-color 200ms ease, transform 200ms ease, color 200ms ease; }
.landing-footer__top:hover { transform: translateY(-2px); border-color: var(--copper); color: var(--copper-deep); }

/* 深色主题：暖炭纸 + 象牙墨 + 提亮铜 */
.landing-view.is-theme-dark {
  --paper: #1f1c19;
  --panel: #252019;
  --card: #2a251f;
  --ink: #f2ede4;
  --ink-soft: #c9bfad;
  --muted: #9a8f7e;
  --line: #3a342b;
  --line-strong: rgba(242, 237, 228, .28);
  --copper: #d97757;
  --copper-deep: #e8926f;
  --success: #8fbf9a;
  --wm: rgba(242, 237, 228, .05);
  --grid: rgba(220, 200, 160, .05);
  --grid-dot: rgba(220, 200, 160, .13);
  --header-bg: rgba(30, 27, 23, .9);
  --header-border: rgba(255, 255, 255, .07);
  --header-shadow: 0 10px 26px rgba(24, 19, 12, .18), inset 0 1px 0 rgba(255, 255, 255, .06);
  --header-shadow-scrolled: 0 18px 44px rgba(24, 19, 12, .3), inset 0 1px 0 rgba(255, 255, 255, .07);
  color-scheme: dark;

  .landing-cta { color: #1f1c19; background: var(--ink); border-color: var(--ink); box-shadow: 0 10px 22px rgba(0, 0, 0, .3); }
  .landing-cta:hover { color: #1f1c19; background: var(--copper); border-color: var(--copper); box-shadow: 0 14px 28px rgba(0, 0, 0, .36); }
  .landing-cta--ghost { color: var(--ink); background: transparent; border-color: var(--line-strong); }
  .landing-cta--ghost:hover { color: var(--copper); border-color: var(--copper); }
  .landing-capability-strip__item:hover, .landing-store-ribbon__items span:hover { background: color-mix(in srgb, var(--copper) 12%, transparent); }
  .landing-info-card:hover { box-shadow: 0 14px 30px rgba(0, 0, 0, .22); }
  .landing-info-card__chips i { color: var(--copper-deep); }
  .about-contact-card:hover { box-shadow: 0 14px 30px rgba(0, 0, 0, .22); }
  & :deep(.agent-stage__status) { border-color: var(--line); color: var(--ink-soft); background: color-mix(in srgb, var(--card) 88%, transparent); }
  & :deep(.agent-stage__prompt) { border-color: var(--line); color: var(--ink-soft); background: color-mix(in srgb, var(--card) 88%, transparent); }
  & :deep(.agent-controls) { border-color: var(--line); background: var(--card); box-shadow: 0 18px 40px rgba(0, 0, 0, .3); }
  & :deep(.agent-control) { border-color: var(--line); color: var(--ink-soft); background: var(--paper); }
  & :deep(.agent-control:hover), & :deep(.agent-control[aria-pressed='true']) { color: var(--copper-deep); background: color-mix(in srgb, var(--copper) 14%, var(--card)); }
  & :deep(.agent-controls__label), & :deep(.agent-controls__hint) { color: var(--muted); }
  & :deep(.agent-conversation) { border-color: var(--line); color: var(--ink-soft); background: var(--card); }
  & :deep(.agent-conversation p) { color: var(--ink-soft); }
}

/* 星弈风格：星空 · 青紫玻璃（用户可在灵动岛风格菜单切换，与纸弈并存）。 */
.landing-view.is-style-star {
  --panel: rgba(255, 255, 255, .18);
  --card: rgba(255, 255, 255, .46);
  --ink: #173963;
  --ink-soft: #5e7da9;
  --muted: #6b85ad;
  --line: rgba(255, 255, 255, .78);
  --line-strong: rgba(36, 143, 240, .3);
  --copper: #2b93ec;
  --copper-deep: #6352f5;
  --success: #2fa27a;
  --wm: rgba(35, 84, 138, .07);
  --grid: rgba(73, 139, 200, .035);
  --grid-dot: rgba(73, 139, 200, .16);
  --header-bg: rgba(255, 255, 255, .52);
  --header-border: rgba(255, 255, 255, .8);
  --header-shadow: 0 12px 28px rgba(73, 125, 207, .12), inset 0 1px 0 rgba(255, 255, 255, .9);
  --header-shadow-scrolled: 0 18px 44px rgba(73, 125, 207, .18), inset 0 1px 0 rgba(255, 255, 255, .95);
  background: #dcecff url('/bg.webp') center / cover no-repeat;
}
.landing-view.is-style-star::before { content: ''; position: absolute; inset: 0; z-index: 0; pointer-events: none; background: linear-gradient(112deg, rgba(249, 253, 255, .88) 0%, rgba(243, 250, 255, .6) 38%, rgba(225, 240, 255, .2) 72%, rgba(216, 232, 255, .36) 100%); }
.landing-view.is-style-star .landing-section { background: transparent; }
.landing-view.is-style-star .landing-section--panel { background: var(--panel); box-shadow: none; }
.landing-view.is-style-star .landing-info-card,
.landing-view.is-style-star .landing-capability-strip,
.landing-view.is-style-star .landing-store-ribbon,
.landing-view.is-style-star .about-contact-card { -webkit-backdrop-filter: blur(16px) saturate(125%); backdrop-filter: blur(16px) saturate(125%); }
.landing-view.is-style-star .landing-info-card { border-color: rgba(255, 255, 255, .78); background: linear-gradient(140deg, rgba(255, 255, 255, .46), rgba(224, 241, 255, .26)); box-shadow: 0 18px 38px rgba(73, 125, 207, .1), inset 0 1px 0 rgba(255, 255, 255, .86); }
.landing-view.is-style-star .landing-info-card:hover { border-color: rgba(84, 178, 239, .5); background: linear-gradient(140deg, rgba(255, 255, 255, .62), rgba(219, 238, 255, .38)); box-shadow: 0 22px 44px rgba(73, 125, 207, .15), inset 0 1px 0 rgba(255, 255, 255, .92); }
.landing-view.is-style-star .landing-info-card--featured { border-color: rgba(102, 85, 244, .34); background: linear-gradient(140deg, rgba(238, 240, 255, .5), rgba(219, 238, 255, .3)); }
.landing-view.is-style-star .landing-capability-strip { border-color: rgba(255, 255, 255, .76); background: rgba(255, 255, 255, .34); box-shadow: 0 14px 30px rgba(73, 125, 207, .09), inset 0 1px 0 rgba(255, 255, 255, .82); }
.landing-view.is-style-star .landing-store-ribbon { border-color: rgba(255, 255, 255, .76); background: rgba(255, 255, 255, .4); box-shadow: 0 14px 30px rgba(73, 125, 207, .09), inset 0 1px 0 rgba(255, 255, 255, .86); }
.landing-view.is-style-star .about-contact-card { border-color: rgba(255, 255, 255, .76); background: radial-gradient(circle at 12% 0%, rgba(255, 255, 255, .72), transparent 32%), radial-gradient(circle at 93% 88%, rgba(151, 211, 255, .22), transparent 42%), linear-gradient(145deg, rgba(255, 255, 255, .66), rgba(225, 241, 255, .34)); box-shadow: 0 32px 70px rgba(69, 122, 193, .17), 0 10px 26px rgba(122, 176, 225, .11), inset 0 1px 0 rgba(255, 255, 255, .96); }
.landing-view.is-style-star .about-team__stack span { border-color: rgba(107, 148, 194, .22); background: rgba(255, 255, 255, .34); }
.landing-view.is-style-star .landing-cta { border: 0; color: #fff; background: linear-gradient(105deg, #28a9f3, #6352f5); box-shadow: 0 15px 28px rgba(70, 116, 239, .24), inset 0 1px 0 rgba(255, 255, 255, .65); }
.landing-view.is-style-star .landing-cta:hover { background: linear-gradient(105deg, #28a9f3, #6352f5); filter: brightness(1.07); box-shadow: 0 20px 36px rgba(70, 116, 239, .32), inset 0 1px 0 rgba(255, 255, 255, .72); }
.landing-view.is-style-star .landing-cta--ghost { color: #2c5789; background: rgba(255, 255, 255, .38); border-color: transparent; box-shadow: inset 0 0 0 1px rgba(60, 126, 199, .32), 0 8px 20px rgba(70, 122, 193, .1); }
.landing-view.is-style-star .landing-cta--ghost:hover { color: #1c4877; background: rgba(255, 255, 255, .66); box-shadow: inset 0 0 0 1px rgba(60, 126, 199, .55), 0 12px 26px rgba(70, 122, 193, .16); }
/* 演示面板跟随星弈调色（CSS 变量穿透子组件根节点） */
.landing-view.is-style-star .mission-demo {
  --demo-ink: #1c3f6e;
  --demo-ink-soft: #5e7ca8;
  --demo-muted: #7d97bb;
  --demo-line: rgba(96, 143, 199, .26);
  --demo-card: rgba(255, 255, 255, .5);
  --demo-card-strong: rgba(255, 255, 255, .88);
  --demo-accent: #2b93ec;
  --demo-tan: #6655f4;
  --demo-success: #2fa27a;
  --demo-on-ink: #ffffff;
  --demo-planning: #b98a2f;
}
/* 星弈 · 暗色 */
.landing-view.is-style-star.is-theme-dark {
  --panel: rgba(20, 44, 80, .25);
  --card: rgba(17, 38, 70, .68);
  --ink: #f1f6ff;
  --ink-soft: #a8bdd8;
  --muted: #9aafd0;
  --line: rgba(130, 184, 237, .26);
  --line-strong: rgba(109, 189, 255, .4);
  --copper: #39c4f1;
  --copper-deep: #9b78ff;
  --success: #6fd0a5;
  --wm: rgba(141, 178, 235, .09);
  --grid: rgba(113, 166, 237, .05);
  --grid-dot: rgba(113, 166, 237, .22);
  --header-bg: rgba(8, 14, 28, .88);
  --header-border: rgba(130, 184, 237, .18);
  --header-shadow: 0 10px 26px rgba(0, 0, 0, .3), inset 0 1px 0 rgba(220, 239, 255, .08);
  --header-shadow-scrolled: 0 18px 44px rgba(0, 0, 0, .42), inset 0 1px 0 rgba(220, 239, 255, .1);
  color-scheme: dark;
  background: #050914 url('/darkbg.webp') center / cover no-repeat;
}
.landing-view.is-style-star.is-theme-dark::before { background: linear-gradient(112deg, rgba(3, 7, 15, .92) 0%, rgba(3, 10, 22, .72) 40%, rgba(3, 7, 15, .4) 100%); }
.landing-view.is-style-star.is-theme-dark .landing-info-card { border-color: rgba(130, 184, 237, .26); background: linear-gradient(140deg, rgba(17, 38, 70, .68), rgba(5, 15, 30, .58)); box-shadow: 0 18px 38px rgba(0, 0, 0, .22), inset 0 1px 0 rgba(220, 239, 255, .14); }
.landing-view.is-style-star.is-theme-dark .landing-info-card:hover { border-color: rgba(100, 192, 255, .66); background: linear-gradient(140deg, rgba(22, 52, 91, .8), rgba(7, 20, 40, .7)); box-shadow: 0 22px 44px rgba(0, 0, 0, .3), inset 0 1px 0 rgba(220, 239, 255, .18); }
.landing-view.is-style-star.is-theme-dark .landing-info-card--featured { border-color: rgba(155, 120, 255, .42); background: linear-gradient(140deg, rgba(34, 30, 74, .8), rgba(12, 16, 40, .7)); }
.landing-view.is-style-star.is-theme-dark .landing-capability-strip, .landing-view.is-style-star.is-theme-dark .landing-store-ribbon { border-color: rgba(130, 184, 237, .26); background: rgba(10, 26, 48, .5); box-shadow: 0 14px 30px rgba(0, 0, 0, .2), inset 0 1px 0 rgba(220, 239, 255, .12); }
.landing-view.is-style-star.is-theme-dark .about-contact-card { border-color: rgba(130, 184, 237, .3); background: radial-gradient(circle at 12% 0%, rgba(71, 164, 235, .22), transparent 32%), radial-gradient(circle at 93% 88%, rgba(139, 108, 255, .2), transparent 42%), linear-gradient(145deg, rgba(18, 42, 76, .78), rgba(5, 15, 30, .66)); box-shadow: 0 32px 70px rgba(0, 0, 0, .3), inset 0 1px 0 rgba(220, 239, 255, .16); }
.landing-view.is-style-star.is-theme-dark .about-team__stack span { border-color: rgba(130, 184, 237, .28); color: #c3d6ee; background: rgba(13, 32, 58, .55); }
.landing-view.is-style-star.is-theme-dark .landing-cta { color: #fff; }
.landing-view.is-style-star.is-theme-dark .landing-cta--ghost { color: #cfe2fb; background: rgba(12, 30, 56, .5); box-shadow: inset 0 0 0 1px rgba(109, 189, 255, .34), 0 8px 20px rgba(0, 0, 0, .22); }
.landing-view.is-style-star.is-theme-dark .landing-cta--ghost:hover { color: #f1f6ff; background: rgba(20, 46, 82, .78); box-shadow: inset 0 0 0 1px rgba(109, 189, 255, .6), 0 12px 26px rgba(0, 0, 0, .3); }
.landing-view.is-style-star.is-theme-dark .mission-demo {
  --demo-ink: #edf4ff;
  --demo-ink-soft: #b9cde6;
  --demo-muted: #8ba4c6;
  --demo-line: rgba(120, 172, 226, .24);
  --demo-card: rgba(15, 36, 66, .6);
  --demo-card-strong: rgba(17, 38, 70, .92);
  --demo-accent: #4db2ff;
  --demo-tan: #a184ff;
  --demo-success: #6fd0a5;
  --demo-on-ink: #edf4ff;
  --demo-planning: #d9b66f;
}

.landing-view.is-desktop-shell { --app-topbar-muted: var(--muted); --app-topbar-hover: color-mix(in srgb, var(--copper) 8%, transparent); --app-topbar-active: color-mix(in srgb, var(--copper) 12%, transparent); --app-topbar-focus-ring: color-mix(in srgb, var(--copper) 45%, transparent); }
.landing-view.is-desktop-shell .landing-header { padding-right: 24px; padding-left: 24px; }
.landing-view.is-desktop-shell .landing-header :deep(.desktop-window-controls) { height: 52px; align-self: center; }
.landing-brand:focus-visible, .landing-nav a:focus-visible, .landing-theme-toggle:focus-visible, .landing-cta:focus-visible, .landing-capability-strip__item:focus-visible, .landing-footer__top:focus-visible { outline: 2px solid color-mix(in srgb, var(--copper) 60%, transparent); outline-offset: 4px; }

@media (max-width: 1060px) {
  .landing-mission-layout { grid-template-columns: 1fr; }
  .landing-info-grid--horizon { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .landing-info-grid--horizon .landing-info-card, .landing-info-grid--horizon .landing-info-card:nth-child(4), .landing-info-grid--horizon .landing-info-card:nth-child(5) { grid-column: auto; }
  .landing-info-grid--scenes { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .landing-info-grid--scenes .landing-info-card, .landing-info-grid--scenes .landing-info-card--featured, .landing-info-grid--scenes .landing-info-card:nth-child(2) { grid-column: auto; }
}

@media (max-width: 860px) {
  .landing-header { width: calc(100% - 24px); gap: 10px; padding: 10px 12px; }
  .landing-nav, .landing-header__note { display: none; }
  .landing-hero { padding-top: 96px; }
  .landing-hero__inner { width: calc(100% - 32px); }
  .landing-hero-row { flex-direction: column; gap: 6px; }
  .landing-hero__copy { width: 100%; }
  .landing-agent-slot { width: min(78vw, 460px); height: min(42vh, 380px); min-width: 0; min-height: 0; margin: 0 auto; }
  .landing-capability-strip { flex-wrap: wrap; }
  .landing-capability-strip__label { width: 100%; padding: 2px 4px; }
  .landing-capability-strip__item { flex: 1 1 30%; }
  .landing-section__inner, .landing-about__inner, .landing-footer { width: calc(100% - 32px); }
  .landing-about__inner { flex-direction: column; align-items: flex-start; gap: 30px; }
  .about-team__copy { max-width: 100%; }
  .about-contact-card { width: min(100%, 480px); min-height: 0; align-self: center; }
  .landing-watermark { font-size: 240px; top: 8%; transform: none; }
  .landing-scroll-cue { display: none; }
}

@media (max-width: 620px) {
  .landing-info-grid--features, .landing-info-grid--horizon, .landing-info-grid--scenes, .landing-info-grid--four { grid-template-columns: 1fr; }
  .about-contact-card { padding: 28px 24px 26px; }
  .about-contact-card__value { font-size: 17px; }
}

@keyframes landing-content-in { from { opacity: 0; transform: translate3d(0, 26px, 0) scale(.985); } to { opacity: 1; transform: translate3d(0, 0, 0) scale(1); } }
@keyframes landing-nav-pill-in { from { transform: scale(.88); opacity: .35; } to { transform: none; opacity: 1; } }
@keyframes landing-cue { 0%, 100% { transform: translate(-50%, 0); opacity: .9; } 50% { transform: translate(-50%, 7px); opacity: .45; } }

@media (prefers-reduced-motion: reduce) {
  .landing-scroll { scroll-behavior: auto; }
  .landing-hero__copy, .landing-capability-strip, .landing-scroll-cue { animation: none; }
  .landing-view.supports-reveal [data-reveal] { opacity: 1; transform: none; transition: none; }
  .landing-info-card, .landing-cta, .landing-nav a, .landing-nav a::after, .landing-capability-strip__item, .landing-store-ribbon__items span { transition: none; }
  .landing-nav a.is-active { animation: none; }
  .landing-watermark { animation: none; }
}
</style>
