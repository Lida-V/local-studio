param([string]$ConfigPath = (Join-Path $PSScriptRoot '../config/support-config.json'))
$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$root = [IO.Path]::GetFullPath($config.target.root)
if ($root -ne 'C:\AI\LocalLLM') { throw 'Installation target must be C:\AI\LocalLLM.' }
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot '../config/download-manifest.json') -Raw | ConvertFrom-Json
foreach ($sub in @('downloads','models/Qwen3.8-27B','runtime','logs','data','cache','tests','bin')) {
    New-Item -ItemType Directory -Path (Join-Path $root $sub) -Force | Out-Null
}
$stateFile = Join-Path $root 'runtime/install-state.json'
$verified = @()
function Write-State([string]$state, [string]$current, [string]$errorText = '') {
    [ordered]@{state=$state;current=$current;updatedAt=(Get-Date -Format o);verified=$verified;error=$errorText} |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $stateFile -Encoding utf8
}
try {
    foreach ($entry in $manifest.files) {
        $dest = [IO.Path]::GetFullPath((Join-Path (Join-Path $root $entry.folder) $entry.name))
        if (-not $dest.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Path escaped installation root.' }
        Write-State 'downloading' $entry.name
        if (Test-Path -LiteralPath $dest) {
            if ((Get-Item -LiteralPath $dest).Length -ne $entry.size) { throw "Existing completed file has wrong size: $($entry.name)" }
        } else {
            $partial = "$dest.part"
            & $config.supporter.pythonExecutable -X utf8 (Join-Path $PSScriptRoot 'Download-File.py') (Join-Path $PSScriptRoot '../config/download-manifest.json') $entry.name $partial
            if ($LASTEXITCODE -ne 0) { throw "Download failed ($LASTEXITCODE): $($entry.name). Partial retained." }
            if ((Get-Item -LiteralPath $partial).Length -ne $entry.size) { throw "Size mismatch: $($entry.name)" }
            Write-State 'hashing' $entry.name
            if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) { throw "SHA256 mismatch: $($entry.name)" }
            Move-Item -LiteralPath $partial -Destination $dest
        }
        if ((Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.sha256) { throw "SHA256 mismatch: $($entry.name)" }
        $verified += $entry.name
        Write-State 'verified' $entry.name
    }
    $binDir = Join-Path $root ('bin/llama.cpp-' + $manifest.runtimeRelease)
    New-Item -ItemType Directory -Path $binDir -Force | Out-Null
    foreach ($entry in ($manifest.files | Where-Object folder -eq 'downloads')) {
        Write-State 'extracting' $entry.name
        Expand-Archive -LiteralPath (Join-Path (Join-Path $root $entry.folder) $entry.name) -DestinationPath $binDir -Force
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot '../config/download-manifest.json') -Destination (Join-Path $root 'runtime/installed-manifest.json')
    Write-State 'complete' ''
} catch {
    Write-State 'failed' '' $_.Exception.Message
    throw
}
