#requires -Version 7.2
$ErrorActionPreference='Stop'
$support=Split-Path $PSScriptRoot -Parent
$config=Get-Content -LiteralPath "$support/config/support-config.json" -Raw | ConvertFrom-Json
$root=$config.target.root
$app=Join-Path $root 'apps/local-studio-desktop'
New-Item -ItemType Directory -Force -Path $app,"$root/cache/npm-desktop","$root/cache/electron-download" | Out-Null
Copy-Item -LiteralPath "$support/desktop/package-lock.json","$support/desktop/package.json","$support/desktop/main.cjs","$support/desktop/preload.cjs" -Destination $app -Force
$env:ELECTRON_CACHE="$root/cache/electron-download"
$env:electron_config_cache="$root/cache/electron-download"
Push-Location -LiteralPath $app
try { & (Get-Command npm.cmd -ErrorAction Stop).Source ci --cache "$root/cache/npm-desktop" --no-audit --no-fund } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'Electron install failed' }
& (Get-Command node -ErrorAction Stop).Source "$app/node_modules/electron/install.js"
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath "$app/node_modules/electron/dist/electron.exe")) { throw 'Electron binary installation failed' }
Copy-Item -LiteralPath "$app/package-lock.json" -Destination "$support/desktop/package-lock.json" -Force
$pythonw=Join-Path (Split-Path $config.chatApp.python -Parent) 'pythonw.exe'
$launcher="$support/scripts/Run-DesktopApp.py"
$cmd="@echo off`r`nchcp 65001 >nul`r`nstart `"Local Studio`" `"$pythonw`" -X utf8 `"$launcher`"`r`n"
foreach ($name in @('Local Studio.cmd','Start-ChatApp.cmd')) {
    [IO.File]::WriteAllText((Join-Path $root $name),$cmd,[Text.UTF8Encoding]::new($false))
}
$shell=New-Object -ComObject WScript.Shell
$shortcut=$shell.CreateShortcut((Join-Path $root 'Local Studio.lnk'))
$shortcut.TargetPath=$pythonw
$shortcut.Arguments="-X utf8 `"$launcher`""
$shortcut.WorkingDirectory=$root
$shortcut.IconLocation="$app/node_modules/electron/dist/electron.exe,0"
$shortcut.Save()
Write-Output "Desktop app installed: $root/Local Studio.lnk"
