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

  it('renders terminal work inline with bounded command output', () => {
    const wrapper = shallowMount(MessageBubble, {
      props: {
        message: {
          id: 'assistant-terminal',
          role: 'assistant',
          content: '命令已执行。',
          createdAt: new Date('2026-08-03T12:00:00Z'),
          executionSummary: [{
            stage: 'tool:terminal:call_1',
            status: 'completed',
            description: '终端命令执行完成',
            terminal: {
              command: 'python -c "print(1)"',
              cwd: '/app/workspace',
              exitCode: 0,
              stdout: '1\n',
              stderr: '',
              timedOut: false,
              truncated: false
            }
          }]
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

    expect(wrapper.find('.terminal-work').exists()).toBe(true)
    expect(wrapper.find('.terminal-work__command').text()).toContain('python -c')
    expect(wrapper.find('.terminal-work__output').text()).toContain('1')
  })

  it('renders workspace file activity without exposing host paths', () => {
    const wrapper = shallowMount(MessageBubble, {
      props: {
        message: {
          id: 'assistant-files',
          role: 'assistant',
          content: '文件已更新。',
          createdAt: new Date('2026-08-03T12:00:00Z'),
          executionSummary: [{
            stage: 'tool:patch_file:call_1',
            status: 'completed',
            description: 'Edited file',
            activity: {
              kind: 'file_patch',
              capabilityId: 'fs.patch',
              relativePath: 'src/hello.txt',
              summary: 'Edited file',
              addedLines: 1,
              removedLines: 1
            }
          }]
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

    expect(wrapper.find('.file-work').exists()).toBe(true)
    expect(wrapper.find('.file-work__path').text()).toBe('src/hello.txt')
    expect(wrapper.find('.file-work').text()).toContain('+1 / -1')
    expect(wrapper.text()).not.toContain('C:\\Users\\LZX')
  })

  it('renders a failed file activity with its stable error code', () => {
    const wrapper = shallowMount(MessageBubble, {
      props: {
        message: {
          id: 'assistant-file-error',
          role: 'assistant',
          content: '文件未更新。',
          createdAt: new Date('2026-08-03T12:00:00Z'),
          executionSummary: [{
            stage: 'tool:write_file:call_2',
            status: 'failed',
            description: '写入失败',
            activity: {
              kind: 'file_write',
              relativePath: 'src/hello.txt',
              errorCode: 'PATH_OUTSIDE_WORKSPACE'
            }
          }]
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

    expect(wrapper.find('.file-work__error').text()).toContain('PATH_OUTSIDE_WORKSPACE')
  })
})
