export type ColorSchemeId = 'codex-dark' | 'claude-warm' | 'tea-green' | 'blue-purple'

export interface ColorScheme {
  id: ColorSchemeId
  name: string
  nameEn: string
  previewColor: string
  variables: Record<string, string>
  bodyBackground: string
}

const codexDark: ColorScheme = {
  id: 'codex-dark',
  name: '经典黑色',
  nameEn: 'VS Code Classic Dark',
  previewColor: '#4FC1FF',
  bodyBackground: 'none',
  variables: {
    '--primary-color': '#0E639C',
    '--primary-hover': '#1177BB',
    '--primary-active': '#005A9E',
    '--primary-fade': 'rgba(14, 99, 156, 0.2)',
    '--primary-line': 'rgba(79, 193, 255, 0.48)',

    '--accent-color': '#4FC1FF',
    '--accent-fade': 'rgba(79, 193, 255, 0.14)',

    '--bg-app': '#181818',
    '--bg-sidebar': '#1F1F1F',
    '--bg-card': '#252526',
    '--bg-panel': '#2D2D2D',
    '--bg-input': '#1F1F1F',
    '--bg-glass': 'rgba(37, 37, 38, 0.88)',
    '--surface-solid': 'var(--bg-card)',
    '--surface-raised': 'color-mix(in srgb, var(--bg-card) 88%, transparent)',
    '--surface-subtle': 'color-mix(in srgb, var(--bg-panel) 80%, transparent)',
    '--surface-hover': 'var(--bg-panel)',
    '--overlay-backdrop': 'rgba(0, 0, 0, 0.72)',
    '--shadow-color': 'rgba(0, 0, 0, 0.34)',
    '--on-primary': '#FFFFFF',
    '--app-layout-bg': 'var(--bg-app)',
    '--sidebar-bg': 'rgba(31, 31, 31, 0.98)',
    '--drawer-bg': 'rgba(31, 31, 31, 0.99)',
    '--sidebar-border': 'rgba(60, 60, 60, 0.9)',
    '--scrollbar-thumb': 'rgba(133, 133, 133, 0.34)',
    '--scrollbar-thumb-hover': 'rgba(79, 193, 255, 0.48)',

    '--selection-bg': 'rgba(0, 122, 204, 0.35)',
    '--selection-text': '#FFFFFF',

    '--app-topbar-bg': '#181818',
    '--app-topbar-text': '#CCCCCC',
    '--app-topbar-muted': '#858585',
    '--app-topbar-border': '#2B2B2B',
    '--app-topbar-hover': '#2A2D2E',
    '--app-topbar-active': '#37373D',
    '--app-topbar-focus-ring': 'rgba(79, 193, 255, 0.34)',
    '--app-topbar-focus-border': '#4FC1FF',
    '--app-topbar-input-bg': '#252526',
    '--app-topbar-input-bg-hover': '#2D2D2D',
    '--app-topbar-input-border': '#3C3C3C',
    '--app-topbar-kbd-bg': '#2D2D2D',
    '--app-topbar-logo-bg': '#252526',

    '--text-primary': '#D4D4D4',
    '--text-regular': '#C8C8C8',
    '--text-secondary': '#A6A6A6',
    '--text-muted': '#858585',
    '--text-disabled': '#5A5A5A',

    '--border-light': '#3C3C3C',
    '--border-hover': '#4E4E4E',
    '--border-focus': 'rgba(79, 193, 255, 0.68)',
    '--border-color': 'var(--border-light)',
    '--color-primary': 'var(--primary-color)',

    '--success': '#89D185',
    '--warning': '#CCA700',
    '--danger': '#F48771',
    '--info': '#75BEFF',
    '--success-fade': 'color-mix(in srgb, var(--success) 12%, transparent)',
    '--warning-fade': 'color-mix(in srgb, var(--warning) 12%, transparent)',
    '--danger-fade': 'color-mix(in srgb, var(--danger) 12%, transparent)',
    '--info-fade': 'color-mix(in srgb, var(--info) 12%, transparent)',

    '--shadow-sm': '0 1px 2px rgba(0, 0, 0, 0.35)',
    '--shadow-md': '0 10px 26px rgba(0, 0, 0, 0.42)',
    '--shadow-lg': '0 20px 52px rgba(0, 0, 0, 0.52)',
    '--shadow-glow': '0 10px 24px rgba(0, 122, 204, 0.24)',

    '--el-color-primary': '#0E639C',
    '--el-color-primary-light-3': '#1177BB',
    '--el-color-primary-light-5': '#2894D1',
    '--el-color-primary-light-7': '#18537A',
    '--el-color-primary-light-8': '#163E59',
    '--el-color-primary-light-9': '#123047',
    '--el-color-primary-dark-2': '#005A9E',
    '--el-bg-color': '#1F1F1F',
    '--el-bg-color-page': '#181818',
    '--el-bg-color-overlay': '#2D2D2D',
    '--el-fill-color-blank': '#252526',
    '--el-fill-color': '#2D2D2D',
    '--el-fill-color-light': '#333333',
    '--el-fill-color-lighter': '#383838',
    '--el-fill-color-extra-light': '#3C3C3C',
    '--el-fill-color-dark': '#1F1F1F',
    '--el-fill-color-darker': '#181818',
    '--el-fill-color-disabled': '#252526',
    '--el-text-color-primary': '#D4D4D4',
    '--el-text-color-regular': '#C8C8C8',
    '--el-text-color-secondary': '#A6A6A6',
    '--el-text-color-placeholder': '#858585',
    '--el-text-color-disabled': '#5A5A5A',
    '--el-border-color': '#3C3C3C',
    '--el-border-color-light': '#454545',
    '--el-border-color-lighter': '#353535',
    '--el-border-color-extra-light': '#303030',
    '--el-border-color-dark': '#4E4E4E',
    '--el-border-color-darker': '#5A5A5A',
    '--el-mask-color': 'rgba(0, 0, 0, 0.72)',
  },
}

