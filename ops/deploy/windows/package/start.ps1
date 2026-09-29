param([string]$EnvFile = ".env")

. (Join-Path $PSScriptRoot ".kinlin\common.ps1")
$context = Read-KinlinPackageEnv $EnvFile
Initialize-KinlinPackageSecrets $context
Ensure-KinlinPackageImages $context
Invoke-KinlinPackageCompose $context config --quiet
Invoke-KinlinPackageCompose $context up -d --pull never --no-build --wait postgres redis ai-service
# schema mutation 的唯一正式 owner 是 backend 启动期 Flyway（flyway.enabled=true）。
# schema-tool 仅为 MANUAL_TOOL（见 compose.yaml），不得在此自动执行迁移。
Invoke-KinlinPackageCompose $context up -d --pull never --no-build --wait
Write-Host "Kinlin AI is ready at http://127.0.0.1:$($context.HttpPort)"
