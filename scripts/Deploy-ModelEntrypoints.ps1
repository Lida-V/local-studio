#requires -Version 7.2
$ErrorActionPreference = 'Stop'
$support = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$config = Get-Content -LiteralPath (Join-Path $support 'config/support-config.json') -Raw | ConvertFrom-Json
$root = [IO.Path]::GetFullPath($config.target.root)
$python = $config.chatApp.python
$backup = Join-Path $root ('runtime/maintenance-backups/model-entries-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
foreach ($entry in @(@('HuihuiでLocal Studio.cmd','huihui-qwen'), @('通常QwenでLocal Studio.cmd','qwen-standard'), @('Flash NextでLocal Studio.cmd','qwen-flash-next'))) {
    $path = Join-Path $root $entry[0]
    if (Test-Path -LiteralPath $path) {
        New-Item -ItemType Directory -Force -Path $backup | Out-Null
        Copy-Item -LiteralPath $path -Destination (Join-Path $backup $entry[0])
    }
    $content = "@echo off`r`nchcp 65001 >nul`r`n`"$python`" -B -X utf8 `"$support\scripts\Local-Studio.py`" model-select $($entry[1])`r`nif errorlevel 1 (pause & exit /b 1)`r`ncall `"$root\Start-ChatApp.cmd`"`r`n"
    [IO.File]::WriteAllText($path, $content, [Text.UTF8Encoding]::new($false))
}
$guide = Join-Path $root 'model-profiles.md'
if (Test-Path -LiteralPath $guide) {
    New-Item -ItemType Directory -Force -Path $backup | Out-Null
    Copy-Item -LiteralPath $guide -Destination (Join-Path $backup 'model-profiles.md')
}
Copy-Item -LiteralPath (Join-Path $support 'docs/model-profiles.md') -Destination $guide
Write-Output 'Installed catalog model switch entries. Uninstalled profiles refuse activation.'
