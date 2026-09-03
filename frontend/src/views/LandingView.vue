<template>
  <main ref="landingRoot" class="landing-view" :class="{ 'is-desktop-shell': desktopShell }" @wheel="handleWheel">
    <header class="landing-header" v-bind="dragRegionProps" aria-label="应用窗口标题栏">
      <a class="landing-brand" href="/" aria-label="知弈 AgentOS 首页" @click.prevent="goHome">
        <span class="landing-brand__logo"><img src="/logo.png" alt="" aria-hidden="true" /></span>
        <span>知弈 <strong>AgentOS</strong></span>
      </a>

      <nav class="landing-nav" aria-label="主导航">
        <a v-for="item in navigation" :key="item.id" :class="{ 'is-active': activeSection === item.id }" :href="`#${item.id}`" @click.prevent="scrollToSection(item.id)">{{ item.label }}</a>
      </nav>

      <span class="landing-header__note">More Agents <i aria-hidden="true">·</i> More Possibilities</span>

      <DesktopWindowControls v-if="desktopShell" />
    </header>

    <section id="home" class="landing-hero" aria-labelledby="landing-title">
      <div class="landing-hero__copy">
        <p class="landing-eyebrow">COLLECTIVE INTELLIGENCE</p>
        <h1 id="landing-title">知弈 <span>AgentOS</span></h1>
        <h2>让智能体成为协作者</h2>
        <p class="landing-lead">理解、规划、执行，一条智能工作链。</p>

        <div class="landing-capabilities" aria-label="产品能力">
          <article v-for="capability in capabilities" :key="capability.title" class="capability-card">
            <div class="capability-card__top">
              <span class="capability-card__index">{{ capability.index }}</span>
              <span class="capability-card__icon" aria-hidden="true">
              <el-icon><component :is="capability.icon" /></el-icon>
              </span>
            </div>
            <strong>{{ capability.title }}</strong>
            <small>{{ capability.subtitle }}</small>
          </article>
        </div>

        <button class="landing-cta" type="button" data-testid="landing-cta" @click="goToLogin">
          探索知弈 AgentOS
          <el-icon aria-hidden="true"><ArrowRight /></el-icon>
        </button>
      </div>

      <div class="landing-orbit-label landing-orbit-label--top" aria-hidden="true">
        <span class="landing-orbit-label__icon"><el-icon><Connection /></el-icon></span>
        <span><b>Multi-Agent</b><small>协同智能体 · 06 active</small></span>
        <i class="landing-orbit-label__signal"></i>
      </div>
      <div class="landing-orbit-label landing-orbit-label--right" aria-hidden="true">
        <span class="landing-orbit-label__icon"><el-icon><Cpu /></el-icon></span>
        <span><b>Heterogeneous</b><small>异构资源 · ready</small></span>
        <i class="landing-orbit-label__signal"></i>
      </div>
      <div class="landing-orbit-label landing-orbit-label--bottom" aria-hidden="true">
        <span class="landing-orbit-label__icon"><el-icon><MagicStick /></el-icon></span>
        <span><b>Self-Evolution</b><small>持续学习 · improving</small></span>
        <i class="landing-orbit-label__signal"></i>
      </div>
      <div class="landing-orbit-label landing-orbit-label--left-bottom" aria-hidden="true">
        <span class="landing-orbit-label__icon"><el-icon><Operation /></el-icon></span>
        <span><b>Dynamic Planning</b><small>动态规划 · online</small></span>
        <i class="landing-orbit-label__signal"></i>
      </div>
      <div class="landing-scroll-hint" data-testid="landing-scroll-hint" aria-hidden="true">
        <span class="landing-scroll-hint__line"></span>
        <span>SCROLL TO EXPLORE</span>
        <el-icon><ArrowDown /></el-icon>
      </div>
    </section>

    <section id="features" class="landing-section" aria-labelledby="features-title">
      <p class="landing-eyebrow">HOW IT WORKS</p>
      <h2 id="features-title">从目标，到结果</h2>
      <p class="landing-section__intro">把复杂任务交给一组会协作的智能体。</p>
      <div class="landing-info-grid landing-info-grid--three">
        <article v-for="item in workflowFeatures" :key="item.title" class="landing-info-card">
          <span class="landing-info-card__index">{{ item.index }}</span>
          <h3>{{ item.title }}</h3>
          <p>{{ item.description }}</p>
          <span class="landing-info-card__meta">{{ item.meta }}</span>
        </article>
      </div>
    </section>

    <section id="ecosystem" class="landing-section" aria-labelledby="ecosystem-title">
      <p class="landing-eyebrow">CONNECTED ECOSYSTEM</p>
      <h2 id="ecosystem-title">连接模型、知识与智能体</h2>
      <p class="landing-section__intro">模型、知识、工具，需要什么就调用什么。</p>
      <div class="landing-info-grid landing-info-grid--two">
        <article v-for="item in ecosystemFeatures" :key="item.title" class="landing-info-card">
          <span class="landing-info-card__index">{{ item.index }}</span>
          <h3>{{ item.title }}</h3>
          <p>{{ item.description }}</p>
          <span class="landing-info-card__meta">{{ item.meta }}</span>
        </article>
      </div>
    </section>

    <section id="about" class="landing-section landing-section--last" aria-labelledby="about-title">
      <p class="landing-eyebrow">ABOUT ZHIYI</p>
      <h2 id="about-title">让智能真正参与工作</h2>
      <p class="landing-section__intro">清晰、协作、可交付。</p>
      <div class="about-ribbon" aria-label="知弈 AgentOS 产品原则">
        <span><b>可理解</b><small>每一步都有上下文</small></span>
        <span><b>可协作</b><small>每个角色都有边界</small></span>
        <span><b>可交付</b><small>每个结果都可追踪</small></span>
      </div>
      <button class="landing-cta landing-cta--small" type="button" @click="goToLogin">立即进入</button>
    </section>
  </main>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { ArrowDown, Connection, Cpu, MagicStick, Operation, ArrowRight } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import DesktopWindowControls from '@window-controls'
