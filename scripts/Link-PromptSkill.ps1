param([Parameter(Mandatory)][string]$SourcePath)
$ErrorActionPreference = 'Stop'
$source = (Resolve-Path -LiteralPath $SourcePath).Path
if (-not (Test-Path -LiteralPath (Join-Path $source 'SKILL.md') -PathType Leaf)) {
    throw 'SourcePath must contain the reviewed qwen-image21-prompting SKILL.md.'
}
$skillsRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../skills'))
$destination = Join-Path $skillsRoot 'qwen-image21-prompting'
if (Test-Path -LiteralPath $destination) {
    $item = Get-Item -LiteralPath $destination -Force
    if ($item.LinkType -ne 'Junction' -or [IO.Path]::GetFullPath(@($item.Target)[0]) -ne $source) {
        throw 'An existing skill occupies this path. It was preserved; review it before changing the installation.'
    }
} else {
    New-Item -ItemType Directory -Path $skillsRoot -Force | Out-Null
    New-Item -ItemType Junction -Path $destination -Target $source | Out-Null
}
Write-Output 'qwen-image21-prompting: canonical skill linked; existing Codex/Claude skill roots also resolve it.'
