// 品牌标三选一的资产清单。三套标的现役来源：
// - ember（焰标，默认）：2026-11-09 提交 9f96644d 换上的橙色三角标，沿用 public 根路径
//   （/logo.svg、/logo-mark.svg、/logo.webp），保证默认视觉与既有部署逐字节一致。
// - ink（弈章）：2026-11-11 换装用户提供的篆书「弈」位图，SVG 版全数退役。
//   themeAssets 按主题直接切换透明底变体：浅色主题显示黑线 logo-light.png、深色主题
//   显示白线 logo-dark.png（useBrand 跟踪当前配色即时换图，无滤镜反相）；
//   favicon logo-compact.png 是深底白线方章，两种浏览器标签条上都可读。
// - wreath（花环）：2026-11-08 之前退役的旧品牌标，从提交 73d172aa 的 logo.webp 取回。
// ACG 子系统专用标 /acglogo.* 不在此列（brand-spec.md：独立品牌资产，不参与主标适配）。

export type BrandId = 'ember' | 'ink' | 'wreath'

export interface BrandPack {
  id: BrandId
  label: string
  description: string
  /** 大尺寸展示：顶栏、加载态等 */
  main: string
  /** 低干扰水印：空态、编辑器空态、Chat hero */
  mark: string
  /** 落地页大图 */
  landing: string
  /** 浏览器标签页图标（跟随所选标；桌面原生 icon.ico 不跟随） */
  favicon: string
  faviconType: 'image/svg+xml' | 'image/webp' | 'image/png'
  /** 按主题直接切换的全槽位资产变体（弈章专用）：key 为深浅主题，命中后覆盖 main/mark/landing */
  themeAssets?: { light: string; dark: string }
}

export const BRAND_PACKS: BrandPack[] = [
  {
    id: 'ember',
    label: '焰标',
    description: '橙色三角焰形标，当前默认品牌标。',
    main: '/logo.svg',
    mark: '/logo-mark.svg',
    landing: '/logo.webp',
    favicon: '/logo.webp',
    faviconType: 'image/webp'
  },
  {
    id: 'ink',
    label: '弈章',
    description: '篆书「弈」位图：浅色主题显示黑线，深色主题显示白线。',
    main: '/brand/ink/logo-light.png',
    mark: '/brand/ink/logo-light.png',
    landing: '/brand/ink/logo-light.png',
    favicon: '/brand/ink/logo-compact.png',
    faviconType: 'image/png',
    themeAssets: { light: '/brand/ink/logo-light.png', dark: '/brand/ink/logo-dark.png' }
  },
  {
    id: 'wreath',
    label: '花环',
    description: '初代花环标，果实与新芽环绕成环。',
    main: '/brand/wreath/logo.webp',
    mark: '/brand/wreath/logo.webp',
    landing: '/brand/wreath/logo.webp',
    favicon: '/brand/wreath/logo.webp',
    faviconType: 'image/webp'
  }
]

export const DEFAULT_BRAND_ID: BrandId = 'ember'

const BRAND_IDS: BrandId[] = ['ember', 'ink', 'wreath']

export function isBrandId(value: unknown): value is BrandId {
  return typeof value === 'string' && BRAND_IDS.includes(value as BrandId)
}

export function getBrandPack(id: BrandId): BrandPack {
  return BRAND_PACKS.find((pack) => pack.id === id) || BRAND_PACKS[0]
}
