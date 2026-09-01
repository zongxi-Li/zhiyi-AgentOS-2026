<template>
  <main class="landing-view">
    <header class="landing-header">
      <a class="landing-brand" href="/" aria-label="知弈 AgentOS 首页">
        <span class="landing-brand__logo"><img src="/logo.png" alt="" aria-hidden="true" /></span>
        <span>知弈 <strong>AgentOS</strong></span>
      </a>

      <nav class="landing-nav" aria-label="主导航">
        <a class="is-active" href="#home">首页</a>
        <a href="#features">功能</a>
        <a href="#ecosystem">生态</a>
        <a href="#about">关于</a>
      </nav>

      <span class="landing-header__note">More Agents <i aria-hidden="true">·</i> More Possibilities</span>
    </header>

    <section id="home" class="landing-hero" aria-labelledby="landing-title">
      <div class="landing-hero__copy">
        <p class="landing-eyebrow">DYNAMIC HETEROGENEOUS AGENT SWARM</p>
        <h1 id="landing-title">知弈 <span>AgentOS</span></h1>
        <h2>动态异构群体智能操作系统</h2>
        <p class="landing-lead">让智能体协作更简单，让复杂问题有更好的解。</p>

        <div class="landing-capabilities" aria-label="产品能力">
          <article v-for="capability in capabilities" :key="capability.title" class="capability-item">
            <span class="capability-item__icon" aria-hidden="true">
              <el-icon><component :is="capability.icon" /></el-icon>
            </span>
            <span>
              <strong>{{ capability.title }}</strong>
              <small>{{ capability.subtitle }}</small>
            </span>
          </article>
        </div>

        <button class="landing-cta" type="button" data-testid="landing-cta" @click="goToLogin">
          探索知弈 AgentOS
          <el-icon aria-hidden="true"><ArrowRight /></el-icon>
        </button>
      </div>

      <div class="landing-orbit-label landing-orbit-label--top" aria-hidden="true">
        <span class="landing-orbit-label__icon"><el-icon><Connection /></el-icon></span>
        <span><b>Multi-Agent</b><small>Collaborative Intelligence</small></span>
      </div>
      <div class="landing-orbit-label landing-orbit-label--right" aria-hidden="true">
        <span class="landing-orbit-label__icon"><el-icon><Cpu /></el-icon></span>
        <span><b>Heterogeneous</b><small>Resource Orchestration</small></span>
      </div>
      <div class="landing-orbit-label landing-orbit-label--bottom" aria-hidden="true">
        <span class="landing-orbit-label__icon"><el-icon><MagicStick /></el-icon></span>
        <span><b>Self-Evolution</b><small>Continuous Learning</small></span>
      </div>
    </section>

    <section id="features" class="landing-section" aria-labelledby="features-title">
      <p class="landing-eyebrow">ONE OPERATING SYSTEM, MANY POSSIBILITIES</p>
      <h2 id="features-title">把每一个复杂任务，变成可协作的执行网络</h2>
      <p>从任务理解、动态规划到结果复核，知弈 AgentOS 让专业能力以清晰、可追踪的方式协同工作。</p>
    </section>

    <section id="ecosystem" class="landing-section" aria-labelledby="ecosystem-title">
      <p class="landing-eyebrow">CONNECTED ECOSYSTEM</p>
      <h2 id="ecosystem-title">连接模型、知识与智能体</h2>
      <p>统一管理模型与资源，让不同能力在同一工作流中被发现、调用和持续优化。</p>
    </section>

    <section id="about" class="landing-section landing-section--last" aria-labelledby="about-title">
      <p class="landing-eyebrow">ABOUT ZHIYI</p>
      <h2 id="about-title">让智能真正参与工作</h2>
      <p>知弈 AgentOS 面向真实业务场景，关注协作效率、过程透明度与专业结果质量。</p>
      <button class="landing-cta landing-cta--small" type="button" @click="goToLogin">立即进入</button>
    </section>
  </main>
</template>

