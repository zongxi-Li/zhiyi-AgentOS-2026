import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  clampNumber,
  fitsAnyDisplay,
  parseBoolean,
  parseBoundedText,
  parseExtensions,
  parseHttpUrl
} from '../src/lib/validation.ts'

test('parseHttpUrl 接受 http/https 与端口，拒绝其他协议与 userinfo', () => {
  assert.equal(parseHttpUrl('https://example.com/a?b=1')?.hostname, 'example.com')
  assert.equal(parseHttpUrl('http://127.0.0.1:9050/api')?.port, '9050')
  assert.equal(parseHttpUrl('ftp://example.com'), null)
  assert.equal(parseHttpUrl('javascript:alert(1)'), null)
  assert.equal(parseHttpUrl('file:///C:/x'), null)
  assert.equal(parseHttpUrl('http://user:pass@example.com/'), null)
  assert.equal(parseHttpUrl('not a url'), null)
  assert.equal(parseHttpUrl(42), null)
  assert.equal(parseHttpUrl(`http://example.com/${'a'.repeat(2100)}`), null)
  assert.equal(parseHttpUrl('http://example.com/\u0000'), null)
  assert.equal(parseHttpUrl('https://'), null)
})

test('parseExtensions 合法输入去重小写，非法输入返回 null', () => {
  assert.equal(parseExtensions(undefined), undefined)
  assert.equal(parseExtensions(null), undefined)
  assert.deepEqual(parseExtensions(['csv', 'JSON', 'csv']), ['csv', 'json'])
  assert.deepEqual(parseExtensions([]), [])
  assert.equal(parseExtensions('csv'), null)
  assert.equal(parseExtensions(['a.b']), null)
  assert.equal(parseExtensions(['../x']), null)
  assert.equal(parseExtensions(Array.from({ length: 17 }, () => 'csv')), null)
  assert.equal(parseExtensions(['x'.repeat(13)]), null)
})

test('parseBoundedText 边界与控制字符', () => {
  assert.equal(parseBoundedText('hello', 10), 'hello')
  assert.equal(parseBoundedText('', 10), null)
  assert.equal(parseBoundedText(undefined, 10), null)
  assert.equal(parseBoundedText(123, 10), null)
  assert.equal(parseBoundedText('a'.repeat(11), 10), null)
  assert.equal(parseBoundedText('a\u0000b', 10), null)
  // 换行/制表是正常文本，不拒绝。
  assert.equal(parseBoundedText('a\nb\tc', 10), 'a\nb\tc')
})

test('parseBoolean 与 clampNumber', () => {
  assert.equal(parseBoolean(true), true)
  assert.equal(parseBoolean(false), false)
  assert.equal(parseBoolean('true'), null)
  assert.equal(parseBoolean(1), null)
  assert.equal(clampNumber(1.2, 0.25, 5), 1.2)
  assert.equal(clampNumber(99, 0.25, 5), 5)
  assert.equal(clampNumber(-1, 0.25, 5), 0.25)
  assert.equal(clampNumber(Number.NaN, 0.25, 5), null)
  assert.equal(clampNumber('1.2', 0.25, 5), null)
})

test('fitsAnyDisplay 命中与拔屏场景', () => {
  const displays = [{ x: 0, y: 0, width: 1920, height: 1080 }, { x: 1920, y: 0, width: 2560, height: 1440 }]
  assert.equal(fitsAnyDisplay({ x: 100, y: 100, width: 800, height: 600 }, displays), true)
  assert.equal(fitsAnyDisplay({ x: 2000, y: 100, width: 800, height: 600 }, displays), true)
  assert.equal(fitsAnyDisplay({ x: 5000, y: 100, width: 800, height: 600 }, displays), false)
  assert.equal(fitsAnyDisplay({ x: Number.NaN, y: 0, width: 800, height: 600 }, displays), false)
  assert.equal(fitsAnyDisplay({ x: 0, y: 0, width: 800, height: 600 }, []), false)
})
