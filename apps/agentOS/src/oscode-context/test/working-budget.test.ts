import test from 'node:test'
import assert from 'node:assert/strict'
import { ContextCompactionEngine } from '../src/engine.ts'
import { DEFAULTS, SUMMARY_FIELDS } from '../src/contracts.ts'
import type { Message, ProjectionRequest } from '../src/contracts.ts'
import { TokenMeter } from '../src/token-meter.ts'
import { balancedCuts, selectCycleRange } from '../src/history-segmenter.ts'
import { pruneResults } from '../src/tool-result-pruner.ts'

const config = {...DEFAULTS, recentToolGroups: 5, recentTailTokens: 14000, maxSummaryCalls: 2, summaryMaxTokens: 4096}
const request = (messages: Message[]): ProjectionRequest => ({contextId:'owner', provider:'mock', model:'mock',
  instructions:'fixed rules', tools:[], messages,
  budget:{contextWindow:1_000_000, outputReserve:65536, safetyMargin:1024, workingSetTriggerTokens:65536, workingSetTargetTokens:40960}})
const cycle = (i: number, output = 'evidence '.repeat(300)): Message[] => [
  {type:'reasoning', id:`r${i}`, summary:[], content:[{type:'reasoning_text',text:`decision ${i}`}]},
  {type:'function_call', call_id:`c${i}`, name:'read_file', arguments:'{}'},
  {type:'function_call_output', call_id:`c${i}`, output},
]

test('100 tools within one user turn shrink at safe reasoning/call/result boundaries', async () => {
  const messages: Message[] = [{role:'user',content:'Preserve REST; do not change max effort.'},
    ...Array.from({length:100}, (_,i)=>cycle(i)).flat()]
  const original = structuredClone(messages)
  let calls=0
  const engine = new ContextCompactionEngine(new TokenMeter(), async (_text,_cap,instruction) => {
    calls++; assert.match(instruction,/UNTRUSTED/)
    return {text:JSON.stringify(Object.fromEntries(SUMMARY_FIELDS.map(k=>[k,k==='facts'?['confirmed evidence']:[]])))}
  }, config)
  const result = await engine.project(request(messages))
  assert.equal(result.status,'summarized'); assert.equal(calls,1)
  assert.deepEqual(result.messages[0], messages[0]); assert.ok(result.messages.length<50)
  assert.deepEqual(result.messages.slice(-15), messages.slice(-15))
  assert.ok(Number(result.metrics.outputTokens)<=40960)
  assert.equal(result.metrics.hardInputLimit,933440)
  assert.deepEqual(messages,original); balancedCuts(result.messages)
  const range=selectCycleRange(messages,new TokenMeter(),14000,5)!
  assert.equal(messages[range[1]].type,'reasoning')
})

for (const protectedOutput of [
  {ok:true,data:{result:{stdout:'x'.repeat(20000),exitCode:7,timedOut:false},activity:{status:'completed'}}},
  {ok:true,data:{result:{stdout:'x'.repeat(20000),exitCode:null,timedOut:true}}},
  {ok:true,data:{result:{stdout:'x'.repeat(20000)},activity:{status:'completed'}}},
  {ok:false,error:'TOOL_OUTCOME_UNKNOWN',stdout:'x'.repeat(20000)},
  {approval:{status:'pending'},stdout:'x'.repeat(20000)},
  [{type:'image',data:'attachment:reference'},{type:'text',text:'x'.repeat(20000)}],
]) test('microcompact preserves failure, unknown, pending and media: '+JSON.stringify(protectedOutput).slice(0,45), () => {
  const source=[{type:'function_call',call_id:'old',name:'run_command',arguments:'{}'},
    {type:'function_call_output',call_id:'old',output:JSON.stringify(protectedOutput)},
    ...Array.from({length:6},(_,i)=>cycle(i)).flat()]
  assert.deepEqual(pruneResults(source,config,source.length).messages[1],source[1])
})

test('microcompact adds a durable reference and reuses the same replacement', () => {
  const source=[...cycle(0,JSON.stringify({stdout:'x'.repeat(24000),exitCode:0,timedOut:false})),
    ...Array.from({length:6},(_,i)=>cycle(i+1)).flat()]
  const result=pruneResults(source,config,source.length)
  assert.ok(result.removedChars>0)
  assert.equal(JSON.parse(result.messages[2].output).oscode_archive_reference,'journal:c0')
  assert.deepEqual(result.messages.slice(-15),source.slice(-15))
  assert.deepEqual(pruneResults(result.messages,config,result.messages.length).messages,result.messages)
})

test('one bounded summary can cover old work around protected errors and attachments', async () => {
  const messages: Message[]=[{role:'user',content:'Current intent must remain verbatim'},
    ...Array.from({length:100},(_,i)=>cycle(i)).flat()]
  const failure=messages.find(m=>m.call_id==='c40' && m.type==='function_call_output')!
  failure.output=JSON.stringify({exitCode:7,stdout:'failure evidence',timedOut:false})
  const attachment=messages.find(m=>m.call_id==='c60' && m.type==='function_call_output')!
  attachment.output=[{type:'image',data:'attachment:actual-reference'}]
  let calls=0
  const engine=new ContextCompactionEngine(new TokenMeter(),async()=>{
    calls++; return {text:JSON.stringify(Object.fromEntries(SUMMARY_FIELDS.map(k=>[k,k==='facts'?['confirmed old work']:[]])))}
  },config)
  const result=await engine.project(request(messages))
  assert.equal(result.status,'summarized'); assert.equal(calls,1)
  assert.deepEqual(result.messages.find(m=>m.call_id==='c40' && m.type==='function_call_output'),failure)
  assert.deepEqual(result.messages.find(m=>m.call_id==='c60' && m.type==='function_call_output'),attachment)
  assert.deepEqual(result.messages[0],messages[0]); balancedCuts(result.messages)
})

test('protected input may exceed soft budget, but cannot exceed hard capacity', async () => {
  let calls=0
  const engine=new ContextCompactionEngine(new TokenMeter(),async()=>{calls++;throw Error('unexpected')},config)
  const input=request([{role:'user',content:'current material '.repeat(5000)}])
  const result=await engine.project(input)
  assert.equal(result.status,'no_safe_range'); assert.equal(result.metrics.softOverBudget,true); assert.equal(calls,0)
  input.budget.contextWindow=80000
  await assert.rejects(engine.project(input),/oversized request blocked/)
})

test('eligible work still shrinks when protected evidence exceeds the soft target', async () => {
  const messages: Message[]=[{role:'user',content:'preserve constraints'},...Array.from({length:100},(_,i)=>cycle(i)).flat()]
  const failure=messages.find(m=>m.call_id==='c40' && m.type==='function_call_output')!
  failure.output=JSON.stringify({exitCode:7,stdout:'x'.repeat(70000),timedOut:false})
  const engine=new ContextCompactionEngine(new TokenMeter(),async()=>({text:JSON.stringify(
    Object.fromEntries(SUMMARY_FIELDS.map(k=>[k,k==='facts'?['confirmed old work']:[]])))}),config)
  const result=await engine.project(request(messages))
  assert.equal(result.status,'summarized');assert.equal(result.metrics.softOverBudget,true)
  assert.equal(result.metrics.targetReachable,false)
  assert.ok(Number(result.metrics.outputTokens)<Number(result.metrics.inputTokens))
  assert.deepEqual(result.messages.find(m=>m.call_id==='c40' && m.type==='function_call_output'),failure)
})
