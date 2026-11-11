import { computed, ref } from 'vue'
import { isDarkColorScheme } from '@/themes/presets'
import { BRAND_PACKS, DEFAULT_BRAND_ID, getBrandPack, isBrandId, type BrandId, type BrandPack } from './brandPacks'

// 品牌标是全局外观状态，与 useTheme 同款模式：模块级 ref 单例 + 启动初始化 +
// localStorage appSettings 持久化。依赖方向单向：useTheme → useBrand，
// 本模块不反向 import useTheme，主题深浅读 root.dataset.colorScheme 并用
// MutationObserver 跟踪其变化，让弈章的深浅色资产变体随主题即时换图。

const activeBrandId = ref<BrandId>(DEFAULT_BRAND_ID)
const isDarkScheme = ref(true)

function readIsDarkScheme(): boolean {
  const schemeId = document.documentElement.dataset.colorScheme
  return typeof schemeId === 'string' ? isDarkColorScheme(schemeId) : true
}

// 主题切换时 useTheme 会重写 root 的 data-color-scheme，监听该属性即可同步换用对应变体。
if (typeof document !== 'undefined' && typeof MutationObserver !== 'undefined') {
  new MutationObserver(() => {
    isDarkScheme.value = readIsDarkScheme()
  }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-color-scheme'] })
}

/** 把按主题切换的变体（弈章）展开进 pack：main/mark/landing 换成当前主题应显示的资产。 */
function resolveThemedPack(pack: BrandPack, isDark: boolean): BrandPack {
  if (!pack.themeAssets) return pack
  const asset = isDark ? pack.themeAssets.dark : pack.themeAssets.light
  return { ...pack, main: asset, mark: asset, landing: asset }
}

function applyBrandVisuals(pack: BrandPack): void {
  isDarkScheme.value = readIsDarkScheme()
  let link = document.querySelector<HTMLLinkElement>("link[rel='icon']")
  if (!link) {
    link = document.createElement('link')
    link.rel = 'icon'
    document.head.appendChild(link)
  }
  link.type = pack.faviconType
  link.href = pack.favicon
}

function setBrand(id: BrandId): void {
  activeBrandId.value = isBrandId(id) ? id : DEFAULT_BRAND_ID
  applyBrandVisuals(getBrandPack(activeBrandId.value))
}

export function useBrand() {
  const activePack = computed(() => resolveThemedPack(getBrandPack(activeBrandId.value), isDarkScheme.value))
  // 设置页 Logo 三选卡用：与 activePack 同口径的主题化预览列表。
  const themedBrandOptions = computed(() => BRAND_PACKS.map((pack) => resolveThemedPack(pack, isDarkScheme.value)))

  return {
    activeBrandId,
    activePack,
    themedBrandOptions,
    brandOptions: BRAND_PACKS,
    setBrand,
    initBrand
  }
}

/** 启动时调用（main.ts，initTheme 之后）：读 appSettings.brand 并应用 favicon 与主题变体。 */
export function initBrand(): void {
  let saved: unknown = null
  const raw = localStorage.getItem('appSettings')
  if (raw) {
    try {
      const parsed = JSON.parse(raw) as { brand?: unknown }
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) saved = parsed.brand
    } catch {
      saved = null
    }
  }
  setBrand(isBrandId(saved) ? saved : DEFAULT_BRAND_ID)
}
