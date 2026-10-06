#requires -Version 7.2
param(
    [ValidateSet('Dependencies', 'Model')]
    [string]$Phase = 'Model',
    [ValidateRange(8192, 262144)]
    [int]$ContextSize = 131072,
    [string]$ConfigPath = (Join-Path $PSScriptRoot '../config/support-config.json')
)

# This prepares the pinned engine and model only. It never starts/stops the server,
# changes the active supporter profile, installs global Python, drivers or build tools.
$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$root = [IO.Path]::GetFullPath($config.target.root).TrimEnd('\')
if (-not $root.Equals('C:\AI\LocalLLM', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Strata preparation target must be C:\AI\LocalLLM.'
}
$sourceRoot = Join-Path $root 'apps/Strata/source'
$engineRoot = Join-Path $sourceRoot 'engine'
$downloadRoot = Join-Path $root 'downloads/strata'
$zipPath = Join-Path $downloadRoot 'strata-windows-x64.zip'
$dataRoot = Join-Path $root 'models/Qwen3.8-Flash-Next'
$ggufRoot = Join-Path $dataRoot 'IQ3_S'
$python = Join-Path $sourceRoot '.venv/Scripts/python.exe'
$pipCache = Join-Path $root 'cache/strata-pip'
$preparedConfig = Join-Path $sourceRoot 'strata-iq3_s.json'
$sourceCommit = '6f32ec070f23ced9f50e704d854d775da52591ab'
$zipHash = 'a862bcfa2330cd1c23f9b5d6e49f4027da8f8313842bd62e858ec6cd4533813a'
$canonicalName = 'qwen3.8-flash-next-iq3_s'
$legacyAlias = 'qwen3.8-27b-local'

function Assert-ScopedPath([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    if (-not ($full.Equals($root, [StringComparison]::OrdinalIgnoreCase) -or
              $full.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase))) {
        throw "Path escaped LocalLLM: $full"
    }
    $cursor = $full
    while ($cursor.Length -ge $root.Length) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Strata preparation refuses a linked path: $cursor"
            }
        }
        if ($cursor.Equals($root, [StringComparison]::OrdinalIgnoreCase)) { break }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    return $full
}

function Invoke-Python([string[]]$Arguments) {
    & $python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Strata Python command failed (exit $LASTEXITCODE)." }
}

function Assert-SourcePin {
    foreach ($name in @('.git', 'setup.py', 'requirements.txt', 'CMakeLists.txt')) {
        if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot $name))) {
            throw "Pinned Strata checkout is missing $name. Obtain the source before running preparation."
        }
    }
    $head = & git -c "safe.directory=$sourceRoot" -C $sourceRoot rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or ($head -join '').Trim() -ne $sourceCommit) {
        throw "Strata checkout must be pinned to $sourceCommit."
    }
    & git -c "safe.directory=$sourceRoot" -C $sourceRoot diff --quiet HEAD --
    if ($LASTEXITCODE -ne 0) { throw 'Pinned Strata source has tracked changes; preparation will not use it.' }
}

function Assert-EngineMetadata($Metadata) {
    if ($Metadata.version -ne '0.1.39' -or $Metadata.source -ne 'release' -or
        $Metadata.cuda -ne '13.0' -or $Metadata.vision -ne 'gpu' -or
        89 -notin @($Metadata.archs) -or 89 -notin @($Metadata.vision_archs)) {
        throw 'The verified release must contain Strata 0.1.39 CUDA 13.0 and RTX 4090 code for text and vision.'
    }
}