<script setup lang="ts">
import { Connection, Cpu, MagicStick, ArrowRight } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const capabilities = [
  { title: '多智能体协作', subtitle: 'Multi-Agent', icon: Connection },
  { title: '动态任务规划', subtitle: 'Dynamic Planning', icon: ArrowRight },
  { title: '异构资源调度', subtitle: 'Heterogeneous', icon: Cpu },
  { title: '自进化学习', subtitle: 'Self-Evolution', icon: MagicStick }
]

const goToLogin = () => router.push('/login')
</script>

<style scoped lang="scss">
.landing-view {
  --ink: #102a56;
  --muted-ink: #6b85ad;
  --blue: #248ff0;
  --purple: #6655f4;
  min-height: 100vh;
  min-height: 100dvh;
  overflow: hidden;
  color: var(--ink);
  background: #d9eaff url('/bg.jpeg') center top / cover fixed no-repeat;
  scroll-behavior: smooth;
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
.landing-lead { margin: 24px 0 0; color: #6e88b0; font-size: 16px; line-height: 1.7; }

.landing-capabilities { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px; margin-top: 48px; }
.capability-item { min-width: 0; display: flex; align-items: flex-start; gap: 9px; color: #183866; }
.capability-item__icon { flex: 0 0 24px; width: 24px; height: 24px; display: grid; place-items: center; color: var(--blue); font-size: 22px; }
.capability-item strong, .capability-item small { display: block; white-space: nowrap; }
.capability-item strong { font-size: 12px; font-weight: 700; }
.capability-item small { margin-top: 5px; color: #7893ba; font-size: 9px; }

.landing-cta { min-height: 52px; margin-top: 48px; padding: 0 28px; display: inline-flex; align-items: center; gap: 20px; border: 0; border-radius: 999px; color: white; background: linear-gradient(105deg, #28a9f3, #6352f5); box-shadow: 0 15px 28px rgba(70, 116, 239, .28), inset 0 1px 0 rgba(255,255,255,.65); font: inherit; font-size: 14px; font-weight: 700; cursor: pointer; transition: transform 180ms ease, box-shadow 180ms ease; }
.landing-cta:hover { transform: translateY(-2px); box-shadow: 0 18px 34px rgba(70, 116, 239, .36), inset 0 1px 0 rgba(255,255,255,.65); }
.landing-cta:active { transform: translateY(0); }
.landing-cta .el-icon { font-size: 18px; }

.landing-orbit-label { position: absolute; min-width: 180px; padding: 12px 16px; display: flex; align-items: center; gap: 11px; border: 1px solid rgba(255,255,255,.72); border-radius: 12px; background: rgba(255,255,255,.36); box-shadow: 0 12px 26px rgba(73, 125, 207, .08), inset 0 1px 0 rgba(255,255,255,.8); backdrop-filter: blur(10px); transform: rotate(-4deg); }
.landing-orbit-label__icon { width: 27px; height: 27px; display: grid; place-items: center; border-radius: 50%; color: var(--blue); background: rgba(226,245,255,.78); font-size: 17px; }
.landing-orbit-label b, .landing-orbit-label small { display: block; }
.landing-orbit-label b { color: #224370; font-size: 12px; font-weight: 700; }
.landing-orbit-label small { margin-top: 3px; color: #7692b9; font-size: 9px; }
.landing-orbit-label--top { top: 14%; left: 49%; }
.landing-orbit-label--right { top: 14%; right: 4%; transform: rotate(5deg); }
.landing-orbit-label--bottom { right: 14%; bottom: 18%; transform: rotate(3deg); }

.landing-section { width: min(900px, calc(100% - 48px)); margin: 0 auto; padding: 100px 0 120px; text-align: center; }
.landing-section h2 { margin: 0; color: var(--ink); font-size: clamp(28px, 4vw, 52px); font-weight: 520; letter-spacing: -.05em; }
.landing-section > p:last-of-type { max-width: 620px; margin: 22px auto 0; color: #6884ad; font-size: 16px; line-height: 1.8; }
.landing-section--last { padding-bottom: 150px; }
.landing-cta--small { margin-top: 36px; }

.landing-brand:focus-visible, .landing-nav a:focus-visible, .landing-cta:focus-visible { outline: 3px solid rgba(36, 143, 240, .5); outline-offset: 4px; }

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
  .landing-nav a, .landing-nav a::after, .landing-cta { transition: none; }
}
</style>
