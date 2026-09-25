#requires -Version 7.2
param([string]$Python='python',[switch]$Install)
$ErrorActionPreference='Stop'
$source=Split-Path $PSScriptRoot -Parent
$configPath=Join-Path $source 'config/support-config.json'
$pythonExe=(Get-Command $Python -ErrorAction Stop).Source
$version=& $pythonExe -c 'import sys; print(str(sys.version_info.major)+"."+str(sys.version_info.minor))'
if ($LASTEXITCODE -ne 0 -or $version -ne '3.11') { throw 'Pass -Python with the path to Python 3.11.' }
foreach($tool in @('uv','node','npm.cmd')) { Get-Command $tool -ErrorAction Stop | Out-Null }
if (-not (Test-Path -LiteralPath $configPath)) {
    $config=Get-Content -LiteralPath (Join-Path $source 'config/support-config.example.json') -Raw | ConvertFrom-Json
    $config.supporter.pythonExecutable=$pythonExe
    [IO.File]::WriteAllText($configPath,($config | ConvertTo-Json -Depth 20),[Text.UTF8Encoding]::new($false))
}
$config=Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
if ($config.target.root -ne 'C:\AI\LocalLLM') { throw 'This release supports the fixed C:\AI\LocalLLM root only.' }
if (-not $Install) { Write-Output 'Configuration ready. Review config/support-config.json, then rerun with -Install to download dependencies and models.'; return }
$root=$config.target.root
if ((Test-Path -LiteralPath "$root/data/open-webui/webui.db") -or (Test-Path -LiteralPath "$root/runtime/installed-manifest.json")) {
    throw 'An existing LocalLLM installation was found. Automatic replacement is refused; keep its configuration and data. Use individual scripts only after reviewing the migration.'
}
& (Join-Path $PSScriptRoot 'Install-LocalLLM.ps1') -ConfigPath $configPath
if ($LASTEXITCODE -ne 0) { throw 'Model installation failed' }
$env:UV_CACHE_DIR="$root/cache/uv"
& (Get-Command uv).Source venv "$root/apps/open-webui/.venv" --python $pythonExe
if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed' }
& (Get-Command uv).Source pip install --python $config.chatApp.python -r (Join-Path $source 'config/open-webui-requirements.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
& (Join-Path $PSScriptRoot 'Install-DesktopApp.ps1')
& (Join-Path $PSScriptRoot 'Deploy-ChatEntrypoints.ps1')
& (Join-Path $PSScriptRoot 'Write-AgentConfig.ps1')
& (Join-Path $PSScriptRoot 'Start-ChatApp.ps1')
& $config.chatApp.python -X utf8 (Join-Path $PSScriptRoot 'Configure-ChatApp.py')
if ($LASTEXITCODE -ne 0) { throw 'Chat model/tool configuration failed' }
Write-Output "Installed. Open $root/Local Studio.lnk"
