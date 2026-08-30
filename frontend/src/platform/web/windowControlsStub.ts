import { defineComponent } from 'vue'

/**
 * Web 构建的窗口控件占位：渲染为空节点。
 * 通过 vite/tsconfig 的 @window-controls 别名按平台切换，
 * 保证 Web build 永不解析 DesktopWindowControls 与任何 @tauri-apps/* 模块。
 */
const WindowControlsStub = defineComponent({
  name: 'WindowControlsStub',
  render: () => null
})

export { WindowControlsStub }
export default WindowControlsStub
