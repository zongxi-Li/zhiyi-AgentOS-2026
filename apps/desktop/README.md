# 知弈 AgentOS 桌面版

知弈 AgentOS 桌面版是基于 Tauri 2 的 Windows 桌面壳。它把现有 Vue 前端打包为本地应用，并通过 HTTP、SSE 和 WebSocket 连接后端 Gateway。

## 一、当前部署结论

- 桌面程序本身运行在用户的 Windows 电脑上，不是在云端运行。
- 当前默认配置连接本机 Gateway：`http://127.0.0.1:9050`。
- 桌面端不负责启动或管理 Backend、AgentOS、Docker、Python、Java、PostgreSQL 和 Redis。
- 当前没有自动更新服务，发布新版本需要重新构建并手动安装安装包。
- 后端可以部署在云端，但桌面程序仍然运行在本地；只需要把 API 地址改为公网 HTTPS Gateway。

## 二、运行架构

```text
Windows 桌面程序
      |
      v
Tauri 2 原生桌面壳
      |
      v
打包后的 Vue 前端（frontend/dist）
      |
      +-- HTTP / SSE / WebSocket
      v
Gateway（默认：127.0.0.1:9050）
      |
      v
Backend / AgentOS / WKN Runtime
      |
      v
PostgreSQL / Redis / 文件存储
```

桌面端与浏览器端共用同一套前端业务代码，但桌面模式会使用桌面平台适配器、原生窗口控制和 Tauri 插件。

## 三、环境要求

开发和打包桌面版需要：

- Windows 10/11；
- Node.js 和 npm；
- Rust stable、MSVC 工具链和 Visual Studio C++ Build Tools；
- Microsoft Edge WebView2 Runtime；
- 如果后端在本机运行，还需要 Docker Desktop。

如果只运行已经打包好的安装包，不需要安装 Node.js 和 Rust，但仍然需要能够访问后端 Gateway。

## 四、首次安装依赖

在项目根目录执行：

```powershell
Set-Location C:\Users\LZX\Desktop\kinlin_ai\frontend
npm ci

Set-Location ..\desktop
npm ci
```

## 五、本地开发

日常体验构建后的前端，可从项目根目录运行：

```powershell
.\ops\scripts\start-desktop-built.ps1 -Build
```

此入口构建 release 桌面程序并加载本地 `frontend/dist`，不启动 Vite；后端 Gateway 仍需在 9050 运行。后续直接运行同一脚本可复用构建产物，源码更新后再加 `-Build`。下述热更新入口继续用于开发。

### 1. 启动本地后端环境

在第一个 PowerShell 窗口执行：

```powershell
Set-Location C:\Users\LZX\Desktop\kinlin_ai
.\ops\scripts\infra\windows\up.ps1 -DebugPorts
```

确认 Gateway 已监听 `127.0.0.1:9050`。

### 2. 启动桌面开发模式

在第二个 PowerShell 窗口执行：

```powershell
Set-Location C:\Users\LZX\Desktop\kinlin_ai\apps\desktop
npm run dev
```

Tauri 会自动执行 `frontend` 的桌面模式 Vite 服务，地址为：

`http://127.0.0.1:15100`

桌面开发模式下不需要再单独执行 `apps\frontend\npm run dev`，否则可能与 Tauri 的 Vite 服务争用 15100 端口。

### 3. 使用桌面快捷方式

项目提供了一个热更新启动脚本：

```text
ops\scripts\start-desktop-hot.ps1
```

桌面上的 **知弈 AgentOS（热更新开发版）** 快捷方式会执行这个脚本。双击后会：

1. 检查前端和桌面端依赖；
2. 关闭正在运行的已安装旧版 `kinlin-desktop.exe`；
3. 检查 15100 端口是否空闲；
4. 启动当前仓库源码的 Tauri 开发版。

修改 `frontend` 源码后，Vite 会自动热更新桌面窗口。该快捷方式只用于开发预览，不生成稳定安装包，也不会替换原来的稳定版快捷方式。

## 六、构建桌面安装包

在 `desktop` 目录执行：

```powershell
Set-Location C:\Users\LZX\Desktop\kinlin_ai\desktop
npm run build
```

构建流程会自动：

1. 执行 `frontend` 的 `build:desktop`；
2. 读取 `frontend/.env.desktop`；
3. 将前端构建结果放入 Tauri 安装包；
4. 生成 NSIS 和 MSI 安装包。

安装包输出目录：

