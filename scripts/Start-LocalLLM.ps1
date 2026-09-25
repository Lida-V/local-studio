#requires -Version 7.2
param([switch]$OpenBrowser,[int]$TimeoutSeconds=180,[string]$ConfigPath=(Join-Path $PSScriptRoot '../config/support-config.json'))
$ErrorActionPreference='Stop'
$cfg=Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$statePath=Join-Path $cfg.target.root 'runtime/server.json'
$isRunning=$false
if (Test-Path -LiteralPath $statePath) {
    $state=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $existing=Get-Process -Id $state.pid -ErrorAction SilentlyContinue
    if ($existing -and $existing.Path -eq $cfg.target.executable -and $existing.StartTime.ToUniversalTime().Ticks -eq $state.startUtcTicks) { $isRunning=$true }
}
if (-not $isRunning) {
    $probe=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Parse($cfg.inference.host),$cfg.inference.port)
    try { $probe.Start() } catch { throw "Port $($cfg.inference.port) is occupied. No other process was stopped." } finally { $probe.Stop() }
    $worker=Join-Path $PSScriptRoot 'Run-LocalLLM.ps1'
    $runArgs=@('-NoProfile','-File',('"'+$worker+'"'),'-ConfigPath',('"'+[IO.Path]::GetFullPath($ConfigPath)+'"'))
    $workerStamp=Get-Date -Format 'yyyyMMdd-HHmmss'
    $wrapper=Start-Process -FilePath (Join-Path $PSHOME 'pwsh.exe') -ArgumentList $runArgs -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $cfg.target.root "logs/launcher-$workerStamp.stdout.log") -RedirectStandardError (Join-Path $cfg.target.root "logs/launcher-$workerStamp.stderr.log")
}
$deadline=(Get-Date).AddSeconds($TimeoutSeconds)
do {
    try {
        $health=Invoke-RestMethod ($cfg.target.defaultUrl+'/health') -TimeoutSec 2
        $models=Invoke-RestMethod ($cfg.target.defaultUrl+'/v1/models') -TimeoutSec 2
        if ($health.status -eq 'ok' -and $cfg.inference.alias -in @($models.data.id)) {
            Write-Output "Ready: $($cfg.target.defaultUrl) | $($cfg.inference.alias)"
            if ($OpenBrowser) { Start-Process $cfg.target.defaultUrl }
            exit 0
        }
    } catch { }
    if ($wrapper -and $wrapper.HasExited) { throw 'Server launcher exited. Inspect logs/launcher-*.stderr.log and server-*.stderr.log.' }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)
throw 'Startup timed out. Process was retained for inspection; use Stop-LocalLLM.ps1 after checking logs.'
