// Grok 角色动效引擎（学习复刻版，源自 grok-icon-study，素材归 xAI 所有，仅供学习参考）。
// 引擎是一组按顺序执行的 IIFE，全部挂到 window：下面 import 的先后顺序不可改动。
import './geometry-data.js'
import './math.js'
import './tables.js'
import './pose.js'
import './tricks.js'
import './fx.js'
import './eyes.js'
import './character.js'

const scope = window

export const GROK_GEO = scope.GROK_GEO
export const GROK_META = scope.GROK_META
export const GrokCharacter = scope.GrokCharacter
