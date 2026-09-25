#requires -Version 7.2
param([string]$ConfigPath = (Join-Path $PSScriptRoot '../config/support-config.json'))
$ErrorActionPreference = 'Stop'
$cfg = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$root = $cfg.target.root
$mutex = [Threading.Mutex]::new($false, ('Local\LocalStudioLLM-' + $cfg.inference.port))
$lockAcquired=$false
try{$lockAcquired=$mutex.WaitOne(10000)}catch [Threading.AbandonedMutexException]{$lockAcquired=$true}
if (-not $lockAcquired) { $mutex.Dispose(); throw 'This LocalLLM instance is already starting or running.' }
$outStream = $null; $errStream = $null; $child = $null
try {
    foreach ($path in @($cfg.target.executable,$cfg.inference.modelPath,$cfg.inference.mmprojPath)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing required file: $path" }
    }
    $env:LLAMA_CACHE = Join-Path $root 'cache'
    $env:HF_HOME = Join-Path $root 'cache/huggingface'
    $env:HF_HUB_OFFLINE = '1'
    $native = [Diagnostics.ProcessStartInfo]::new()
    $native.FileName = $cfg.target.executable
    $native.WorkingDirectory = Split-Path $cfg.target.executable
    $native.UseShellExecute = $false
    $native.CreateNoWindow = $true
    $native.RedirectStandardOutput = $true
    $native.RedirectStandardError = $true
    $cliArgs = @(
        '--model', $cfg.inference.modelPath, '--mmproj', $cfg.inference.mmprojPath,
        '--host', $cfg.inference.host, '--port', [string]$cfg.inference.port,
        '--alias', $cfg.inference.alias, '--ctx-size', [string]$cfg.inference.contextSize,
        '--parallel', [string]$cfg.inference.parallel, '--gpu-layers', [string]$cfg.inference.gpuLayers,
        '--flash-attn', $cfg.inference.flashAttention, '--batch-size', '512', '--ubatch-size', '128',
        '--jinja', '--chat-template-kwargs', '{"enable_thinking":false}',
        '--temp','0.7','--top-p','0.8','--top-k','20','--min-p','0',
        '--presence-penalty','1.5','--repeat-penalty','1.0'
    )
    foreach ($argValue in $cliArgs) { $native.ArgumentList.Add($argValue) }
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $outPath = Join-Path $root "logs/server-$stamp.stdout.log"
    $errPath = Join-Path $root "logs/server-$stamp.stderr.log"
    $outStream = [IO.FileStream]::new($outPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite,1,[IO.FileOptions]::Asynchronous)
    $errStream = [IO.FileStream]::new($errPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::ReadWrite,1,[IO.FileOptions]::Asynchronous)
    $child = [Diagnostics.Process]::Start($native)
    [ordered]@{pid=$child.Id;startUtcTicks=$child.StartTime.ToUniversalTime().Ticks;executable=$native.FileName;url=$cfg.target.defaultUrl;stdout=$outPath;stderr=$errPath;startedAt=(Get-Date -Format o)} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'runtime/server.json') -Encoding utf8
    $outCopy = $child.StandardOutput.BaseStream.CopyToAsync($outStream)
    $errCopy = $child.StandardError.BaseStream.CopyToAsync($errStream)
    $child.WaitForExit()
    [Threading.Tasks.Task]::WaitAll(@($outCopy,$errCopy))
    $requestedStop=$false
    $stopPath=Join-Path $root 'runtime/stop-request.json'
    if(Test-Path -LiteralPath $stopPath){
        $stopInfo=Get-Content -LiteralPath $stopPath -Raw | ConvertFrom-Json
        $requestedStop=($stopInfo.pid -eq $child.Id -and $stopInfo.startUtcTicks -eq $child.StartTime.ToUniversalTime().Ticks)
    }
    [ordered]@{pid=$child.Id;exitCode=$child.ExitCode;requestedStop=$requestedStop;finishedAt=(Get-Date -Format o)} |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $root 'runtime/last-exit.json') -Encoding utf8
    if ($child.ExitCode -ne 0 -and -not $requestedStop) { throw "llama-server exited with $($child.ExitCode). See $errPath" }
} finally {
    if ($outStream) { $outStream.Dispose() }
    if ($errStream) { $errStream.Dispose() }
    $mutex.ReleaseMutex()
    $mutex.Dispose()
}
