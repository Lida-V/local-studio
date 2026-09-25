#requires -Version 7.2
param([switch]$OpenBrowser)
$ErrorActionPreference='Stop'
$root='C:\AI\LocalLLM'
& (Join-Path $PSScriptRoot 'Start-AgentWorker.ps1')
& "$root\apps\open-webui\.venv\Scripts\python.exe" -X utf8 (Join-Path $PSScriptRoot 'Check-Generation.py')
if ($LASTEXITCODE -eq 3) {
    Write-Output 'Image generation is active; Qwen will resume automatically.'
    if ($OpenBrowser) { Start-Process 'http://127.0.0.1:18081' }
    exit 0
}
if ($LASTEXITCODE -ne 0) { throw 'Unable to check image generation state.' }
& (Join-Path $PSScriptRoot 'Start-LocalLLM.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Qwen startup failed' }
$up=$false
try { $up=(Invoke-RestMethod 'http://127.0.0.1:18081/health' -TimeoutSec 2).status -eq $true } catch { }
if (-not $up) {
    $probe=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,18081)
    try { $probe.Start() } finally { $probe.Stop() }
    $stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
    $args=@('-X','utf8',('"'+(Join-Path $PSScriptRoot 'Run-ChatApp.py')+'"'))
    Start-Process -FilePath "$root\apps\open-webui\.venv\Scripts\python.exe" -ArgumentList $args -WindowStyle Hidden -WorkingDirectory $root -RedirectStandardOutput "$root\logs\chatapp-$stamp.stdout.log" -RedirectStandardError "$root\logs\chatapp-$stamp.stderr.log" | Out-Null
    $deadline=(Get-Date).AddMinutes(3)
    do {
        Start-Sleep -Seconds 2
        try { $up=(Invoke-RestMethod 'http://127.0.0.1:18081/health' -TimeoutSec 2).status -eq $true } catch { }
    } until ($up -or (Get-Date) -gt $deadline)
    if (-not $up) { throw 'Chat app startup timed out; inspect C:\AI\LocalLLM\logs\chatapp-*.stderr.log' }
}
Write-Output 'Chat app ready: http://127.0.0.1:18081'
if ($OpenBrowser) { Start-Process 'http://127.0.0.1:18081' }