const claudeWarm: ColorScheme = {
  id: 'claude-warm',
  name: 'Claude 暖橙',
  nameEn: 'Claude Warm',
  previewColor: '#D97757',
  bodyBackground: 'none',
  variables: {
    '--primary-color': '#D97757',
    '--primary-hover': '#C15F3C',
    '--primary-active': '#A84B2F',
    '--primary-fade': 'rgba(217, 119, 87, 0.1)',
    '--primary-line': 'rgba(217, 119, 87, 0.24)',

    '--accent-color': '#B07B4F',
    '--accent-fade': 'rgba(176, 123, 79, 0.1)',

    '--bg-app': '#FAF9F5',
    '--bg-sidebar': '#F5F3EC',
    '--bg-card': '#FFFFFF',
    '--bg-panel': '#F5F4EE',
    '--bg-input': '#F0EEE6',
    '--bg-glass': 'rgba(255, 255, 255, 0.7)',
    '--app-layout-bg': 'var(--bg-app)',
    '--sidebar-bg': 'rgba(245, 243, 236, 0.94)',
    '--drawer-bg': 'rgba(250, 249, 245, 0.97)',
    '--sidebar-border': 'rgba(228, 223, 210, 0.7)',
    '--scrollbar-thumb': 'rgba(217, 119, 87, 0.18)',
    '--scrollbar-thumb-hover': 'rgba(217, 119, 87, 0.28)',

    '--text-primary': '#1F1E1D',
    '--text-regular': '#3D3A34',
    '--text-secondary': '#73706B',
    '--text-disabled': '#ABA79E',

    '--border-light': '#E9E4D8',
    '--border-hover': '#D9D2C2',
    '--border-focus': 'rgba(217, 119, 87, 0.42)',

    '--success': '#4A7C59',
    '--warning': '#B5852F',
    '--danger': '#C0533F',
    '--info': '#7A6E5D',

    '--shadow-sm': '0 1px 2px rgba(31, 30, 29, 0.04)',
    '--shadow-md': '0 8px 24px rgba(31, 30, 29, 0.06)',
    '--shadow-lg': '0 18px 48px rgba(31, 30, 29, 0.08)',
    '--shadow-glow': '0 12px 28px rgba(217, 119, 87, 0.16)',

    '--el-color-primary': '#D97757',
    '--el-color-primary-light-3': '#E39F87',
    '--el-color-primary-light-5': '#ECBBA9',
    '--el-color-primary-light-7': '#F4D7CB',
    '--el-color-primary-light-8': '#F8E5DC',
    '--el-color-primary-light-9': '#FCF2ED',
    '--el-color-primary-dark-2': '#C15F3C',
  },
}

