import { test } from 'node:test'
import assert from 'node:assert/strict'
import { LLMSummarizer, SUMMARY_SCHEMA } from '../src/summarizer.ts'
import { TokenMeter } from '../src/token-meter.ts'
import { DEFAULTS, resolveConfig, SUMMARY_FIELDS } from '../src/contracts.ts'

test('Planner can remove auxiliary call counts while chat retains its explicit default', async () => {
  assert.equal(DEFAULTS.maxSummaryCalls, 16)
  assert.equal(resolveConfig({ maxSummaryCalls: null }).maxSummaryCalls, null)
  const source = [{ role: 'user', content: 'source '.repeat(12_000) }]
  const checkpoint = Object.fromEntries(SUMMARY_FIELDS.map(key => [key, key === 'facts' ? ['confirmed'] : []]))
  let calls = 0
  const invoke = async () => { calls++; return { text: JSON.stringify(checkpoint) } }
  const budget = { contextWindow: 4000, outputReserve: 400, safetyMargin: 0 }
  const unlimited = new LLMSummarizer(invoke, new TokenMeter(), budget, null)
  const result = await unlimited.summarize(source, 400)
  assert.ok(calls > 16)
  assert.deepEqual(result, checkpoint)
  const limited = new LLMSummarizer(invoke, new TokenMeter(), budget, 2)
  await assert.rejects(limited.summarize(source, 400), /Summary call budget exceeded/)
  assert.equal(limited.calls, 2)
  assert.deepEqual(SUMMARY_SCHEMA.required, [...SUMMARY_FIELDS])
})
