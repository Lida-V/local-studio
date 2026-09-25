#requires -Version 7.2
$ErrorActionPreference='Stop'
$source=Split-Path $PSScriptRoot -Parent
$config=Get-Content -LiteralPath "$source/config/support-config.json" -Raw | ConvertFrom-Json
$python=$config.chatApp.python
$entry=Join-Path $PSScriptRoot 'Local-Studio.py'
$server=@{command=$python;args=@('-X','utf8',$entry,'mcp')}
$mcpPath=Join-Path $source '.mcp.json'
$mcp=if(Test-Path -LiteralPath $mcpPath){Get-Content -LiteralPath $mcpPath -Raw | ConvertFrom-Json -AsHashtable}else{@{mcpServers=@{}}}
if(-not $mcp.ContainsKey('mcpServers')){$mcp.mcpServers=@{}}
if($mcp.mcpServers.ContainsKey('local_studio')){throw 'local_studio already exists; review it before replacing.'}
$mcp.mcpServers.local_studio=$server
[IO.File]::WriteAllText($mcpPath,($mcp | ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
New-Item -ItemType Directory -Path "$source/.codex" -Force | Out-Null
$tomlPath=Join-Path $source '.codex/config.toml'
if(Test-Path -LiteralPath $tomlPath){
    if(Select-String -LiteralPath $tomlPath -Pattern '^\[mcp_servers\.local_studio\]' -Quiet){throw 'Codex local_studio already exists; review it before replacing.'}
}
$toml="`n[mcp_servers.local_studio]`ncommand = '"+$python.Replace('\','/')+"'`nargs = ['-X', 'utf8', '"+$entry.Replace('\','/')+"', 'mcp']`nstartup_timeout_sec = 30`ntool_timeout_sec = 60`n"
if($toml.Contains("''")){throw 'Unexpected empty path'}
[IO.File]::AppendAllText($tomlPath,$toml,[Text.UTF8Encoding]::new($false))
$cmd="@echo off`r`nchcp 65001 >nul`r`n`"$python`" -X utf8 `"$entry`" %*`r`n"
[IO.File]::WriteAllText("$($config.target.root)/Studio-CLI.cmd",$cmd,[Text.UTF8Encoding]::new($false))
$pwsh=Join-Path $PSHOME 'pwsh.exe'
$start="@echo off`r`nchcp 65001 >nul`r`n`"$pwsh`" -NoProfile -File `"$PSScriptRoot\Start-ChatApp.ps1`"`r`nif errorlevel 1 pause`r`n"
[IO.File]::WriteAllText("$($config.target.root)/Start-AgentBackend.cmd",$start,[Text.UTF8Encoding]::new($false))
Write-Output 'Project-scoped MCP configs and CLI entrypoints created. Global account settings were not changed.'