function Install-VerifiedEngine {
    if (-not (Test-Path -LiteralPath $zipPath -PathType Leaf)) {
        throw 'Download and SHA256-verify strata-windows-x64.zip before preparing dependencies.'
    }
    if ((Get-Item -LiteralPath $zipPath).Length -ne 123629160 -or
        (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $zipHash) {
        throw 'Strata 0.1.39 Windows archive size or SHA256 mismatch.'
    }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        $expected = @('strata.exe', 'strata-vision.exe', 'BUILD.json')
        $seen = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        foreach ($entry in $archive.Entries) {
            $name = $entry.FullName.Replace('/', '\')
            if ([IO.Path]::IsPathRooted($name) -or $name.Contains(':') -or
                @($name.Split('\') | Where-Object { $_ -eq '..' }).Count -gt 0 -or
                (($entry.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000 -or
                $name -notin $expected -or -not $seen.Add($name)) {
                throw "Unsafe or unexpected entry in Strata archive: $($entry.FullName)"
            }
            $null = Assert-ScopedPath (Join-Path $engineRoot $name)
        }
        if ($seen.Count -ne $expected.Count) { throw 'Strata archive is missing required engine files.' }
        $reader = [IO.StreamReader]::new($archive.GetEntry('BUILD.json').Open())
        try { $metadata = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
        Assert-EngineMetadata $metadata

        # Validate every existing file before writing anything. Never replace a
        # different build or a partial binary just because the directory is named engine.
        foreach ($entry in $archive.Entries) {
            $destination = Join-Path $engineRoot $entry.FullName
            if (-not (Test-Path -LiteralPath $destination)) { continue }
            if (-not (Test-Path -LiteralPath $destination -PathType Leaf) -or
                (Get-Item -LiteralPath $destination).Length -ne $entry.Length) {
                throw "Existing engine file is incompatible; retained unchanged: $destination"
            }
            $stream = $entry.Open()
            $sha = [Security.Cryptography.SHA256]::Create()
            try { $entryHash = [Convert]::ToHexString($sha.ComputeHash($stream)) }
            finally { $sha.Dispose(); $stream.Dispose() }
            if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $entryHash) {
                throw "Existing engine file differs from the pinned archive; retained unchanged: $destination"
            }
        }
        New-Item -ItemType Directory -Path $engineRoot -Force | Out-Null
        foreach ($entry in $archive.Entries) {
            $destination = Join-Path $engineRoot $entry.FullName
            if (-not (Test-Path -LiteralPath $destination)) {
                [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $destination, $false)
            }
        }
    } finally { $archive.Dispose() }
}

function Assert-ModelFile([string]$Name, [long]$Size, [string]$Hash, [string]$Folder) {
    $path = Assert-ScopedPath (Join-Path $Folder $Name)
    if (-not (Test-Path -LiteralPath $path -PathType Leaf) -or
        (Get-Item -LiteralPath $path).Length -ne $Size) {
        throw "Pinned model file is missing or incomplete: $Name"
    }
    Write-Host "Checking SHA256: $Name"
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Hash) {
        throw "Pinned model SHA256 mismatch: $Name"
    }
}

foreach ($path in @($sourceRoot, $engineRoot, $downloadRoot, $dataRoot, $ggufRoot, $python, $pipCache, $preparedConfig,
        (Join-Path $sourceRoot 'third_party/_unpack'), (Join-Path $sourceRoot 'third_party/llama.cpp'))) {
    $null = Assert-ScopedPath $path
}
Assert-SourcePin

$previousEnv = @{}
foreach ($name in @('PIP_CACHE_DIR', 'PIP_DISABLE_PIP_VERSION_CHECK', 'PYTHONUTF8', 'PYTHONNOUSERSITE', 'PYTHONPATH', 'HF_ENDPOINT', 'STRATA_MTP_REVISION')) {
    $previousEnv[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    $env:PIP_CACHE_DIR = $pipCache
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    $env:PYTHONUTF8 = '1'
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONPATH = $null
    $env:HF_ENDPOINT = 'https://huggingface.co'
    $env:STRATA_MTP_REVISION = 'de4b8e4d43b917e7706784d8bb445c9af86a3540'

    if ($Phase -eq 'Dependencies') {
        Install-VerifiedEngine
        if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
            $venvRoot = Join-Path $sourceRoot '.venv'
            if (Test-Path -LiteralPath $venvRoot) { throw 'Existing incomplete .venv is retained; inspect it before retrying.' }
            $candidates = @($config.supporter.pythonExecutable, 'C:\Program Files\Python311\python.exe') |
                Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -Unique
            $basePython = $null
            foreach ($candidate in $candidates) {
                & $candidate -I -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) and sys.maxsize > 2**32 else 1)'
                if ($LASTEXITCODE -eq 0) { $basePython = $candidate; break }
            }
            if (-not $basePython) { throw 'No existing supported 64-bit Python was found. Global Python will not be installed.' }
            & $basePython -I -m venv $venvRoot
            if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $python)) { throw 'Strata venv creation failed.' }
        }
        $identityCheck = @'
import pathlib, sys
expected = pathlib.Path(sys.argv[1]).resolve()
if pathlib.Path(sys.prefix).resolve() != expected or sys.prefix == sys.base_prefix:
    raise SystemExit("Refusing dependency installation outside the dedicated Strata venv")
if sys.version_info < (3, 10) or sys.maxsize <= 2**32:
    raise SystemExit("Strata requires 64-bit Python 3.10 or newer")
'@
        Invoke-Python @('-I', '-c', $identityCheck, (Join-Path $sourceRoot '.venv'))
        New-Item -ItemType Directory -Path $pipCache -Force | Out-Null
        Invoke-Python @('-X', 'utf8', '-m', 'pip', '--isolated', 'install', '--cache-dir', $pipCache,
            '--disable-pip-version-check', '-r', (Join-Path $sourceRoot 'requirements.txt'),
            'nvidia-cublas==13.0.2.14', 'nvidia-cuda-runtime==13.0.96', 'jsonschema>=4.23,<5')
        Invoke-Python @('-X', 'utf8', '-m', 'pip', '--isolated', 'check')
        # Record the exact installed requirements in setup's own stamp, so its next
        # pass reuses these packages instead of running a second pip installation.
        $requirements = @(Get-Content -LiteralPath (Join-Path $sourceRoot 'requirements.txt') |
            ForEach-Object { ($_ -split '#', 2)[0].Trim() } | Where-Object { $_ })
        $requirements += @('nvidia-cublas==13.0.2.14', 'nvidia-cuda-runtime==13.0.96')
        $pipStamp = Assert-ScopedPath (Join-Path $sourceRoot '.venv/.strata-pip.json')
        $requirements | ConvertTo-Json | Set-Content -LiteralPath $pipStamp -Encoding utf8
        Write-Host 'Pinned Strata engine and isolated Python dependencies prepared. The model/server has not been started.'
        return
    }

    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Run -Phase Dependencies first.' }
    Install-VerifiedEngine
    Assert-ModelFile 'Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf' 54817524224 `
        '4c1eb2ceb4915e1192f4f386021897bde56a97f40a0bb78bb86465e0f7d2aca3' $ggufRoot
    Assert-ModelFile 'Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00002-of-00002.gguf' 28800138432 `
        '316b46f3a2dbd68c900f43136ab9449f9dcc3725dfd8c794847c204bc161e113' $ggufRoot
    Assert-ModelFile 'mmproj-Qwen3.8-Flash-Next-BF16.gguf' 907543008 `
        'b1a82259702816a5330d7bd7607cd9676b11780e79ff7348c21103ff3ce49bd0' $dataRoot
    Invoke-Python @('-B', '-X', 'utf8', (Join-Path $PSScriptRoot 'Fetch-StrataMTP.py'))

    if (Test-Path -LiteralPath $preparedConfig) {
        $backupRoot = Assert-ScopedPath (Join-Path $root 'runtime/strata-preparation/backups')
        New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
        Copy-Item -LiteralPath $preparedConfig -Destination (Join-Path $backupRoot ((Get-Date -Format 'yyyyMMdd-HHmmss-fffffff') + '.json'))
    }
    $port = [int]$config.inference.port
    if ($config.inference.host -ne '127.0.0.1' -or $port -lt 1 -or $port -gt 65535) {
        throw 'Local Studio Strata preparation requires a valid loopback-only inference address.'
    }

    # Run the pinned setup in a separate process without modifying upstream files.
    # Prevent its automatic global compiler installation and shared-install model
    # migration paths, even if a prebuilt engine becomes unavailable unexpectedly.
    $modelRunner = @'
import importlib.util, json, pathlib, sys
source = pathlib.Path(sys.argv[1]).resolve()
expected_data = pathlib.Path(sys.argv[2]).resolve()
mtp_helper = pathlib.Path(sys.argv[3]).resolve(strict=True)
sys.path.insert(0, str(source))
spec = importlib.util.spec_from_file_location("strata_setup_pinned", source / "setup.py")
setup = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = setup
spec.loader.exec_module(setup)
def blocked_build(*args, **kwargs):
    raise SystemExit("Prebuilt Strata is required; global build tools, drivers and source compilation are disabled")
for name in ("install_build_tools", "build_engine", "build_engine_hip", "build_vision_cpu"):
    setattr(setup, name, blocked_build)
def scoped_data(requested):
    if not requested or pathlib.Path(requested).resolve() != expected_data:
        raise SystemExit("Strata setup attempted to use a different data directory")
    expected_data.mkdir(parents=True, exist_ok=True)
    return expected_data, []
setup.data_folder = scoped_data
setup.load_settings = lambda: {}
setup.save_settings = lambda settings: None
setup.other_installs = lambda settings: []
original_run = setup.run
def scoped_run(command, *args, **kwargs):
    if (isinstance(command, list) and len(command) >= 2 and
            pathlib.Path(command[1]).resolve() == source / "tools/mtp_fetch.py"):
        if command[2:4] != ["fetch", "--out"] or len(command) != 5 or pathlib.Path(command[4]).resolve() != expected_data / "mtp":
            raise SystemExit("Unexpected MTP fetch arguments; the pinned helper is required")
        command = [sys.executable, "-B", "-X", "utf8", str(mtp_helper)]
    return original_run(command, *args, **kwargs)
setup.run = scoped_run
_, avx2, _ = setup.cpu_info()
if not avx2 or setup.cpu_floor(avx2):
    raise SystemExit("The pinned Windows engine requires the normal AVX2 CPU path; experimental CPU builds are disabled")
cards = [c for c in setup.gpus() if "RTX 4090" in c.get("name", "")]
if len(cards) != 1 or setup.gpu_problem(cards[0]) is not None or int(cards[0]["arch"]) != 89:
    raise SystemExit("Expected one supported RTX 4090 with NVIDIA driver 580 or newer")
meta = json.loads((source / "engine" / "BUILD.json").read_text(encoding="utf-8"))
if setup.prebuilt_vision(meta, cards[0], "gpu") != "gpu":
    raise SystemExit("The verified engine cannot supply GPU vision for the selected card")
sys.argv = [str(source / "setup.py"), *sys.argv[4:], "--gpu", str(cards[0]["index"])]
raise SystemExit(setup.main() or 0)
'@
    $setupArguments = @('-X', 'utf8', '-c', $modelRunner, $sourceRoot, $dataRoot, (Join-Path $PSScriptRoot 'Fetch-StrataMTP.py'),
        '--yes', '--setup', '--family', 'qwen', '--model', 'IQ3_S', '--context', [string]$ContextSize,
        '--vision', 'gpu', '--low-ram', 'off', '--draft-vocab', 'cjk', '--no-start', '--no-browser',
        '--backend', 'cuda', '--cuda', '13', '--experimental-speed-projection', 'off', '--vram-reserve-mib', '1536',
        '--data-dir', $dataRoot, '--gguf-dir', $ggufRoot, '--models-dir', $dataRoot,
        '--prebuilt', $downloadRoot, '--host', '127.0.0.1', '--port', [string]$port)
    Invoke-Python $setupArguments
    if (-not (Test-Path -LiteralPath $preparedConfig -PathType Leaf)) { throw 'Setup did not produce strata-iq3_s.json.' }
    $runConfig = Get-Content -LiteralPath $preparedConfig -Raw | ConvertFrom-Json -AsHashtable
    if ($runConfig.exe -ne (Join-Path $engineRoot 'strata.exe') -or -not $runConfig.vision.gpu) {
        throw 'Generated Strata configuration does not use the verified text and GPU vision engine.'
    }
    $runConfig.model_name = $canonicalName
    $runConfig.aliases = @(@($runConfig.aliases) + $legacyAlias | Where-Object { $_ -and $_ -ne $canonicalName } | Select-Object -Unique)
    $temporaryConfig = Assert-ScopedPath ($preparedConfig + '.prepare.tmp')
    if (Test-Path -LiteralPath $temporaryConfig) { throw 'An earlier temporary Strata config is retained; inspect it before retrying.' }
    $runConfig | ConvertTo-Json -Depth 50 | Set-Content -LiteralPath $temporaryConfig -Encoding utf8
    Move-Item -LiteralPath $temporaryConfig -Destination $preparedConfig -Force
    # Retain the previous Local Studio default (thinking off). Existing Strata
    # shared settings are user choices and are never replaced by preparation.
    $sharedPath = Assert-ScopedPath (Join-Path $sourceRoot 'strata-iq3_s.shared-settings.json')
    if (-not (Test-Path -LiteralPath $sharedPath)) {
        '{"reasoning_effort":"none"}' | Set-Content -LiteralPath $sharedPath -Encoding utf8
    }
    Write-Host "Strata IQ3_S prepared at $ContextSize tokens with GPU vision and legacy alias $legacyAlias. Start and smoke verification remain separate steps."
} finally {
    foreach ($entry in $previousEnv.GetEnumerator()) {
        [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, 'Process')
    }
}