const teaGreen: ColorScheme = {
  id: 'tea-green',
  name: '茶绿',
  nameEn: 'Tea Green',
  previewColor: '#3f6b63',
  bodyBackground: 'none',
  variables: {
    '--primary-color': '#3f6b63',
    '--primary-hover': '#345b54',
    '--primary-active': '#294943',
    '--primary-fade': 'rgba(63, 107, 99, 0.1)',
    '--primary-line': 'rgba(63, 107, 99, 0.22)',

    '--accent-color': '#6f668f',
    '--accent-fade': 'rgba(111, 102, 143, 0.1)',

    '--bg-app': '#f6f7f4',
    '--bg-sidebar': '#fbfbf8',
    '--bg-card': '#ffffff',
    '--bg-panel': '#fbfcfa',
    '--bg-input': '#f1f3ef',
    '--bg-glass': 'rgba(255, 255, 255, 0.72)',
    '--app-layout-bg': 'var(--bg-app)',
    '--sidebar-bg': 'rgba(251, 251, 248, 0.92)',
    '--drawer-bg': 'rgba(251, 251, 248, 0.96)',
    '--sidebar-border': 'rgba(227, 230, 223, 0.72)',
    '--scrollbar-thumb': 'rgba(63, 107, 99, 0.16)',
    '--scrollbar-thumb-hover': 'rgba(63, 107, 99, 0.24)',

    '--text-primary': '#1d2422',
    '--text-regular': '#3d4642',
    '--text-secondary': '#727c76',
    '--text-disabled': '#a6aca8',

    '--border-light': '#e3e6df',
    '--border-hover': '#cfd6cd',
    '--border-focus': 'rgba(63, 107, 99, 0.42)',

    '--success': '#3d7656',
    '--warning': '#9a7432',
    '--danger': '#b24a4a',
    '--info': '#496b8f',

    '--shadow-sm': '0 1px 2px rgba(29, 36, 34, 0.04)',
    '--shadow-md': '0 8px 24px rgba(29, 36, 34, 0.06)',
    '--shadow-lg': '0 18px 48px rgba(29, 36, 34, 0.08)',
    '--shadow-glow': '0 12px 28px rgba(63, 107, 99, 0.14)',

    '--el-color-primary': '#3f6b63',
    '--el-color-primary-light-3': '#79a098',
    '--el-color-primary-light-5': '#a5c2ba',
    '--el-color-primary-light-7': '#c9ddd5',
    '--el-color-primary-light-8': '#dbeae2',
    '--el-color-primary-light-9': '#edf5f1',
    '--el-color-primary-dark-2': '#345b54',
  },
}

const bluePurple: ColorScheme = {
  id: 'blue-purple',
  name: '蓝紫',
  nameEn: 'Blue Purple',
  previewColor: '#5B5FCF',
  bodyBackground: 'none',
  variables: {
    '--primary-color': '#5B5FCF',
    '--primary-hover': '#4A4EB8',
    '--primary-active': '#3D41A3',
    '--primary-fade': 'rgba(91, 95, 207, 0.1)',
    '--primary-line': 'rgba(91, 95, 207, 0.22)',

    '--accent-color': '#8B5CF6',
    '--accent-fade': 'rgba(139, 92, 246, 0.1)',

    '--bg-app': '#f5f4fa',
    '--bg-sidebar': '#fafaff',
    '--bg-card': '#ffffff',
    '--bg-panel': '#fafafd',
    '--bg-input': '#f0f0f8',
    '--bg-glass': 'rgba(255, 255, 255, 0.72)',
    '--app-layout-bg': 'var(--bg-app)',
    '--sidebar-bg': 'rgba(250, 250, 255, 0.92)',
    '--drawer-bg': 'rgba(250, 250, 255, 0.96)',
    '--sidebar-border': 'rgba(228, 227, 240, 0.72)',
    '--scrollbar-thumb': 'rgba(91, 95, 207, 0.16)',
    '--scrollbar-thumb-hover': 'rgba(91, 95, 207, 0.24)',

    '--text-primary': '#1c1c2e',
    '--text-regular': '#3c3c56',
    '--text-secondary': '#6f6f8a',
    '--text-disabled': '#a4a4b8',

    '--border-light': '#e4e3f0',
    '--border-hover': '#cecdd8',
    '--border-focus': 'rgba(91, 95, 207, 0.42)',

    '--success': '#3d7656',
    '--warning': '#9a7432',
    '--danger': '#b24a4a',
    '--info': '#5B7FCF',

    '--shadow-sm': '0 1px 2px rgba(28, 28, 46, 0.04)',
    '--shadow-md': '0 8px 24px rgba(28, 28, 46, 0.06)',
    '--shadow-lg': '0 18px 48px rgba(28, 28, 46, 0.08)',
    '--shadow-glow': '0 12px 28px rgba(91, 95, 207, 0.14)',

    '--el-color-primary': '#5B5FCF',
    '--el-color-primary-light-3': '#8C8FDD',
    '--el-color-primary-light-5': '#ADAFE7',
    '--el-color-primary-light-7': '#CECFF1',
    '--el-color-primary-light-8': '#DEDFF5',
    '--el-color-primary-light-9': '#EFEFFA',
    '--el-color-primary-dark-2': '#4A4EB8',
  },
}

export const colorSchemes: ColorScheme[] = [codexDark, claudeWarm, bluePurple, teaGreen]

export function getColorScheme(id: ColorSchemeId): ColorScheme {
  return colorSchemes.find((s) => s.id === id) || codexDark
}
