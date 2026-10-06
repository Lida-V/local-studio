#requires -Version 7.2
param([switch]$OpenBrowser,[int]$TimeoutSeconds=180,[string]$ConfigPath=(Join-Path $PSScriptRoot '../config/support-config.json'))
$ErrorActionPreference='Stop'
$cfg=Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$backend=if($cfg.inference.backend){[string]$cfg.inference.backend}else{'llama.cpp'}
if($backend -notin @('llama.cpp','strata')){throw "Unsupported inference backend: $backend"}
$statePath=Join-Path $cfg.target.root 'runtime/server.json'
$isRunning=$false
$wrapper=$null
if (Test-Path -LiteralPath $statePath) {
    $state=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $existing=Get-Process -Id $state.pid -ErrorAction SilentlyContinue
    if ($existing -and $existing.Path -eq $cfg.target.executable -and $existing.StartTime.ToUniversalTime().Ticks -eq $state.startUtcTicks) {
        $stateBackend=if($state.backend){[string]$state.backend}else{'llama.cpp'}
        if($stateBackend -ne $backend){throw 'Owned server uses a different backend. Stop it before changing configuration.'}
        $isRunning=$true
    }
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
        $ownedReady=$true
        if($backend -eq 'strata'){
            $ownedReady=$false
            $state=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
            $expectedProcessState=Join-Path $cfg.target.root "runtime/strata-process-$($state.launchToken).json"
            if($state.launchToken -notmatch '^[0-9a-f]{32}$' -or [IO.Path]::GetFullPath($state.processStatePath) -ne [IO.Path]::GetFullPath($expectedProcessState)){throw 'Invalid Strata process ownership record.'}
            $owner=Get-Process -Id $state.pid -ErrorAction SilentlyContinue
            $processState=Get-Content -LiteralPath $expectedProcessState -Raw | ConvertFrom-Json
            $server=Get-Process -Id $processState.server.pid -ErrorAction SilentlyContinue
            $props=Invoke-RestMethod ($cfg.target.defaultUrl+'/props') -TimeoutSec 2
            $ownedReady=($owner -and $owner.Path -eq $cfg.target.executable -and $owner.StartTime.ToUniversalTime().Ticks -eq $state.startUtcTicks -and
                $processState.launchToken -eq $state.launchToken -and $processState.jobContained -eq $true -and
                ($processState.server.pid -eq $state.pid -or $processState.parentPid -eq $state.pid) -and
                [IO.Path]::GetFullPath($processState.sourceRoot) -eq [IO.Path]::GetFullPath($cfg.strata.sourceRoot) -and
                [IO.Path]::GetFullPath($processState.serverConfigPath) -eq [IO.Path]::GetFullPath($cfg.strata.serverConfigPath) -and
                $server -and $server.Path -eq $processState.server.executable -and $server.StartTime.ToUniversalTime().Ticks -eq $processState.server.startUtcTicks -and
                $health.loaded -eq $true -and $props.modalities.vision -eq $true -and $props.is_sleeping -eq $false)
        }
        if ($health.status -eq 'ok' -and $cfg.inference.alias -in @($models.data.id) -and $ownedReady) {
            Write-Output "Ready: $($cfg.target.defaultUrl) | $($cfg.inference.alias)"
            if ($OpenBrowser) { Start-Process $cfg.target.defaultUrl }
            exit 0
        }
    } catch { }
    if ($wrapper -and $wrapper.HasExited) { throw 'Server launcher exited. Inspect logs/launcher-*.stderr.log and server-*.stderr.log.' }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)
throw 'Startup timed out. Process was retained for inspection; use Stop-LocalLLM.ps1 after checking logs.'
