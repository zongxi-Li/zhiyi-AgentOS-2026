# Repository Structure P0 Design

## Goal

整理仓库根目录，保留当前运行能力，同时让根目录只展示应用、运维、文档和工具，以及一个生产 Compose 配置和一个生产环境模板。

## Target structure

    apps/
    ├── agent/
    ├── agentOS/
    ├── backend/
    ├── frontend/
    └── desktop/

    ops/
    ├── docker/
    ├── deploy/
    └── scripts/

    .config/
    ├── compose/
    │   ├── dev.yaml
    │   ├── windows.yaml
    │   ├── windows-prod.yaml
    │   └── release.yaml
    └── env/
        ├── windows.example
        ├── release.example
        └── package.example

    docs/
    tools/
    data/                 # 本地运行数据，继续忽略

    README.md
    compose.yaml          # 唯一根路径生产 Compose
    .env.example          # 唯一根路径生产环境模板

.config/ 是仓库中的逻辑隐藏配置目录，不存放敏感值。真实密钥继续由外部 Secret 目录提供。

## Compose design

根目录的 compose.yaml 合并当前基础定义和生产安全覆盖，能够直接作为生产版本使用。

非生产模式移动到 .config/compose/：

- dev.yaml：源码挂载、热更新和本地开发服务；
- windows.yaml：Windows Docker Desktop 调试端口和缓存；
- windows-prod.yaml：Windows amd64 预构建镜像；
- release.yaml：离线发布镜像和发布包配置。

所有 Compose 相对路径统一以仓库根目录为基准。脚本和文档统一调用：

    docker compose -f compose.yaml -f .config/compose/dev.yaml ...
    docker compose -f compose.yaml -f .config/compose/windows.yaml ...

不再保留空的 observability Compose。

## Environment design

根目录 .env.example 只保留生产部署所需的非敏感变量。开发、Windows 和离线包模板集中到 .config/env/，不重复放在根目录或多个部署目录。

真实 .env、.env.windows 和 Secret 文件属于本地运行状态，不纳入版本控制；迁移脚本和 README 明确指定对应的 --env-file。

## Migration safety

- 保留 agent/ 的全部应用层、Pack、知识库、依赖和测试内容，只改变路径为 apps/agent/；
- 保留 agentOS/ 的运行内核，只改变路径为 apps/agentOS/；
- 不合并 agent/ 与 agentOS/ 的 Python Module；
- 更新 Dockerfile、Compose、脚本、测试和当前文档中的路径；
- 历史文档中的旧路径只在路径确实表示当前代码时更新，历史迁移证据不改写其历史语义；
- 移动和删除前检查目标路径、工作区状态和引用关系。

## Verification

验证以下内容：

1. 根目录只存在一个 Compose YAML 和一个环境模板；
2. apps/、ops/ 目录内容完整；
3. 生产 Compose 使用 --env-file .env.example 能解析；
4. 开发和 Windows 叠加 Compose 能解析；
5. Python AgentOS 测试和前端构建通过；
6. 旧根路径、旧 Compose 文件名和旧配置路径没有活动代码引用；
7. git diff --check 通过。