import { isDesktop, platform } from '@/platform'

const router = useRouter()
const desktopShell = isDesktop()
const dragRegionProps = platform.dragRegionProps
const landingRoot = ref<HTMLElement | null>(null)
const activeSection = ref('home')
const navigation = [
  { id: 'home', label: '首页' },
  { id: 'features', label: '功能' },
  { id: 'ecosystem', label: '生态' },
  { id: 'about', label: '关于' }
]

const capabilities = [
  { index: '01', title: '多智能体协作', subtitle: 'Multi-Agent', icon: Connection },
  { index: '02', title: '动态任务规划', subtitle: 'Dynamic Planning', icon: ArrowRight },
  { index: '03', title: '异构资源调度', subtitle: 'Heterogeneous', icon: Cpu },
  { index: '04', title: '自进化学习', subtitle: 'Self-Evolution', icon: MagicStick }
]

const workflowFeatures = [
  { index: '01 / UNDERSTAND', title: '理解与规划', description: '拆解目标，建立任务路径。', meta: 'Context → Plan' },
  { index: '02 / COLLABORATE', title: '协作与执行', description: '明确分工，并行推进。', meta: 'Roles → Actions' },
  { index: '03 / DELIVER', title: '复核与交付', description: '保留依据，交付结果。', meta: 'Evidence → Outcome' }
]

const ecosystemFeatures = [
  { index: 'MODEL LAYER', title: '模型与资源', description: '统一管理模型与工具。', meta: 'Every capability, one place' },
  { index: 'KNOWLEDGE LAYER', title: '知识与工作流', description: '让知识进入真实工作流。', meta: 'Knowledge → Action' }
]

let sectionObserver: IntersectionObserver | null = null

onMounted(() => {
  if (typeof IntersectionObserver === 'undefined') return
  sectionObserver = new IntersectionObserver((entries) => {
    const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0]
    if (visible) activeSection.value = visible.target.id
  }, { rootMargin: '-24% 0px -58% 0px', threshold: [0.1, 0.35, 0.6] })
  navigation.forEach(item => {
    const section = document.getElementById(item.id)
    if (section) sectionObserver?.observe(section)
  })
})

