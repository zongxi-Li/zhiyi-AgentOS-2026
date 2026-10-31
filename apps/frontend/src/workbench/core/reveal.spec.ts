import { afterEach, expect, it } from 'vitest'
import { registerReveal, requestReveal, resetReveal } from './reveal'

afterEach(() => resetReveal())

it('编辑器未挂载时先暂存，注册时立即消费', () => {
  const seen: number[] = []
  requestReveal('src/a.ts', 12)
  const off = registerReveal('src/a.ts', line => seen.push(line))
  expect(seen).toEqual([12])
  off()
})

it('已挂载时直接投递，不同路径互不影响', () => {
  const first: number[] = []
  const second: number[] = []
  registerReveal('a.ts', line => first.push(line))
  registerReveal('b.ts', line => second.push(line))

  requestReveal('a.ts', 3)
  requestReveal('a.ts', 9)
  requestReveal('b.ts', 1)
  expect(first).toEqual([3, 9])
  expect(second).toEqual([1])
})

it('注销后不再接收，等下一个编辑器注册', () => {
  const seen: number[] = []
  const off = registerReveal('a.ts', line => seen.push(line))
  off()
  requestReveal('a.ts', 5)
  expect(seen).toEqual([])

  registerReveal('a.ts', line => seen.push(line))
  expect(seen).toEqual([5])
})

it('空路径被忽略', () => {
  const seen: number[] = []
  registerReveal('', line => seen.push(line))
  requestReveal('', 1)
  expect(seen).toEqual([])
})
