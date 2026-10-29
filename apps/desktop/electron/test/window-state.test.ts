import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  DEFAULT_WINDOW_STATE,
  dropStalePosition,
  parseWindowState,
  serializeWindowState
} from '../src/lib/window-state.ts'

test('parseWindowState 对空/坏输入回退默认，不抛错', () => {
  assert.deepEqual(parseWindowState(null), DEFAULT_WINDOW_STATE)
  assert.deepEqual(parseWindowState(''), DEFAULT_WINDOW_STATE)
  assert.deepEqual(parseWindowState('{bad json'), DEFAULT_WINDOW_STATE)
  assert.deepEqual(parseWindowState('[1,2]'), DEFAULT_WINDOW_STATE)
  assert.deepEqual(parseWindowState('"text"'), DEFAULT_WINDOW_STATE)
})

test('parseWindowState 字段级容错', () => {
  const state = parseWindowState(JSON.stringify({ width: 1200, height: 800, x: 40, y: 60, isMaximized: true }))
  assert.deepEqual(state, { width: 1200, height: 800, x: 40, y: 60, isMaximized: true })

  assert.equal(parseWindowState(JSON.stringify({ width: 10, height: 99999 })).width, DEFAULT_WINDOW_STATE.width)
  assert.equal(parseWindowState(JSON.stringify({ width: '1200' })).width, DEFAULT_WINDOW_STATE.width)
  // 超范围坐标丢弃，尺寸保留。
  const stale = parseWindowState(JSON.stringify({ width: 1200, height: 800, x: 999999, y: 0 }))
  assert.equal(stale.x, undefined)
  assert.equal(stale.width, 1200)
})

test('serializeWindowState 与 parseWindowState 往返一致', () => {
  const raw = serializeWindowState({ x: 11, y: 22, width: 1440, height: 900 }, true, false)
  const restored = parseWindowState(raw)
  assert.deepEqual(restored, { width: 1440, height: 900, x: 11, y: 22, isMaximized: true })
})

test('dropStalePosition 保留在屏坐标，丢弃离屏坐标', () => {
  const onScreen = dropStalePosition(
    { width: 1200, height: 800, x: 10, y: 10, isMaximized: false },
    () => true
  )
  assert.equal(onScreen.x, 10)

  const offScreen = dropStalePosition(
    { width: 1200, height: 800, x: 5000, y: 500, isMaximized: true },
    () => false
  )
  assert.equal(offScreen.x, undefined)
  assert.equal(offScreen.y, undefined)
  assert.equal(offScreen.width, 1200)
  assert.equal(offScreen.isMaximized, true)
})
