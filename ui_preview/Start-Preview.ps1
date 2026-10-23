[CmdletBinding()]
param([switch]$Desktop,[switch]$PrepareOnly)
$ErrorActionPreference='Stop'
# Desktop launches can inherit PowerShell 7's module paths from the parent app.
# Select this host's built-in modules only for this startup, never user/machine settings.
$previousModulePath=$env:PSModulePath
$env:PSModulePath=Join-Path $PSHOME 'Modules'
$startupLock=New-Object Threading.Mutex($false,'Local\ResearchAgentOrchestrator.ApprovedUI.Start')
$acquired=$false
try {
try {$acquired=$startupLock.WaitOne(20000)} catch [Threading.AbandonedMutexException] {$acquired=$true}
if(-not $acquired){throw 'Another Scene Control startup is still in progress'}
$repo='E:\Github\Research-Agent-Orchestrator'
$state=Join-Path $repo '.runtime\desktop-ui'
$python=Join-Path $repo '.venv\Scripts\pythonw.exe'
$appScript=Join-Path $PSScriptRoot 'app.py'
$appWorkdir=$repo
$workerActivation='E:\Github\Building-Generation-Validation\.runtime\worker\activation.json'
if(Test-Path -LiteralPath $workerActivation){
    $worker=Get-Content -LiteralPath $workerActivation -Raw|ConvertFrom-Json
    if($worker.owner -cne 'BGV.Windows.CodexWorker.v1' -or $worker.sha256 -cnotmatch '^[0-9a-f]{64}$'){throw 'Unknown worker activation'}
    $expected='E:\Github\Building-Generation-Validation\.runtime\desktop\snapshots\'+$worker.sha256+'\source'
    if($worker.source -cne $expected){throw 'Worker snapshot path mismatch'}
    & 'C:\Python312\python.exe' -B (Join-Path $expected 'worker.py') status --expected-hash $worker.sha256|Out-Null
    if($LASTEXITCODE -ne 0){throw 'Accepted UI snapshot verification failed'}
    $appScript=Join-Path $expected 'ui_preview\app.py';$appWorkdir=$expected
}
# One application for both historical invocations. -Desktop is retained only
# for compatibility with existing shortcuts; omitting it cannot open a second UI.
$native=Join-Path $state 'app'
$binary=Join-Path $native 'BGVSceneControl.exe'
$icon=Join-Path $native 'SceneControl.ico'
if(-not(Test-Path -LiteralPath $python)){throw 'Project preview environment missing. See ui_preview/README.md.'}
New-Item -ItemType Directory -Path $native -Force | Out-Null
$source=Join-Path $PSScriptRoot 'PreviewWindow.cs'
$hash=(Get-FileHash -LiteralPath $source).Hash
$receipt=Join-Path $state 'build-desktop.json'
$built=$null
if(Test-Path -LiteralPath $receipt){$built=Get-Content -LiteralPath $receipt -Raw|ConvertFrom-Json}
if(-not(Test-Path -LiteralPath $binary) -or $null -eq $built -or $built.source -cne $hash -or $built.binary -cne (Get-FileHash -LiteralPath $binary).Hash){
    # Reuse the existing pinned WebView2 runtime; do not replace the installed app.
    $dependencyRoot='E:\Github\Building-Generation-Validation\.runtime\desktop'
    $activation=Get-Content -LiteralPath (Join-Path $dependencyRoot 'activation.json') -Raw|ConvertFrom-Json
    if($activation.owner -cne 'BGV.Windows.SceneControl.Desktop.v1' -or $activation.sha256 -notmatch '^[0-9a-f]{64}$'){throw 'Desktop dependency identity unavailable'}
    $dependencies=Join-Path $dependencyRoot ('snapshots\'+$activation.sha256+'\app')
    $acceptedManifest=Get-Content -LiteralPath (Join-Path (Split-Path -Parent $dependencies) 'manifest.json') -Raw|ConvertFrom-Json
    $iconSource=Join-Path $dependencies 'SceneControl.ico'
    if((Get-FileHash -LiteralPath $iconSource).Hash.ToLowerInvariant() -cne $acceptedManifest.files.'app/SceneControl.ico'){throw 'Accepted BGV icon identity changed'}
    Copy-Item -LiteralPath $iconSource -Destination $icon -Force
    $pins=Get-Content -LiteralPath (Join-Path $repo 'config\desktop-dependencies.json') -Raw|ConvertFrom-Json
    foreach($file in @('Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll','WebView2Loader.dll')){
        if((Get-FileHash -LiteralPath (Join-Path $dependencies $file)).Hash.ToLowerInvariant() -cne $pins.files.$file){throw 'Pinned WebView2 dependency changed'}
        Copy-Item -LiteralPath (Join-Path $dependencies $file) -Destination (Join-Path $native $file) -Force
    }
    $compiler='C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    & $compiler /nologo /target:winexe /platform:x64 /langversion:5 /optimize+ "/out:$binary" "/win32icon:$icon" "/win32manifest:$(Join-Path $repo 'native\SceneControl.manifest')" /reference:System.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll "/reference:$(Join-Path $native 'Microsoft.Web.WebView2.Core.dll')" "/reference:$(Join-Path $native 'Microsoft.Web.WebView2.WinForms.dll')" $source
    if($LASTEXITCODE -ne 0){throw 'Preview shell build failed'}
    @{source=$hash;binary=(Get-FileHash -LiteralPath $binary).Hash;owner='ResearchAgentOrchestrator.UI.Preview'}|ConvertTo-Json|Set-Content -LiteralPath $receipt -Encoding utf8
}
if($PrepareOnly){Write-Output ('Prepared Scene Control UI: '+$binary);return}
function Preview-Health {
    try { return Invoke-RestMethod 'http://127.0.0.1:8878/preview-health' -TimeoutSec 2 -UseBasicParsing } catch { return $null }
}
$health=Preview-Health
if($health -and ($health.owner -cne 'BGV.SceneControl.UI.v1' -or $health.ui_only -notin @($true,$false))){throw 'Port 8878 belongs to another application'}
if(-not $health){
    $listener=Get-NetTCPConnection -LocalPort 8878 -State Listen -ErrorAction SilentlyContinue
    if($listener){throw 'Preview port is already occupied; nothing stopped'}
    $process=Start-Process -FilePath $python -ArgumentList @('-B',('"'+$appScript+'"')) -WorkingDirectory $appWorkdir -WindowStyle Hidden -PassThru
    @{owner='ResearchAgentOrchestrator.UI.Preview';pid=$process.Id;started_utc=(Get-Date).ToUniversalTime().ToString('o')}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $state 'server.json') -Encoding utf8
    for($i=0;$i -lt 30;$i++){$health=Preview-Health;if($health){break};Start-Sleep -Milliseconds 150}
}
if(-not $health -or $health.owner -cne 'BGV.SceneControl.UI.v1' -or $health.ui_only -notin @($true,$false)){throw 'UI service did not become ready'}
Start-Process -FilePath $binary -ArgumentList '--desktop' -WorkingDirectory $native
Write-Output ('Scene Control opened. '+$binary)
} finally {if($acquired){$startupLock.ReleaseMutex()};$startupLock.Dispose();$env:PSModulePath=$previousModulePath}
