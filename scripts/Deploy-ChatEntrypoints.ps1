#requires -Version 7.2
$ErrorActionPreference='Stop'
$root='C:\AI\LocalLLM'
$pwsh=Join-Path $PSHOME 'pwsh.exe'
$support=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$start="@echo off`r`nchcp 65001 >nul`r`nstart `"Local Studio`" `"$root\apps\open-webui\.venv\Scripts\pythonw.exe`" -X utf8 `"$support\scripts\Run-DesktopApp.py`"`r`n"
$stop="@echo off`r`nchcp 65001 >nul`r`n`"$root\apps\open-webui\.venv\Scripts\python.exe`" -X utf8 `"$support\scripts\Stop-ChatApp.py`"`r`nif errorlevel 1 (pause & exit /b 1)`r`n`"$pwsh`" -NoProfile -File `"$support\scripts\Stop-LocalLLM.ps1`"`r`nif errorlevel 1 pause`r`n"
[IO.File]::WriteAllText("$root\Start-ChatApp.cmd",$start,[Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText("$root\Local Studio.cmd",$start,[Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText("$root\Stop-ChatApp.cmd",$stop,[Text.UTF8Encoding]::new($false))
Copy-Item -LiteralPath "$support\docs\USER-GUIDE.md" -Destination "$root\USER-GUIDE.md" -Force
New-Item -ItemType Directory -Force -Path "$root\workspace" | Out-Null
if (-not (Test-Path -LiteralPath "$root\workspace\AGENTS.md")) {
    Copy-Item -LiteralPath "$support\docs\workspace-AGENTS.md" -Destination "$root\workspace\AGENTS.md"
}
Write-Output 'Deployed Start-ChatApp.cmd and Stop-ChatApp.cmd.'
