param(
    [string]$EnvFile = ".env.windows",
    [switch]$DebugPorts,
    [switch]$Build,
    [ValidateSet("frontend", "backend", "ai-service", "postgres", "redis")]
    [string]$BuildService,
    [switch]$FullPreflight,
    [switch]$ApplyAgentOSSchema
)

. (Join-Path $PSScriptRoot "_common.ps1")
$context = Get-KinlinWindowsContext $EnvFile
if ($Build -and $BuildService) { throw "Use either -Build or -BuildService, not both" }
if ($FullPreflight) {
    & (Join-Path $PSScriptRoot "preflight.ps1") -EnvFile $context.EnvFile -Full
} else {
    & (Join-Path $PSScriptRoot "preflight.ps1") -EnvFile $context.EnvFile
}
$env:DOCKER_BUILDKIT = "1"
$env:COMPOSE_DOCKER_CLI_BUILD = "1"
Write-KinlinContext $context
if ($BuildService) {
    Write-Host "Building only $BuildService before starting the full development stack"
    Invoke-KinlinCompose $context build $BuildService
}
$profileArguments = @()
if ($DebugPorts) { $profileArguments = @("--profile", "debug-ports") }
if ($Build) {
    Write-Host "Building the Windows development images before measuring container startup"
    Invoke-KinlinCompose $context @profileArguments build
}
$rendered = Invoke-KinlinComposeOutput $context config --format json
$formal = Get-KinlinFormalExecutionConfiguration (($rendered -join "`n") | ConvertFrom-Json)
if ($ApplyAgentOSSchema -and -not $formal.Dispatch) {
    throw "-ApplyAgentOSSchema requires the complete formal execution configuration (including Dispatch)"
}
if ($formal.Dispatch) {
    if ($ApplyAgentOSSchema) {
        # A failed upgrade leaves AI stopped. Never restart against partially
        # prepared ledgers, and never stop the database or delete its volumes.
        Invoke-KinlinCompose $context stop ai-service
    }
    $maintenance = @("run", "--rm", "--no-deps", "-T", "ai-service", "python", "/app/scripts/prepare_agentos_runtime.py")
    if ($ApplyAgentOSSchema) { $maintenance += "--apply" }
    Invoke-KinlinCompose $context @maintenance
}
$arguments = $profileArguments + @("up", "-d", "--wait")
$startupStopwatch = [System.Diagnostics.Stopwatch]::StartNew()
Invoke-KinlinCompose $context @arguments
$startupStopwatch.Stop()
Write-Host ("Windows Compose readiness completed in {0:N2}s (image build excluded)" -f $startupStopwatch.Elapsed.TotalSeconds)
Write-Host "Windows development environment is ready at $($context.PublicOrigin)"
