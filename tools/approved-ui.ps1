[CmdletBinding()]
param([ValidateSet('Install','Open','Status','Restore')][string]$Mode='Status')
# Change only this application's shortcuts. The accepted orchestration service stays intact.
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1') -ErrorAction Stop
$repo=[IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$script=Join-Path $repo 'ui_preview\Start-Preview.ps1'
$powershell='C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
$state=Join-Path $repo '.runtime\ui-preview\installation'
$receipt=Join-Path $state 'installation.json'
$owner='ResearchAgentOrchestrator.ApprovedUI.Shortcuts.v1'
$arguments='-NoProfile -NonInteractive -WindowStyle Hidden -File "'+$script+'" -Desktop'
$links=@((Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'BGV Scene Control.lnk'),(Join-Path ([Environment]::GetFolderPath('Programs')) 'BGV Scene Control.lnk'))
$pinned=Join-Path ([Environment]::GetFolderPath('ApplicationData')) 'Microsoft\Internet Explorer\Quick Launch\User Pinned\TaskBar\SceneControl.lnk'
if(Test-Path -LiteralPath $pinned){$links+= $pinned}
$shell=New-Object -ComObject WScript.Shell
$prior=$null
if(Test-Path -LiteralPath $receipt){
    $prior=Get-Content -LiteralPath $receipt -Raw|ConvertFrom-Json
    if($prior.owner -cne $owner -or $prior.repo -cne $repo){throw 'UI shortcut receipt ownership mismatch'}
}
function Read-Link($path){
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw 'Expected Scene Control shortcut missing'}
    if((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Shortcut reparse point refused'}
    return $shell.CreateShortcut($path)
}
function Assert-NewLink($path){
    $link=Read-Link $path
    if($link.TargetPath -ine $powershell -or $link.Arguments -cne $arguments -or $link.WorkingDirectory -ine $repo){throw 'Shortcut belongs to another application or was changed'}
}
if($Mode -eq 'Open'){
    & $script -Desktop
    exit
}
if($Mode -eq 'Install'){
    $pending=@($links)
    $retained=@()
    if($prior -and $prior.status -eq 'INSTALLED'){
        foreach($record in $prior.shortcuts){
            if($record.path -notin $links){throw 'Installed shortcut path is outside the known entries'}
            Assert-NewLink $record.path
        }
        $retained=@($prior.shortcuts)
        $pending=@($links|Where-Object {$_ -notin @($prior.shortcuts.path)})
        if($pending.Count -eq 0){Write-Output 'Approved UI is already installed at all existing entries.';exit}
    }
    $legacy='E:\Github\Building-Generation-Validation\.runtime\desktop'
    $activation=Get-Content -LiteralPath (Join-Path $legacy 'activation.json') -Raw|ConvertFrom-Json
    $launcher=Join-Path $legacy 'SceneControlLauncher.exe'
    $launcherReceipt=Get-Content -LiteralPath (Join-Path $legacy 'launcher.json') -Raw|ConvertFrom-Json
    if($activation.owner -cne 'BGV.Windows.SceneControl.Desktop.v1' -or $launcherReceipt.owner -cne $activation.owner -or $launcherReceipt.sha256 -cne (Get-FileHash -LiteralPath $launcher).Hash.ToLowerInvariant()){throw 'Original Scene Control identity unavailable'}
    foreach($path in $pending){
        $link=Read-Link $path
        if($link.TargetPath -ine $launcher -or $link.Arguments -or $link.WorkingDirectory -ine $legacy){throw 'Existing shortcut is not the owned original Scene Control entry'}
    }
    # Prepare and verify the separate UI binary before changing either user entry.
    & $script -Desktop -PrepareOnly
    $stamp=[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')+'-'+[Guid]::NewGuid().ToString('N')
    $backup=Join-Path $state $stamp
    New-Item -ItemType Directory -Path $backup -Force|Out-Null
    $records=@($retained)
    $newBackups=@()
    for($i=0;$i -lt $pending.Count;$i++){
        $copy=Join-Path $backup ($i.ToString()+'.lnk')
        Copy-Item -LiteralPath $pending[$i] -Destination $copy
        $newBackups+=@{path=$pending[$i];backup=$copy;sha256=(Get-FileHash -LiteralPath $copy).Hash}
    }
    $records+= $newBackups
    try {
        foreach($path in $pending){
            $link=Read-Link $path
            $link.TargetPath=$powershell;$link.Arguments=$arguments;$link.WorkingDirectory=$repo
            $link.WindowStyle=7;$link.Description='Scene Control — approved Flask / Jinja2 / HTMX interface'
            $link.Save();Assert-NewLink $path
        }
    } catch {
        foreach($record in $newBackups){Copy-Item -LiteralPath $record.backup -Destination $record.path -Force}
        throw
    }
    @{owner=$owner;repo=$repo;status='INSTALLED';installed_utc=[DateTime]::UtcNow.ToString('o');scope='UI_ONLY';previous_activation=$activation.sha256;shortcuts=$records;target=$powershell;arguments=$arguments}|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $receipt -Encoding utf8
}
if($Mode -eq 'Restore'){
    if(-not $prior -or $prior.status -ne 'INSTALLED'){throw 'No installed UI shortcut change to restore'}
    foreach($record in $prior.shortcuts){
        if($record.path -notin $links -or -not $record.backup.StartsWith($state+'\',[StringComparison]::OrdinalIgnoreCase)){throw 'Backup path ownership mismatch'}
        Assert-NewLink $record.path
        if((Get-FileHash -LiteralPath $record.backup).Hash -cne $record.sha256){throw 'Original shortcut backup changed'}
    }
    foreach($record in $prior.shortcuts){Copy-Item -LiteralPath $record.backup -Destination $record.path -Force}
    $prior.status='RESTORED'
    $prior|ConvertTo-Json -Depth 5|Set-Content -LiteralPath $receipt -Encoding utf8
}
$current=@()
foreach($path in $links){$link=Read-Link $path;$current+=@{path=$path;target=$link.TargetPath;arguments=$link.Arguments}}
@{owner=$owner;mode=$Mode;ui_only=$true;shortcuts=$current;receipt=$receipt;backend_tasks_changed=$false}|ConvertTo-Json -Depth 5
