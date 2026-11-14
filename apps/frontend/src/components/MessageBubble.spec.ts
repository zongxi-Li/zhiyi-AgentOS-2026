import { shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MessageBubble from './MessageBubble.vue'

const mountAssistant = (content: string) => shallowMount(MessageBubble, {
  props: {
    message: {
      id: 'assistant-table',
      role: 'assistant',
      content,
      createdAt: new Date('2026-08-03T12:00:00Z')
    }
  },
  global: {
    stubs: {
      'el-icon': true,
      'el-tooltip': { template: '<span><slot /></span>' },
      'el-progress': true,
      ImageViewer: true
    }
  }
})

describe('MessageBubble Markdown rendering', () => {
  it('renders a stream failure even when only reasoning blocks were received', () => {
    const wrapper = shallowMount(MessageBubble, {props: {message: {
      id: 'failed-reasoning', role: 'assistant', content: '模型连接中断', streamError: '模型连接中断',
      transcript: [{id:'reasoning', kind:'reasoning', text:'合成进展', state:'interrupted'}],
    }}, global: {stubs: {'el-icon':true, 'el-tooltip':true, 'el-progress':true, ImageViewer:true}}})
    expect(wrapper.get('.stream-error').text()).toBe('模型连接中断')
  })

  it('passes ordered blocks and their own tool details without aggregating the sequence', () => {
    const wrapper = shallowMount(MessageBubble, {props: {message: {
      id: 'ordered', role: 'assistant', content: 'beforeafter', transcript: [
        {id:'a',kind:'text',text:'before',state:'completed'},
        {id:'tool:x',kind:'tool',callId:'x',toolName:'read_file',state:'completed'},
        {id:'b',kind:'text',text:'after',state:'completed'},
      ], executionSummary:[{stage:'tool:read_file:x',status:'completed',description:'read'}],
    }}, global: {stubs: {'el-icon':true, 'el-tooltip':true, 'el-progress':true, ImageViewer:true}}})
    const blocks = wrapper.findAllComponents({name:'ChatTranscriptBlock'})
    expect(blocks.map(block=>block.props('block').id)).toEqual(['a','tool:x','b'])
    expect(blocks[1].props('item').stage).toBe('tool:read_file:x')
    expect(blocks[0].props('item')).toBeUndefined()
  })

  it('follows the newest reasoning delta while retaining the full expanded text', async () => {
    const initial = 'Earlier analysis. '.repeat(30)
    const message = { id: 'live-tail', role: 'assistant', content: '',
      createdAt: new Date(), thinkingState: 'thinking', reasoningContent: initial }
    const wrapper = shallowMount(MessageBubble, { props: { message }, global: {
      stubs: { 'el-icon': true, 'el-tooltip': { template: '<span><slot /></span>' }, 'el-progress': true, ImageViewer: true }
    } })
    const preview = wrapper.get('.thinking-status__preview-text')
    Object.defineProperty(preview.element, 'scrollWidth', { value: 640, configurable: true })
    const latest = `${initial}现在检查车轮转动与道路动画，修复最新问题 🚲`
    await wrapper.setProps({ message: { ...message, reasoningContent: latest } })
    expect(preview.text()).toContain('现在检查车轮转动与道路动画，修复最新问题 🚲')
    expect(preview.text().endsWith('🚲')).toBe(true)
    expect(Array.from(preview.text()).length).toBeLessThanOrEqual(181)
    expect(preview.element.scrollLeft).toBe(640)
    await wrapper.get('.thinking-status__preview').trigger('click')
    expect(wrapper.get('.reasoning-content').text()).toBe(latest)
    const expanded = wrapper.get('.reasoning-content')
    Object.defineProperty(expanded.element, 'scrollHeight', { value: 900 })
    Object.defineProperty(expanded.element, 'clientHeight', { value: 100 })
    await wrapper.setProps({ message: { ...message, reasoningContent: `${latest} 下一步检查灯光` } })
    expect(expanded.element.scrollTop).toBe(900)
    await expanded.trigger('wheel')
    expanded.element.scrollTop = 0
    await expanded.trigger('scroll')
    await wrapper.setProps({ message: { ...message, reasoningContent: `${latest} 下一步检查灯光和材质` } })
    expect(expanded.element.scrollTop).toBe(0)
    wrapper.unmount()
  })

  it('renders Markdown tables in assistant replies', () => {
    const wrapper = mountAssistant([
      '| 风险编号 | 风险标题 | 修改建议 |',
      '| --- | --- | --- |',
      '| risk-001 | 付款节点倒挂 | 验收后付款 |'
    ].join('\n'))

    expect(wrapper.find('.markdown-table-wrap').exists()).toBe(true)
    expect(wrapper.findAll('th').map(cell => cell.text())).toEqual(['风险编号', '风险标题', '修改建议'])
    expect(wrapper.findAll('td').map(cell => cell.text())).toEqual(['risk-001', '付款节点倒挂', '验收后付款'])
  })

  it('keeps raw HTML escaped while rendering Markdown', () => {
    const wrapper = mountAssistant('<script>alert("x")</script> **安全内容**')

    expect(wrapper.find('script').exists()).toBe(false)
    expect(wrapper.find('strong').text()).toBe('安全内容')
    expect(wrapper.text()).toContain('<script>')
  })

  it('shows the live execution phase below partial assistant content', () => {
    const wrapper = shallowMount(MessageBubble, {
      props: {
        message: {
          id: 'assistant-continuing',
          role: 'assistant',
          content: '我先读取当前文件，然后进行优化升级。',
          createdAt: new Date('2026-08-03T12:00:00Z'),
          thinkingState: 'complete',
          thinkingDurationMs: 10_000,
          streamActivity: 'waiting',
          streamPhase: '等待模型继续'
          ,phaseStartedAt: 1000, lastHeartbeatAt: 19000, lastProviderActivityAt: 16000
        }
      },
      global: { stubs: { 'el-icon': true, 'el-tooltip': { template: '<span><slot /></span>' }, 'el-progress': true, ImageViewer: true } }
    })

    const status = wrapper.find('.continuation-status')
    expect(status.exists()).toBe(true)
    expect(status.text()).toContain('执行脉络')
    expect(status.text()).toContain('等待模型继续')
    expect(status.text()).toContain('18 秒')
    expect(wrapper.find('.thinking-status__phase').text()).toBe('等待模型继续')
    expect(status.element.compareDocumentPosition(wrapper.find('.message-actions').element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('removes the continuation status after the stream completes', () => {
    const wrapper = shallowMount(MessageBubble, {
      props: {
        message: {
          id: 'assistant-complete',
          role: 'assistant',
          content: '任务已完成。',
          createdAt: new Date('2026-08-03T12:00:00Z'),
          streamActivity: 'complete',
          streamPhase: '已完成'
        }
      },
      global: { stubs: { 'el-icon': true, 'el-tooltip': { template: '<span><slot /></span>' }, 'el-progress': true, ImageViewer: true } }
    })

    expect(wrapper.find('.continuation-status').exists()).toBe(false)
  })

  it('keeps command and file work out of the conversation (renders in the info dock feed instead)', () => {
    const wrapper = shallowMount(MessageBubble, {
      props: {
        message: {
          id: 'assistant-work',
          role: 'assistant',
          content: '命令已执行，文件已更新。',
          createdAt: new Date('2026-08-03T12:00:00Z'),
          executionSummary: [
            {
              stage: 'tool:run_command:call-shell',
              status: 'approval_required',
              description: 'Run command',
              approval: {
                approvalId: 'approval-shell', toolCallId: 'call-shell', invocationId: 'call-shell',
                toolName: 'run_command', capabilityId: 'shell.exec', relativePath: '.',
                operationSummary: 'Run command: echo hello', operation: 'Run command',
                command: 'echo hello', cwd: '.', riskNotice: '当前 Windows 用户权限',
                createdAt: '2026-08-03T12:00:00Z', status: 'pending', sessionId: 'chat_session'
              }
            },
            {
              stage: 'tool:terminal:call_1',
              status: 'completed',
              description: '终端命令执行完成',
              terminal: {
                command: 'python -c "print(1)"', cwd: '/app/workspace', exitCode: 0,
                stdout: '1\n', stderr: '', timedOut: false, truncated: false
              }
            },
            {
              stage: 'tool:patch_file:call_2',
              status: 'completed',
              description: 'Edited file',
              activity: { kind: 'file_patch', capabilityId: 'fs.patch', relativePath: 'src/hello.txt' }
            }
          ]
        }
      },
      global: { stubs: { 'el-icon': true, 'el-tooltip': { template: '<span><slot /></span>' }, 'el-progress': true, ImageViewer: true } }
    })

    expect(wrapper.find('.approval-work').exists()).toBe(false)
    expect(wrapper.find('.terminal-work').exists()).toBe(false)
    expect(wrapper.find('.file-work').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('需要确认命令执行')
    expect(wrapper.text()).not.toContain('退出码')
  })

  it('shows a collapsed reasoning preview and keeps execution summary collapsed until requested', async () => {
    const wrapper = shallowMount(MessageBubble, {
      props: {
        message: {
          id: 'assistant-reasoning',
          role: 'assistant',
          content: '完成。',
          createdAt: new Date('2026-08-03T12:00:00Z'),
          thinkingState: 'complete',
          thinkingDurationMs: 125_000,
          reasoningContent: '先检查文件，再写一个单页。',
          modelInfo: 'deepseek-flash',
          effectiveThinkingMode: 'deep',
          tokensUsed: 121_200,
          executionSummary: [
            { stage: 'tool:run_command:call_1', status: 'completed', description: 'run_command 调用完成', durationMs: 1220 },
            { stage: 'tool:read_file:call_2', status: 'failed', description: 'read_file 调用失败', durationMs: 905 }
          ]
        }
      },
      global: { stubs: { 'el-icon': true, 'el-tooltip': { template: '<span><slot /></span>' }, 'el-progress': true, ImageViewer: true } }
    })

    expect(wrapper.find('.thinking-status__preview').text()).toContain('先检查文件')
    expect(wrapper.find('.thinking-status__details').exists()).toBe(false)

    await wrapper.get('.thinking-status__trigger').trigger('click')
    expect(wrapper.find('.reasoning-content').text()).toContain('先检查文件')
    expect(wrapper.find('.execution-summary').exists()).toBe(false)
    expect(wrapper.get('.thinking-section__toggle').text()).toContain('2 项')

    await wrapper.get('.thinking-section__toggle').trigger('click')
    expect(wrapper.findAll('.execution-summary__item')).toHaveLength(2)
    expect(wrapper.findAll('.execution-summary__status').map(node => node.text())).toEqual(['完成', '失败'])
    expect(wrapper.findAll('.execution-summary__duration').map(node => node.text())).toEqual(['1.22 s', '905 ms'])
  })
})