onUnmounted(() => sectionObserver?.disconnect())

let wheelLocked = false
let wheelUnlockTimer: number | undefined

const handleWheel = (event: WheelEvent) => {
  const root = landingRoot.value
  if (!root || Math.abs(event.deltaY) < 8) return
  const currentIndex = navigation.findIndex(item => item.id === activeSection.value)
  const nextIndex = currentIndex + (event.deltaY > 0 ? 1 : -1)
  if (currentIndex < 0 || nextIndex < 0 || nextIndex >= navigation.length) return
  event.preventDefault()
  if (wheelLocked) return
  const target = document.getElementById(navigation[nextIndex].id)
  if (!target) return
  wheelLocked = true
  activeSection.value = navigation[nextIndex].id
  root.scrollTo({
    top: target.offsetTop,
    behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'
  })
  window.clearTimeout(wheelUnlockTimer)
  wheelUnlockTimer = window.setTimeout(() => { wheelLocked = false }, 680)
}

onUnmounted(() => window.clearTimeout(wheelUnlockTimer))

const goToLogin = () => router.push('/login')

const goHome = () => router.push('/')

// 桌面端是 hash 路由：原生锚点 href="#features" 会把 URL 从 #/ 顶成 #/features，
// 路由失配后整个落地页被顶掉。这里统一拦截，改为程序化滚动，
// history 模式（Web）与 hash 模式（桌面）行为一致。
const scrollToSection = (id: string) => {
  activeSection.value = id
  document.getElementById(id)?.scrollIntoView({
    behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'
  })
}
</script>

<style scoped lang="scss">
.landing-view {
  --ink: #102a56;
  --muted-ink: #6b85ad;
  --blue: #248ff0;
  --purple: #6655f4;
  /* 应用壳的 html/body/#app 全是 overflow:hidden，页面高度若用 min-height 会撑破
     #app 被 canvas 裁切——这里必须自封顶成为真正的滚动容器，
     滚轮换段、scroll-snap 与锚点导航才有载体。 */
  height: 100vh;
  height: 100dvh;
  overflow-x: hidden;
  overflow-y: auto;
  color: var(--ink);
  background: #d9eaff;
  background-image: url('/bg.jpeg');
  background-position: center center;
  background-repeat: no-repeat;
  background-size: auto 100vh;
  background-attachment: fixed;
  scroll-behavior: smooth;
  scroll-snap-type: y mandatory;
}

.landing-view::before {
  content: '';
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background: linear-gradient(90deg, rgba(246, 251, 255, .88) 0%, rgba(246, 251, 255, .5) 33%, rgba(236, 245, 255, .06) 72%), linear-gradient(180deg, rgba(255,255,255,.2), transparent 45%);
}

.landing-header,
.landing-hero,
.landing-section { position: relative; z-index: 1; }
.landing-hero, .landing-section { scroll-snap-align: start; scroll-snap-stop: always; }

.landing-header {
  width: min(100% - 96px, 1920px);
  min-height: 88px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 28px;
}

.landing-brand {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  color: var(--ink);
  font-size: 21px;
  font-weight: 650;
  letter-spacing: -.02em;
  text-decoration: none;
  white-space: nowrap;
}

.landing-brand strong { font-weight: 500; }
.landing-brand__logo { width: 36px; height: 36px; display: block; }
.landing-brand__logo img { width: 100%; height: 100%; display: block; object-fit: contain; }

.landing-nav { display: flex; align-items: center; gap: clamp(24px, 3vw, 52px); }
.landing-nav a {
  position: relative;
  min-height: 44px;
  display: inline-flex;
  align-items: center;
  color: var(--muted-ink);
  font-size: 14px;
  text-decoration: none;
  transition: color 180ms ease;
}
.landing-nav a::after {
  content: '';
  position: absolute;
  right: 0;
  bottom: 7px;
  left: 0;
  height: 2px;
  border-radius: 99px;
  background: linear-gradient(90deg, var(--blue), var(--purple));
  opacity: 0;
  transform: scaleX(.4);
  transition: opacity 180ms ease, transform 180ms ease;
}
.landing-nav a:hover,
.landing-nav a.is-active { color: var(--ink); }
.landing-nav a:hover::after,
.landing-nav a.is-active::after { opacity: 1; transform: scaleX(1); }