```text
desktop\src-tauri\target\release\bundle\nsis\
desktop\src-tauri\target\release\bundle\msi\
```

通常优先分发 `nsis` 目录中的 `*-setup.exe`。企业环境或需要 Windows Installer 的场景可以分发 `msi` 文件。

注意：桌面构建只包含前端和 Tauri 壳，不包含后端服务、Docker 镜像、数据库或 Redis。

## 七、安装和更新桌面版

当前采用手动更新流程：

1. 关闭正在运行的旧桌面程序；
2. 执行 `desktop\npm run build`；
3. 将 `nsis` 或 `msi` 安装包分发给用户；
4. 运行安装程序覆盖或升级旧版本；
5. 重新打开桌面程序。

发布新版本前，建议同步更新以下版本号：

```text
desktop\src-tauri\tauri.conf.json
desktop\src-tauri\Cargo.toml
desktop\package.json
```

目前没有配置 Tauri Updater、云端安装包存储、版本检查接口或自动更新签名。因此，仅更新 `frontend/dist` 不会自动更新已经安装的桌面程序，必须重新打包并安装。

## 八、连接云端后端

桌面程序可以连接云端，但云端必须提供兼容的 Gateway。修改：

`frontend/.env.desktop`

将：

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:9050
```

改为类似：

```dotenv
VITE_API_BASE_URL=https://api.example.com
```

然后重新构建桌面安装包。

云端 Gateway 需要同时满足：

- HTTPS 访问；
- 正确处理 `/api`、`/ai` 等接口路径；
- 允许 `tauri.localhost` 来源的 CORS；
- 支持 SSE 和 WebSocket；
- 正确转发用户认证信息；
- 提供头像上传和读取接口；
- 配置文件存储、数据库备份和访问权限。

API 地址不是密钥，可以写入构建配置；API Key、JWT 密钥、数据库密码等敏感信息不能写入 README、前端代码或 Git 仓库。

## 九、常见问题

### 修改代码后桌面端没有变化

如果运行的是已安装版本，它使用的是打包时的前端文件。请重新执行：

```powershell
Set-Location C:\Users\LZX\Desktop\kinlin_ai\desktop
npm run build
```

然后安装新生成的安装包。

如果运行的是开发模式，确认使用的是 `desktop\npm run dev`，并在需要时关闭旧的 Tauri 进程后重新启动。

### 页面显示离线或接口请求失败

检查 Gateway 和 Docker 状态：

```powershell
Set-Location C:\Users\LZX\Desktop\kinlin_ai
.\ops\scripts\infra\windows\status.ps1
```

桌面默认请求地址是宿主机的 `127.0.0.1:9050`；不要填写 Backend 容器内部地址。

### 头像无法显示

确认用户头像接口可访问：

`GET /api/users/{userId}/avatar`

该请求需要带有效认证信息，并且云端部署时要保证头像文件不会因容器重建而丢失。

### 从桌面拖拽文件到附件不生效

`tauri.conf.json` 里主窗口配置了 `"dragDropEnabled": false`，这是刻意设置：Tauri 的原生拖放接管在 Windows 上会吞掉 WebView2 的 HTML5 拖放事件，只有关闭它，前端拖拽区（如新建工程附件）才能收到拖放的文件。不要改回 `true`，否则拖拽添加附件会失效，其他功能不受影响。

同理，F11 全屏由前端（`App.vue` 挂载的 `@fullscreen-hotkey`）调用 Tauri 窗口接口实现，无需额外快捷键插件。

## 十、发布检查清单

- [ ] 更新桌面端版本号；
- [ ] 确认 `frontend/.env.desktop` 指向正确的环境；
- [ ] 执行前端构建和桌面构建；
- [ ] 在干净的 Windows 环境安装测试；
- [ ] 验证登录、对话、SSE、WebSocket、头像、文件上传（含拖拽添加附件）和 F11 全屏；
- [ ] 验证云端 CORS、HTTPS 和权限策略；
- [ ] 检查安装包中没有密钥和本地开发配置；
- [ ] 保存安装包校验和，并通过可信渠道分发。

## 十一、当前未实现的能力

以下能力暂未纳入当前桌面版本：

- Tauri 自动更新；
- 云端安装包发布和版本检查；
- 桌面端运行时 Supervisor；
- Backend 或 AgentOS 随桌面程序打包；
- Docker 自动安装和启动；
- 系统托盘；
- 本地离线推理和自动故障恢复。
