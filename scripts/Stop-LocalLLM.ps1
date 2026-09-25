#requires -Version 7.2
param([string]$ConfigPath=(Join-Path $PSScriptRoot '../config/support-config.json'))
$ErrorActionPreference='Stop'
$cfg=Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$statePath=Join-Path $cfg.target.root 'runtime/server.json'
if (-not (Test-Path -LiteralPath $statePath)) { Write-Output 'Already stopped.'; exit 0 }
$state=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$instance=Get-Process -Id $state.pid -ErrorAction SilentlyContinue
if (-not $instance) { Write-Output 'Already stopped.'; exit 0 }
if ($instance.Path -ne $cfg.target.executable -or $instance.StartTime.ToUniversalTime().Ticks -ne $state.startUtcTicks) { throw 'PID identity differs. No process was stopped.' }
[ordered]@{pid=$instance.Id;startUtcTicks=$state.startUtcTicks;requestedAt=(Get-Date -Format o)} |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $cfg.target.root 'runtime/stop-request.json') -Encoding utf8
Stop-Process -Id $instance.Id
if(-not $instance.WaitForExit(10000)){throw 'Server did not exit within 10 seconds.'}
$shutdownMutex=[Threading.Mutex]::new($false,('Local\LocalStudioLLM-'+$cfg.inference.port))
$acquired=$false
try{
    try{$acquired=$shutdownMutex.WaitOne(10000)}catch [Threading.AbandonedMutexException]{$acquired=$true}
    if(-not $acquired){throw 'Server exited but launcher cleanup has not finished.'}
}finally{
    if($acquired){$shutdownMutex.ReleaseMutex()}
    $shutdownMutex.Dispose()
}
Write-Output "Stopped LocalLLM PID $($instance.Id)."
