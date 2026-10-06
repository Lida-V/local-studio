param([string]$ConfigPath=(Join-Path $PSScriptRoot '../config/support-config.json'),[switch]$NoSnapshot)
$ErrorActionPreference='Stop'
$cfg=Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$status=[ordered]@{checkedAt=(Get-Date -Format o);root=$cfg.target.root;backend=$(if($cfg.inference.backend){$cfg.inference.backend}else{'llama.cpp'});contextSize=$cfg.inference.contextSize;executablePresent=(Test-Path -LiteralPath $cfg.target.executable);url=$cfg.target.defaultUrl;api='stopped';modelIds=@();vision=$null;files=@();gpu=$null;process=$null}
$catalog=Get-Content -LiteralPath (Join-Path $PSScriptRoot '../config/model-profiles.json') -Raw | ConvertFrom-Json
$profile=@($catalog.profiles | Where-Object { [IO.Path]::GetFullPath((Join-Path $cfg.target.root $_.model.path)) -eq [IO.Path]::GetFullPath($cfg.inference.modelPath) })
if($profile.Count -ne 1){throw 'The active model does not match exactly one catalog profile.'}
foreach($entry in @($profile[0].model,$profile[0].mmproj)+@($profile[0].additionalArtifacts)){
    if(-not $entry){continue}
    $path=Join-Path $cfg.target.root $entry.path
    $file=Get-Item -LiteralPath $path -ErrorAction SilentlyContinue
    $status.files+=@{name=[IO.Path]::GetFileName($path);present=[bool]$file;expectedBytes=$entry.size;actualBytes=$(if($file){$file.Length}else{$null});sizeMatches=($file -and $file.Length -eq $entry.size)}
}
try{
    $health=Invoke-RestMethod ($cfg.target.defaultUrl+'/health') -TimeoutSec 3
    $models=Invoke-RestMethod ($cfg.target.defaultUrl+'/v1/models') -TimeoutSec 3
    $props=Invoke-RestMethod ($cfg.target.defaultUrl+'/props') -TimeoutSec 3
    $status.api=$health.status
    $status.modelIds=@($models.data.id)
    $status.vision=$props.modalities.vision
}catch{}
$stateFile=Join-Path $cfg.target.root 'runtime/server.json'
if(Test-Path -LiteralPath $stateFile){
    $state=Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
    $instance=Get-Process -Id $state.pid -ErrorAction SilentlyContinue
    if($instance){$status.process=@{pid=$instance.Id;identityMatches=($instance.Path -eq $cfg.target.executable -and $instance.StartTime.ToUniversalTime().Ticks -eq $state.startUtcTicks)}}
}
if(Get-Command nvidia-smi -ErrorAction SilentlyContinue){$status.gpu=(& nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free --format=csv,noheader)}
$json=$status | ConvertTo-Json -Depth 7
Write-Output $json
if(-not $NoSnapshot){
    $dir=Join-Path $PSScriptRoot '../notes/status'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $json | Set-Content -LiteralPath (Join-Path $dir ('status-'+(Get-Date -Format 'yyyyMMdd-HHmmss')+'.json')) -Encoding utf8
}
