// 运行时实现见同目录 index.js（引擎按 import 顺序挂到 window）。
// 类型只描述组件真正用到的引擎面，不逐字复刻内部字段。

export interface GrokSnapshot {
  state: string
  mode: string
  shape: string
  color: string
  scheme: string
  eyeFrom: number
  eyeTo: number
  spin: number
  tx: number
  ty: number
  squash: number
  blink: number
  overlay: string | null
}

export interface GrokCharacterOptions {
  shape?: string
  color?: string
  scheme?: 'light' | 'dark'
  mode?: 'onboarding' | 'hold'
  state?: string
  onChange?: (snapshot: GrokSnapshot) => void
  loginWrap?: boolean
  followPointer?: boolean
  gazeTarget?: { x: number; y: number } | null
  paused?: boolean
  reduceMotion?: boolean
  badgeColor?: string
  sizePx?: number | null
  eyeColor?: string | null
  emphasis?: boolean
  pose?: Partial<{ turn: number; tilt: number; roll: number; scale: number }>
}

export interface GrokShapeMeta {
  label: string
  path: string
  tiltScale?: number
  beltRadius?: number
  radius?: number
  face: unknown
  top?: number
  bottom?: number
}

export interface GrokPaletteEntry {
  light: string
  dark: string
}

export interface GrokCharacterInstance {
  shapeName: string
  colorId: string
  scheme: string
  mode: string
  state: string
  moodN: number
  snapshot(): GrokSnapshot
  destroy(): void
  setMode(mode: 'onboarding' | 'hold'): void
  setPaused(paused: boolean): void
  setEmphasis(emphasis: boolean): void
  setFollowPointer(follow: boolean): void
  setGazeTarget(point: { x: number; y: number } | null): void
  setShape(name: string): void
  setColor(colorId: string, scheme?: 'light' | 'dark'): void
  setInk(flat: string | null): void
  setEyeColor(color: string | null): void
  setState(name: string, options?: { resetEyes?: boolean }): void
  spinOnce(turns?: number): void
  bounceOnce(): void
  burstOnce(): void
}

export interface GrokMeta {
  groups: Array<{ label: string; states: string[] }>
  onboarding: string[]
  onboardingMs: number
  eyePlaylist: Record<string, number[]>
  springs: Record<string, [number, number]>
  overlays: Record<string, unknown>
}

export interface GrokGeo {
  viewBox: { minX: number; minY: number; width: number; height: number }
  Re: number
  eyes: number[][][]
  shapes: Record<string, GrokShapeMeta>
  palette: Record<string, GrokPaletteEntry>
}

export const GROK_GEO: GrokGeo
export const GROK_META: GrokMeta
export const GrokCharacter: new (svg: SVGSVGElement, options?: GrokCharacterOptions) => GrokCharacterInstance
