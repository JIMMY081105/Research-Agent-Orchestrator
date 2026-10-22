[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$state=Join-Path $repo '.runtime\ui-preview'
$python=Join-Path $repo '.venv\Scripts\pythonw.exe'
$appScript=Join-Path $PSScriptRoot 'app.py'
$native=Join-Path $state 'native'
$binary=Join-Path $native 'SceneControlPreview.exe'
if(-not(Test-Path -LiteralPath $python)){throw 'Project preview environment missing. See ui_preview/README.md.'}
New-Item -ItemType Directory -Path $native -Force | Out-Null
$source=Join-Path $PSScriptRoot 'PreviewWindow.cs'
$hash=(Get-FileHash -LiteralPath $source).Hash
$receipt=Join-Path $state 'build.json'
$built=$null
if(Test-Path -LiteralPath $receipt){$built=Get-Content -LiteralPath $receipt -Raw|ConvertFrom-Json}
if(-not(Test-Path -LiteralPath $binary) -or $null -eq $built -or $built.source -cne $hash){
    # Reuse the existing pinned WebView2 runtime; do not replace the installed app.
    $desktop='E:\Github\Building-Generation-Validation\.runtime\desktop'
    $activation=Get-Content -LiteralPath (Join-Path $desktop 'activation.json') -Raw|ConvertFrom-Json
    if($activation.owner -cne 'BGV.Windows.SceneControl.Desktop.v1' -or $activation.sha256 -notmatch '^[0-9a-f]{64}$'){throw 'Desktop dependency identity unavailable'}
    $dependencies=Join-Path $desktop ('snapshots\'+$activation.sha256+'\app')
    foreach($file in @('Microsoft.Web.WebView2.Core.dll','Microsoft.Web.WebView2.WinForms.dll','WebView2Loader.dll')){
        Copy-Item -LiteralPath (Join-Path $dependencies $file) -Destination (Join-Path $native $file) -Force
    }
    $compiler='C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe'
    & $compiler /nologo /target:winexe /platform:x64 /langversion:5 /optimize+ "/out:$binary" "/win32manifest:$(Join-Path $repo 'native\SceneControl.manifest')" /reference:System.dll /reference:System.Drawing.dll /reference:System.Windows.Forms.dll "/reference:$(Join-Path $native 'Microsoft.Web.WebView2.Core.dll')" "/reference:$(Join-Path $native 'Microsoft.Web.WebView2.WinForms.dll')" $source
    if($LASTEXITCODE -ne 0){throw 'Preview shell build failed'}
    @{source=$hash;binary=(Get-FileHash -LiteralPath $binary).Hash;owner='ResearchAgentOrchestrator.UI.Preview'}|ConvertTo-Json|Set-Content -LiteralPath $receipt -Encoding utf8
}
function Preview-Health {
    try { return Invoke-RestMethod 'http://127.0.0.1:8877/preview-health' -TimeoutSec 2 -UseBasicParsing } catch { return $null }
}
$health=Preview-Health
if($health -and ($health.owner -cne 'ResearchAgentOrchestrator.UI.Preview' -or $health.ui_only -ne $true)){throw 'Port 8877 belongs to another application'}
if(-not $health){
    $listener=Get-NetTCPConnection -LocalPort 8877 -State Listen -ErrorAction SilentlyContinue
    if($listener){throw 'Preview port is already occupied; nothing stopped'}
    $process=Start-Process -FilePath $python -ArgumentList @('-B',('"'+$appScript+'"')) -WorkingDirectory $repo -WindowStyle Hidden -PassThru
    @{owner='ResearchAgentOrchestrator.UI.Preview';pid=$process.Id;started_utc=(Get-Date).ToUniversalTime().ToString('o')}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $state 'server.json') -Encoding utf8
    for($i=0;$i -lt 30;$i++){$health=Preview-Health;if($health){break};Start-Sleep -Milliseconds 150}
}
if(-not $health -or $health.owner -cne 'ResearchAgentOrchestrator.UI.Preview' -or $health.ui_only -ne $true){throw 'Preview service did not become ready'}
Start-Process -FilePath $binary -WorkingDirectory $native
Write-Output ('UI-only native preview opened. '+$binary)
