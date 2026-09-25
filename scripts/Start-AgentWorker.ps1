#requires -Version 7.2
$ErrorActionPreference='Stop'
$python='C:\AI\LocalLLM\apps\open-webui\.venv\Scripts\python.exe'
$entry=Join-Path $PSScriptRoot 'Local-Studio.py'
& $python -X utf8 $entry worker-check
if ($LASTEXITCODE -eq 0) { return }
Start-Process -FilePath $python -ArgumentList '-X','utf8',('"'+$entry+'"'),'daemon' -WindowStyle Hidden -RedirectStandardOutput 'C:\AI\LocalLLM\logs\agent-worker.stdout.log' -RedirectStandardError 'C:\AI\LocalLLM\logs\agent-worker.stderr.log' | Out-Null
for ($i=0;$i -lt 20;$i++) {
    Start-Sleep -Milliseconds 250
    & $python -X utf8 $entry worker-check
    if ($LASTEXITCODE -eq 0) { return }
}
throw 'Agent worker did not start'