.landing-header__note { color: #7b96bd; font-size: 11px; letter-spacing: .11em; white-space: nowrap; }
.landing-header__note i { padding: 0 10px; font-style: normal; color: var(--blue); }

.landing-hero {
  min-height: calc(100vh - 88px);
  min-height: calc(100dvh - 88px);
  width: min(100% - 96px, 1920px);
  margin: 0 auto;
  display: flex;
  align-items: center;
  padding: 0 0 70px;
  box-sizing: border-box;
}

.landing-hero__copy { width: min(590px, 46vw); margin-left: 2%; margin-top: -6vh; }
.landing-eyebrow { margin: 0 0 21px; color: #6e8fc0; font-size: 11px; font-weight: 700; letter-spacing: .25em; }
.landing-hero h1 { margin: 0; color: var(--ink); font-size: clamp(54px, 5vw, 86px); font-weight: 520; line-height: .98; letter-spacing: -.065em; }
.landing-hero h1 span { font-weight: 450; }
.landing-hero h2 { margin: 23px 0 0; color: #183665; font-size: clamp(26px, 2.2vw, 39px); font-weight: 520; letter-spacing: -.04em; }
.landing-lead { margin: 24px 0 0; color: #5e7da9; font-size: 16px; line-height: 1.7; }

.landing-capabilities { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 40px; }
.capability-card { min-width: 0; min-height: 150px; padding: 14px 13px 13px; box-sizing: border-box; border: 1px solid rgba(255,255,255,.62); border-radius: 15px; background: rgba(255,255,255,.25); box-shadow: 0 10px 24px rgba(80,128,198,.06), inset 0 1px 0 rgba(255,255,255,.6); backdrop-filter: blur(10px); transition: transform 180ms ease, background-color 180ms ease, box-shadow 180ms ease; }
.capability-card:hover { transform: translateY(-3px); background: rgba(255,255,255,.46); box-shadow: 0 16px 28px rgba(80,128,198,.12), inset 0 1px 0 rgba(255,255,255,.78); }
.capability-card__top { display: flex; align-items: center; justify-content: space-between; }
.capability-card__index { color: #7d9ac2; font-size: 9px; font-weight: 750; letter-spacing: .13em; }
.capability-card__icon { width: 28px; height: 28px; display: grid; place-items: center; border: 1px solid rgba(78,160,241,.18); border-radius: 9px; color: var(--blue); background: rgba(228,246,255,.72); font-size: 18px; }
.capability-card strong, .capability-card small { display: block; }
.capability-card strong { margin-top: 16px; color: #183866; font-size: 12px; font-weight: 750; white-space: nowrap; }
.capability-card small { margin-top: 4px; color: #7190bb; font-size: 9px; letter-spacing: .04em; }

.landing-cta { min-height: 52px; margin-top: 48px; padding: 0 28px; display: inline-flex; align-items: center; gap: 20px; border: 0; border-radius: 999px; color: white; background: linear-gradient(105deg, #28a9f3, #6352f5); box-shadow: 0 15px 28px rgba(70, 116, 239, .28), inset 0 1px 0 rgba(255,255,255,.65); font: inherit; font-size: 14px; font-weight: 700; cursor: pointer; transition: transform 180ms ease, box-shadow 180ms ease; }
.landing-cta:hover { transform: translateY(-2px); box-shadow: 0 18px 34px rgba(70, 116, 239, .36), inset 0 1px 0 rgba(255,255,255,.65); }
.landing-cta:active { transform: translateY(0); }
.landing-cta .el-icon { font-size: 18px; }

.landing-orbit-label { position: absolute; min-width: 180px; padding: 12px 40px 12px 16px; display: flex; align-items: center; gap: 11px; border: 1px solid rgba(255,255,255,.72); border-radius: 12px; background: rgba(255,255,255,.36); box-shadow: 0 12px 26px rgba(73, 125, 207, .08), inset 0 1px 0 rgba(255,255,255,.8); backdrop-filter: blur(10px); transform: rotate(-4deg); }
.landing-orbit-label__icon { width: 27px; height: 27px; display: grid; place-items: center; border-radius: 50%; color: var(--blue); background: rgba(226,245,255,.78); font-size: 17px; }
.landing-orbit-label b, .landing-orbit-label small { display: block; }
.landing-orbit-label b { color: #224370; font-size: 12px; font-weight: 700; }
.landing-orbit-label small { margin-top: 3px; color: #7692b9; font-size: 9px; }
.landing-orbit-label__signal { position: absolute; top: 14px; right: 14px; width: 6px; height: 6px; border-radius: 50%; background: #34c5ee; box-shadow: 0 0 0 4px rgba(52,197,238,.12); }
.landing-orbit-label--top { top: 14%; left: 49%; }
.landing-orbit-label--right { top: 14%; right: 4%; transform: rotate(5deg); }
.landing-orbit-label--bottom { right: 14%; bottom: 18%; transform: rotate(3deg); }
.landing-orbit-label--left-bottom { bottom: 23%; left: 40%; transform: rotate(-3deg); }
.landing-scroll-hint { position: absolute; bottom: 7%; left: 2%; display: flex; align-items: center; gap: 9px; color: #6f8cae; font-size: 9px; font-weight: 700; letter-spacing: .2em; }
.landing-scroll-hint__line { width: 1px; height: 31px; background: linear-gradient(180deg, var(--blue), transparent); }
.landing-scroll-hint .el-icon { color: var(--blue); font-size: 14px; animation: landing-scroll-pulse 1.8s ease-in-out infinite; }
@keyframes landing-scroll-pulse { 0%, 100% { opacity: .45; transform: translateY(-2px); } 50% { opacity: 1; transform: translateY(3px); } }

.landing-section { width: min(1100px, calc(100% - 48px)); margin: 0 auto; padding: 100px 0 120px; text-align: center; }
.landing-section h2 { margin: 0; color: var(--ink); font-size: clamp(28px, 4vw, 52px); font-weight: 520; letter-spacing: -.05em; }
.landing-section__intro { max-width: 620px; margin: 22px auto 0; color: #6884ad; font-size: 16px; line-height: 1.8; }
.landing-info-grid { display: grid; gap: 14px; margin-top: 42px; text-align: left; }
.landing-info-grid--three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.landing-info-grid--two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.landing-info-card { position: relative; min-height: 190px; padding: 24px 24px 21px; box-sizing: border-box; border: 1px solid rgba(255,255,255,.74); border-radius: 18px; background: rgba(255,255,255,.32); box-shadow: 0 14px 30px rgba(73,125,207,.08), inset 0 1px 0 rgba(255,255,255,.78); backdrop-filter: blur(12px); transition: transform 180ms ease, background-color 180ms ease, box-shadow 180ms ease; }
.landing-info-card:hover { transform: translateY(-4px); background: rgba(255,255,255,.5); box-shadow: 0 20px 38px rgba(73,125,207,.13), inset 0 1px 0 rgba(255,255,255,.88); }
.landing-info-card__index, .landing-info-card__meta { display: block; color: #6e91c0; font-size: 10px; font-weight: 750; letter-spacing: .14em; }
.landing-info-card h3 { margin: 28px 0 0; color: #173963; font-size: 21px; font-weight: 650; letter-spacing: -.03em; }
.landing-info-card p { max-width: 300px; margin: 12px 0 0; color: #6884ad; font-size: 13px; line-height: 1.75; }
.landing-info-card__meta { position: absolute; right: 24px; bottom: 21px; color: #8aa5c8; font-size: 9px; font-weight: 600; letter-spacing: .06em; }
.about-ribbon { max-width: 720px; margin: 42px auto 0; padding: 20px 24px; display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; border: 1px solid rgba(255,255,255,.72); border-radius: 18px; background: rgba(255,255,255,.29); box-shadow: 0 14px 30px rgba(73,125,207,.07), inset 0 1px 0 rgba(255,255,255,.8); backdrop-filter: blur(12px); }
.about-ribbon span { position: relative; }
.about-ribbon span + span::before { content: ''; position: absolute; top: 3px; bottom: 3px; left: -8px; width: 1px; background: rgba(115,155,204,.22); }
.about-ribbon b, .about-ribbon small { display: block; }
.about-ribbon b { color: #214572; font-size: 14px; }
.about-ribbon small { margin-top: 6px; color: #7792b8; font-size: 10px; }
.landing-section--last { padding-bottom: 150px; }
.landing-cta--small { margin-top: 36px; }

.landing-brand:focus-visible, .landing-nav a:focus-visible, .landing-cta:focus-visible { outline: 3px solid rgba(36, 143, 240, .5); outline-offset: 4px; }

/* Tauri 隐藏了原生标题栏：桌面 shell 下落地页顶栏兼任窗口拖拽区，右上角承载窗口控制按钮
   （纯 Web 版不渲染桌面 shell）。页面可滚动，顶栏须 sticky 常驻，
   滚到任意区块时拖拽区与窗口按钮仍然可达。窗口控件的取色变量在这里指向
   落地页自己的配色体系，不借用工作台顶栏的灰。 */
.landing-view.is-desktop-shell {
  --app-topbar-muted: var(--muted-ink);
  --app-topbar-hover: rgba(36, 143, 240, .08);
  --app-topbar-active: rgba(36, 143, 240, .13);
  --app-topbar-focus-ring: rgba(36, 143, 240, .45);
}

.landing-view.is-desktop-shell .landing-header {
  position: sticky;
  top: 0;
  z-index: 20;
  width: 100%;
  padding-left: 24px;
  background: linear-gradient(180deg, rgba(246, 251, 255, .92), rgba(246, 251, 255, .78));
  backdrop-filter: blur(14px);
}

.landing-view.is-desktop-shell .landing-header__note { margin-left: auto; }

.landing-view.is-desktop-shell .landing-header :deep(.desktop-window-controls) { height: 52px; align-self: center; }

.landing-view::-webkit-scrollbar { width: 8px; }
.landing-view::-webkit-scrollbar-track { background: rgba(255,255,255,.18); }
.landing-view::-webkit-scrollbar-thumb { border: 2px solid transparent; border-radius: 99px; background: rgba(79,128,199,.36); background-clip: padding-box; }

@media (max-width: 900px) {
  .landing-header, .landing-hero { width: min(100% - 48px, 720px); }
  .landing-header__note { display: none; }
  .landing-hero { align-items: flex-start; padding-top: 12vh; }
  .landing-hero__copy { width: min(560px, 100%); margin-left: 0; }
  .landing-orbit-label { display: none; }
}

@media (max-width: 640px) {
  .landing-header { min-height: 72px; }
  .landing-brand { font-size: 18px; }
  .landing-brand__logo { width: 32px; height: 32px; }
  .landing-nav { gap: 12px; }
  .landing-nav a { font-size: 12px; }
  .landing-hero { min-height: calc(100dvh - 72px); width: calc(100% - 40px); padding-top: 9vh; }
  .landing-eyebrow { font-size: 9px; letter-spacing: .16em; }
  .landing-hero h1 { font-size: clamp(48px, 15vw, 72px); }
  .landing-hero h2 { font-size: 25px; line-height: 1.35; }
  .landing-capabilities { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 10px; margin-top: 36px; }
  .landing-cta { margin-top: 38px; }
  .landing-section { padding: 70px 0 85px; }
}

@media (prefers-reduced-motion: reduce) {
  .landing-view { scroll-behavior: auto; }
  .landing-nav a, .landing-nav a::after, .landing-cta, .capability-card, .landing-info-card { transition: none; }
  .landing-scroll-hint .el-icon { animation: none; }
}
</style>
