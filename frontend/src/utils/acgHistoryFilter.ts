export type AcgHistoryRole = 'all' | 'general' | 'lawyer' | 'teacher' | 'programmer' | 'writer'

export const ACG_HISTORY_SOURCES = 'acg,agent,chat,legacy_agent_chat'
export const ACG_HISTORY_ROLE_STORAGE_KEY = 'acg.history.role'
export const ACG_HISTORY_ROLE_CHANGE_EVENT = 'acg-history-role-change'

export const ACG_HISTORY_ROLE_OPTIONS: ReadonlyArray<{ value: AcgHistoryRole; label: string }> = [
  { value: 'all', label: '全部角色' },
  { value: 'general', label: '通用' },
  { value: 'lawyer', label: '律师' },
  { value: 'teacher', label: '教师' },
  { value: 'programmer', label: '程序员' },
  { value: 'writer', label: '作家' }
]

const ROLE_DOMAINS: Record<Exclude<AcgHistoryRole, 'all'>, string> = {
  general: 'general',
  lawyer: 'legal',
  teacher: 'education',
  programmer: 'programmer',
  writer: 'writer'
}

export const acgHistoryRoleDomain = (role: AcgHistoryRole): string | undefined =>
  role === 'all' ? undefined : ROLE_DOMAINS[role]

export const isAcgHistoryRole = (value: unknown): value is AcgHistoryRole =>
  ACG_HISTORY_ROLE_OPTIONS.some(option => option.value === value)

export const loadAcgHistoryRole = (): AcgHistoryRole => {
  if (typeof window === 'undefined') return 'all'
  const stored = window.localStorage.getItem(ACG_HISTORY_ROLE_STORAGE_KEY)
  return isAcgHistoryRole(stored) ? stored : 'all'
}

export const saveAcgHistoryRole = (role: AcgHistoryRole): void => {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(ACG_HISTORY_ROLE_STORAGE_KEY, role)
  window.dispatchEvent(new CustomEvent<AcgHistoryRole>(ACG_HISTORY_ROLE_CHANGE_EVENT, { detail: role }))
}
