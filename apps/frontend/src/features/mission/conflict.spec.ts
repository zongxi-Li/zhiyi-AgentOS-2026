import { expect, it } from 'vitest'
import { missionLaunchConflict } from './conflict'

it.each([
  [{ status: 409, data: { detail: { code: 'ATTACHMENT_NOT_READY' } } }, 'ATTACHMENT_NOT_READY'],
  [{ status: 409, headers: { 'x-mission-launch-conflict': 'CLIENT_REQUEST_ID_CONFLICT' } }, 'CLIENT_REQUEST_ID_CONFLICT'],
  [{ status: 409, headers: { 'x-mission-launch-conflict': 'MISSION_SEMANTIC_CONFLICT' } }, 'MISSION_SEMANTIC_CONFLICT'],
  [{ status: 409, data: { detail: { code: 'BUSINESS_RULE' } } }, 'UNKNOWN_CONFLICT'],
  [{ status: 409, data: { code: 'ATTACHMENT_NOT_READY' } }, 'ATTACHMENT_NOT_READY'],
  [{ status: 409, data: { detail: 'clientRequestId conflict' } }, 'UNKNOWN_CONFLICT'],
  [{ status: 503 }, null]
])('classifies only machine contracts: %j', (response, classification) => {
  expect(missionLaunchConflict({ response })).toBe(classification)
})
