#requires -Version 7.2
param([string]$ConfigPath=(Join-Path $PSScriptRoot '../config/support-config.json'))
$ErrorActionPreference='Stop'
$cfg=Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$backend=if($cfg.inference.backend){[string]$cfg.inference.backend}else{'llama.cpp'}
if($backend -notin @('llama.cpp','strata')){throw "Unsupported inference backend: $backend"}
$statePath=Join-Path $cfg.target.root 'runtime/server.json'
if (-not (Test-Path -LiteralPath $statePath)) { Write-Output 'Already stopped.'; exit 0 }
$state=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$instance=Get-Process -Id $state.pid -ErrorAction SilentlyContinue
if ($instance -and ($instance.Path -ne $cfg.target.executable -or $instance.StartTime.ToUniversalTime().Ticks -ne $state.startUtcTicks)) { throw 'PID identity differs. No process was stopped.' }
$stateBackend=if($state.backend){[string]$state.backend}else{'llama.cpp'}
if($stateBackend -ne $backend -or ($state.executable -and $state.executable -ne $cfg.target.executable)){throw 'Server configuration identity differs. No process was stopped.'}
$server=$instance; $children=@()
if($backend -eq 'strata'){
    $expectedProcessState=Join-Path $cfg.target.root "runtime/strata-process-$($state.launchToken).json"
    if($state.launchToken -notmatch '^[0-9a-f]{32}$' -or [IO.Path]::GetFullPath($state.processStatePath) -ne [IO.Path]::GetFullPath($expectedProcessState)){throw 'Invalid Strata process ownership record. No process was stopped.'}
    # A venv python.exe can be a redirector. Wait briefly for its real interpreter
    # to record its identity before trying to stop an instance still starting.
    $ownershipDeadline=(Get-Date).AddSeconds(10)
    while(-not(Test-Path -LiteralPath $expectedProcessState) -and $instance -and (Get-Date) -lt $ownershipDeadline){
        Start-Sleep -Milliseconds 100
        $instance=Get-Process -Id $state.pid -ErrorAction SilentlyContinue
    }
    if($instance -and ($instance.Path -ne $cfg.target.executable -or $instance.StartTime.ToUniversalTime().Ticks -ne $state.startUtcTicks)){throw 'Launcher identity changed during startup. No process was stopped.'}
    if(-not(Test-Path -LiteralPath $expectedProcessState)){
        if(-not $instance){Write-Output 'Already stopped.'; exit 0}
        throw 'Strata has not recorded job containment. No process was stopped; inspect launcher logs.'
    }
    $processState=Get-Content -LiteralPath $expectedProcessState -Raw | ConvertFrom-Json
    if($processState.launchToken -ne $state.launchToken -or $processState.jobContained -ne $true -or
       ($processState.server.pid -ne $state.pid -and $processState.parentPid -ne $state.pid) -or
       [IO.Path]::GetFullPath($processState.sourceRoot) -ne [IO.Path]::GetFullPath($cfg.strata.sourceRoot) -or
       [IO.Path]::GetFullPath($processState.serverConfigPath) -ne [IO.Path]::GetFullPath($cfg.strata.serverConfigPath)){
        throw 'Strata ownership handshake differs. No process was stopped.'
    }
    $server=Get-Process -Id $processState.server.pid -ErrorAction SilentlyContinue
    if($server -and ($server.Path -ne $processState.server.executable -or $server.StartTime.ToUniversalTime().Ticks -ne $processState.server.startUtcTicks)){
        throw 'Strata interpreter identity differs. No process was stopped.'
    }
    $children=@($processState.children)
    if($server){
        try{
            $unloaded=Invoke-RestMethod ($cfg.target.defaultUrl+'/v1/unload') -Method Post -ContentType 'application/json' -Body '{}' -TimeoutSec 90
            if($unloaded.status -eq 'busy'){throw 'Strata is busy. No process was stopped.'}
            if($unloaded.loaded -ne $false){throw 'Strata did not confirm model release.'}
        }catch{
            if(($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) -or $_.Exception.Message -match 'Strata is busy'){
                throw 'Strata is busy. No process was stopped.'
            }
            # An instance that failed before opening HTTP must still be stoppable
            # during rollback. Terminate only the verified, contained interpreter.
            Write-Output 'Strata unload was unavailable; stopping the verified owned Windows Job Object.'
        }
        # A late reload/MCP child also belongs to the same job. Refresh identities
        # for the post-stop verification; we never stop children by name or PID.
        $latest=Get-Content -LiteralPath $expectedProcessState -Raw | ConvertFrom-Json
        if($latest.launchToken -ne $state.launchToken){throw 'Strata ownership changed during unload. No process was stopped.'}
        $children=@($latest.children)
    }
}
if(-not $server -and -not $instance){
    foreach($childIdentity in $children){
        $remaining=Get-Process -Id $childIdentity.pid -ErrorAction SilentlyContinue
        if($remaining -and $remaining.Path -eq $childIdentity.executable -and $remaining.StartTime.ToUniversalTime().Ticks -eq $childIdentity.startUtcTicks){throw 'Owned Strata child remains after its interpreter exited. Inspect runtime state.'}
    }
    Write-Output 'Already stopped.'; exit 0
}
[ordered]@{pid=$state.pid;startUtcTicks=$state.startUtcTicks;requestedAt=(Get-Date -Format o)} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $cfg.target.root 'runtime/stop-request.json') -Encoding utf8
if($server){
    # Recheck immediately before TerminateProcess, after the potentially long unload.
    $verified=Get-Process -Id $server.Id -ErrorAction SilentlyContinue
    if($verified -and ($verified.Path -ne $server.Path -or $verified.StartTime.ToUniversalTime().Ticks -ne $server.StartTime.ToUniversalTime().Ticks)){throw 'Server identity changed during unload. No process was stopped.'}
    if($verified){Stop-Process -Id $verified.Id}
    if(-not $server.WaitForExit(10000)){throw 'Server did not exit within 10 seconds.'}
}
if($instance -and $instance.Id -ne $server.Id){
    if(-not $instance.WaitForExit(10000)){
        $verified=Get-Process -Id $state.pid -ErrorAction SilentlyContinue
        if($verified -and ($verified.Path -ne $cfg.target.executable -or $verified.StartTime.ToUniversalTime().Ticks -ne $state.startUtcTicks)){throw 'Launcher identity changed. No launcher process was stopped.'}
        if($verified){Stop-Process -Id $verified.Id}
        if(-not $instance.WaitForExit(10000)){throw 'Python launcher did not exit within 10 seconds.'}
    }
}
foreach($childIdentity in $children){
    $remaining=Get-Process -Id $childIdentity.pid -ErrorAction SilentlyContinue
    if($remaining -and $remaining.Path -eq $childIdentity.executable -and $remaining.StartTime.ToUniversalTime().Ticks -eq $childIdentity.startUtcTicks){
        if(-not $remaining.WaitForExit(10000)){throw "Owned Strata child $($childIdentity.pid) did not exit with its job."}
    }
}
$shutdownMutex=[Threading.Mutex]::new($false,('Local\LocalStudioLLM-'+$cfg.inference.port))
$acquired=$false
try{
    try{$acquired=$shutdownMutex.WaitOne(10000)}catch [Threading.AbandonedMutexException]{$acquired=$true}
    if(-not $acquired){throw 'Server exited but launcher cleanup has not finished.'}
}finally{
    if($acquired){$shutdownMutex.ReleaseMutex()}
    $shutdownMutex.Dispose()
}
Write-Output "Stopped LocalLLM PID $($state.pid)."
