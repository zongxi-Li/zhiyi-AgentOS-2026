import { shallowMount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import MessageBubble from './MessageBubble.vue'
import { chatApi } from '@/services/api/chat'

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

  it('renders a safe inline approval card without host authority fields', () => {
    const wrapper = shallowMount(MessageBubble, {
      props: {
        message: {
          id: 'assistant-approval',
          role: 'assistant',
          content: '等待文件操作确认',
          createdAt: new Date('2026-08-03T12:00:00Z'),
          executionSummary: [{
            stage: 'tool:write_file:call_approval',
            status: 'approval_required',
            description: 'Write file: hello.txt',
            approval: {
              approvalId: 'approval_test',
              toolCallId: 'call_approval',
              invocationId: 'call_approval',
              toolName: 'write_file',
              capabilityId: 'fs.write',
              relativePath: 'hello.txt',
              operationSummary: 'Write file: hello.txt',
              createdAt: '2026-08-03T12:00:00Z',
              status: 'pending',
              sessionId: 'chat_session'
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

    expect(wrapper.find('.approval-work').exists()).toBe(true)
    expect(wrapper.findAll('.approval-work__button')).toHaveLength(3)
    expect(wrapper.find('.approval-work').text()).toContain('fs.write')
    expect(wrapper.find('.approval-work').text()).toContain('hello.txt')
    expect(wrapper.text()).not.toContain('C:\\Users\\LZX')
    expect(wrapper.text()).not.toContain('grant_')
    expect(wrapper.text()).not.toContain('credential')
  })

  it('sends the original approval correlation when allowing once', async () => {
    const resolve = vi.spyOn(chatApi, 'resolveApproval').mockResolvedValue({
      approvalId: 'approval_test',
      status: 'resolved',
      decision: 'allow_once'
    })
    const wrapper = shallowMount(MessageBubble, {
      props: {
        message: {
          id: 'assistant-approval-action',
          role: 'assistant',
          content: '等待确认',
          createdAt: new Date('2026-08-03T12:00:00Z'),
          executionSummary: [{
            stage: 'tool:write_file:call_approval',
            status: 'approval_required',
            description: 'Write file: hello.txt',
            approval: {
              approvalId: 'approval_test',
              toolCallId: 'call_approval',
              invocationId: 'call_approval',
              toolName: 'write_file',
              capabilityId: 'fs.write',
              relativePath: 'hello.txt',
              operationSummary: 'Write file: hello.txt',
              createdAt: '2026-08-03T12:00:00Z',
              status: 'pending',
              sessionId: 'chat_session'
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

    await wrapper.find('.approval-work__button.is-primary').trigger('click')
    expect(resolve).toHaveBeenCalledWith('approval_test', {
      decision: 'allow_once',
      sessionId: 'chat_session',
      invocationId: 'call_approval',
      capabilityId: 'fs.write',
      relativePath: 'hello.txt'
    })
    await wrapper.findAll('.approval-work__button')[1].trigger('click')
    await wrapper.findAll('.approval-work__button')[2].trigger('click')
    expect(resolve.mock.calls.map(call => call[1].decision)).toEqual([
      'allow_once',
      'allow_session',
      'deny'
    ])
    resolve.mockRestore()
  })

  it('does not render approval for read/list activity', () => {
    const wrapper = shallowMount(MessageBubble, {
      props: {
        message: {
          id: 'assistant-read-list',
          role: 'assistant',
          content: '读取完成',
          createdAt: new Date('2026-08-03T12:00:00Z'),
          executionSummary: [
            {
              stage: 'tool:read_file:call_read',
              status: 'completed',
              description: 'Read file',
              activity: { kind: 'file_read', capabilityId: 'fs.read', relativePath: 'hello.txt' }
            },
            {
              stage: 'tool:list_files:call_list',
              status: 'completed',
              description: 'Listed directory',
              activity: { kind: 'file_list', capabilityId: 'fs.list', relativePath: '.' }
            }
          ]
        }
      },
      global: { stubs: { 'el-icon': true, 'el-tooltip': { template: '<span><slot /></span>' }, 'el-progress': true, ImageViewer: true } }
    })

    expect(wrapper.find('.approval-work').exists()).toBe(false)
  })

  it('renders shell approval as allow-once or deny with the host risk notice', () => {
    const wrapper = shallowMount(MessageBubble, {
      props: {
        message: {
          id: 'assistant-shell-approval',
          role: 'assistant',
          content: 'command approval',
          createdAt: new Date('2026-08-03T12:00:00Z'),
          executionSummary: [{
            stage: 'tool:run_command:call-shell',
            status: 'approval_required',
            description: 'Run command',
            approval: {
              approvalId: 'approval-shell', toolCallId: 'call-shell', invocationId: 'call-shell',
              toolName: 'run_command', capabilityId: 'shell.exec', relativePath: '.',
              operationSummary: 'Run command: echo hello', operation: 'Run command',
              command: 'echo hello', cwd: '.',
              riskNotice: '当前 Windows 用户权限', createdAt: '2026-08-03T12:00:00Z',
              status: 'pending', sessionId: 'chat_session'
            }
          }]
        }
      },
      global: { stubs: { 'el-icon': true, 'el-tooltip': { template: '<span><slot /></span>' }, 'el-progress': true, ImageViewer: true } }
    })

    expect(wrapper.findAll('.approval-work__button')).toHaveLength(2)
    expect(wrapper.find('.approval-work').text()).toContain('shell.exec')
    expect(wrapper.find('.approval-work').text()).toContain('当前 Windows 用户权限')
  })

  it('keeps approval and resulting file activity associated', () => {
    const wrapper = shallowMount(MessageBubble, {
      props: {
        message: {
          id: 'assistant-approval-result',
          role: 'assistant',
          content: '文件操作结束',
          createdAt: new Date('2026-08-03T12:00:00Z'),
          executionSummary: [
            {
              stage: 'tool:write_file:call-approved',
              status: 'completed',
              description: 'Created file',
              activity: { kind: 'file_write', relativePath: 'approved.txt' },
              approval: {
                approvalId: 'approval-approved', toolCallId: 'call-approved', invocationId: 'call-approved',
                toolName: 'write_file', capabilityId: 'fs.write', relativePath: 'approved.txt',
                operationSummary: 'Write file: approved.txt', createdAt: '2026-08-03T12:00:00Z',
                status: 'approved', sessionId: 'chat_session'
              }
            },
            {
              stage: 'tool:patch_file:call-denied',
              status: 'failed',
              description: 'Patch denied',
              activity: { kind: 'file_patch', relativePath: 'denied.txt', errorCode: 'PERMISSION_DENIED' },
              approval: {
                approvalId: 'approval-denied', toolCallId: 'call-denied', invocationId: 'call-denied',
                toolName: 'patch_file', capabilityId: 'fs.patch', relativePath: 'denied.txt',
                operationSummary: 'Patch file: denied.txt', createdAt: '2026-08-03T12:00:00Z',
                status: 'denied', sessionId: 'chat_session'
              }
            }
          ]
        }
      },
      global: { stubs: { 'el-icon': true, 'el-tooltip': { template: '<span><slot /></span>' }, 'el-progress': true, ImageViewer: true } }
    })

    expect(wrapper.findAll('.approval-work__card')).toHaveLength(2)
    expect(wrapper.find('.file-work').text()).toContain('PERMISSION_DENIED')
    expect(wrapper.find('.approval-work').text()).toContain('已允许')
    expect(wrapper.find('.approval-work').text()).toContain('已拒绝')
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
        }
      },
      global: { stubs: { 'el-icon': true, 'el-tooltip': { template: '<span><slot /></span>' }, 'el-progress': true, ImageViewer: true } }
    })

    const status = wrapper.find('.continuation-status')
    expect(status.exists()).toBe(true)
    expect(status.text()).toContain('执行脉络')
    expect(status.text()).toContain('等待模型继续')
    expect(wrapper.find('.thinking-status__phase').text()).toBe('已思考（用时 10 秒）')
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
})
