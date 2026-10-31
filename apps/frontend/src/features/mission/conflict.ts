export type MissionLaunchConflict = 'ATTACHMENT_NOT_READY' | 'CLIENT_REQUEST_ID_CONFLICT' | 'MISSION_SEMANTIC_CONFLICT' | 'BUSINESS_CONFLICT' | 'UNKNOWN_CONFLICT' | null

export function missionLaunchConflict(error: unknown): MissionLaunchConflict {
  const response = (error as { response?: { status?: number; headers?: Record<string, string>; data?: { code?: string; detail?: { code?: string } } } })?.response
  if (response?.status !== 409) return null
  const code = response.data?.detail?.code || response.headers?.['x-mission-launch-conflict'] || response.data?.code
  if (code === 'ATTACHMENT_NOT_READY' || code === 'CLIENT_REQUEST_ID_CONFLICT' || code === 'MISSION_SEMANTIC_CONFLICT') return code
  // Unrecognized/gateway-generic codes carry no proof about creation safety.
  return 'UNKNOWN_CONFLICT'
}
