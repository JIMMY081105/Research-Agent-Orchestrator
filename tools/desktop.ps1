[CmdletBinding()]
param(
 [ValidateSet('Install','Status','Open','Disable','Enable','Uninstall','EnsureService')][string]$Mode='Status',
 [string]$ExpectedHash=''
)
$ErrorActionPreference='Stop'
$runtime='E:\Github\Building-Generation-Validation\.runtime'
$directory=Join-Path $runtime 'desktop'
$owner='BGV.Windows.SceneControl.Desktop.v1'
$taskName='BGV-SceneControl-Service-v1'
$python='C:\Python312\python.exe'
$pythonw='C:\Python312\pythonw.exe'
$a=Get-Content -LiteralPath (Join-Path $directory 'activation.json') -Raw|ConvertFrom-Json
if($a.owner -cne $owner -or $a.sha256 -notmatch '^[0-9a-f]{64}$'){throw 'Invalid desktop activation'}
if($ExpectedHash -and $ExpectedHash -cne $a.sha256){throw 'Desktop version changed'}
$bundle=Join-Path $directory ('snapshots\'+$a.sha256)
$source=Join-Path $bundle 'source'
$app=Join-Path $bundle 'app\SceneControl.exe'
$launcher=Join-Path $directory 'SceneControlLauncher.exe'
$launcherSource=Join-Path $bundle 'app\SceneControlLauncher.exe'
$launcherReceipt=Join-Path $directory 'launcher.json'
if([IO.Path]::GetFullPath($a.source) -cne $source){throw 'Desktop source outside snapshot'}
foreach($path in @($runtime,$directory,$bundle,$source,$app,$python,$pythonw)){
 if(-not(Test-Path -LiteralPath $path)){throw 'Desktop required path unavailable'}
 $item=Get-Item -LiteralPath $path
 while($item){if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Desktop reparse path rejected'};$item=$item.Parent}
}
& $python -B (Join-Path $source 'desktop.py') verify --root $source --runtime $runtime --expected-hash $a.sha256 | Out-Null
if($LASTEXITCODE -ne 0){throw 'Desktop fixed snapshot verification failed'}
$arguments='-B "'+(Join-Path $source 'desktop.py')+'" serve --root "'+$source+'" --runtime "'+$runtime+'" --expected-hash '+$a.sha256+' --trigger scheduled-desktop'
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
function Assert-Owned($task){
 if($task.Description -cne $owner -or $task.Actions.Count -ne 1 -or $task.Actions[0].Execute -cne $pythonw -or
    $task.Actions[0].Arguments -cne $arguments -or $task.Actions[0].WorkingDirectory -cne $source){throw 'Task ownership or version mismatch'}
 $actualSid=$task.Principal.UserId
 if($actualSid -notlike 'S-1-*'){$actualSid=([Security.Principal.NTAccount]$actualSid).Translate([Security.Principal.SecurityIdentifier]).Value}
 if($actualSid -cne $sid -or $task.Principal.LogonType.ToString() -ne 'Interactive' -or $task.Principal.RunLevel.ToString() -ne 'Limited'){throw 'Wrong desktop service principal'}
}
function Utc-OrNull($value){if($null -eq $value){return $null};return $value.ToUniversalTime().ToString('o')}
$existing=Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction SilentlyContinue
if($existing){Assert-Owned $existing}
$links=@((Join-Path ([Environment]::GetFolderPath('DesktopDirectory')) 'BGV Scene Control.lnk'),(Join-Path ([Environment]::GetFolderPath('Programs')) 'BGV Scene Control.lnk'))
$shell=New-Object -ComObject WScript.Shell
function Assert-Launcher {
 if((Test-Path -LiteralPath $launcher) -or (Test-Path -LiteralPath $launcherReceipt)){
  foreach($path in @($launcher,$launcherReceipt)){
   if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw 'Incomplete existing launcher ownership'}
   $item=Get-Item -LiteralPath $path
   while($item){if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Launcher reparse path rejected'};$item=$item.Parent}
  }
  $prior=Get-Content -LiteralPath $launcherReceipt -Raw|ConvertFrom-Json
  if($prior.owner -cne $owner -or $prior.sha256 -cne (Get-FileHash -LiteralPath $launcher -Algorithm SHA256).Hash.ToLowerInvariant()){throw 'Existing launcher ownership mismatch'}
 }
}
Assert-Launcher
function Assert-Link($path){
 if(Test-Path -LiteralPath $path){
  $link=$shell.CreateShortcut($path)
  if(($link.TargetPath -cne $app -and $link.TargetPath -cne $launcher) -or $link.Arguments){throw 'Same-name shortcut belongs to another app/version'}
 }
}
if($Mode -eq 'Install'){
 if($existing){throw 'Desktop task already installed; no task overwritten'}
 foreach($path in $links){Assert-Link $path}
 if(-not(Test-Path -LiteralPath $launcherSource -PathType Leaf)){throw 'Accepted launcher missing'}
 $action=New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $source
 $when=(Get-Date).AddMinutes(1)
 $triggers=@((New-ScheduledTaskTrigger -Once -At $when),(New-ScheduledTaskTrigger -AtLogOn -User $sid))
 $settings=New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
 $settings.WakeToRun=$false
 $principal=New-ScheduledTaskPrincipal -UserId $sid -LogonType Interactive -RunLevel Limited
 $legacyRecord=$null
 $legacy=Get-ScheduledTask -TaskName 'BGV-ResearchOps-UI-v1' -TaskPath '\' -ErrorAction SilentlyContinue
 if($legacy){
  $legacyActivation=Get-Content -LiteralPath (Join-Path $runtime 'dashboard\activation.json') -Raw|ConvertFrom-Json
  if($legacyActivation.owner -cne 'BGV.Windows.ResearchOps.UI.v1' -or $legacyActivation.sha256 -notmatch '^[0-9a-f]{64}$'){throw 'Legacy UI ownership unavailable'}
  $legacySource=Join-Path $runtime ('dashboard\snapshots\'+$legacyActivation.sha256+'\source')
  if([IO.Path]::GetFullPath($legacyActivation.source) -cne $legacySource){throw 'Legacy UI source mismatch'}
  $legacyRecord=@{sha256=$legacyActivation.sha256;source=$legacySource;was_enabled=$legacy.Settings.Enabled;was_running=($legacy.State -eq 'Running');disabled_by_this_install=$true}
  # The immutable original helper verifies exact task action, SID, and snapshot.
  & (Join-Path $legacySource 'tools\dashboard.ps1') -Mode Status | Out-Null
  if(-not $?){throw 'Legacy UI ownership verification failed'}
 }
 Register-ScheduledTask -TaskName $taskName -TaskPath '\' -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Description $owner | Out-Null
 $existing=Get-ScheduledTask -TaskName $taskName -TaskPath '\'
 Assert-Owned $existing
 if($legacy){
  & (Join-Path $legacySource 'tools\dashboard.ps1') -Mode Disable | Out-Null
  if(-not $?){throw 'Legacy UI disable failed'}
  if($legacy.State -eq 'Running'){Stop-ScheduledTask -TaskName 'BGV-ResearchOps-UI-v1' -TaskPath '\'}
 }
 # Only an absent launcher or a verified owned one may be replaced. Preserve old bytes.
 $stamp=[Guid]::NewGuid().ToString()
 if(Test-Path -LiteralPath $launcher){
  Copy-Item -LiteralPath $launcher -Destination (Join-Path $directory ('launcher-backup-'+$stamp+'.exe'))
  Copy-Item -LiteralPath $launcherReceipt -Destination (Join-Path $directory ('launcher-backup-'+$stamp+'.json'))
 }
 $temporary=Join-Path $directory ('launcher-'+$stamp+'.tmp')
 Copy-Item -LiteralPath $launcherSource -Destination $temporary
 if((Get-FileHash -LiteralPath $temporary).Hash -cne (Get-FileHash -LiteralPath $launcherSource).Hash){throw 'Launcher copy changed'}
 if(Test-Path -LiteralPath $launcher){[IO.File]::Replace($temporary,$launcher,$null)}else{[IO.File]::Move($temporary,$launcher)}
 @{owner=$owner;sha256=(Get-FileHash -LiteralPath $launcher).Hash.ToLowerInvariant();bundle_sha256=$a.sha256;installed_at=(Get-Date).ToUniversalTime().ToString('o')}|ConvertTo-Json|Set-Content -LiteralPath $launcherReceipt -Encoding utf8
 foreach($path in $links){
  $link=$shell.CreateShortcut($path)
  $link.TargetPath=$launcher;$link.WorkingDirectory=$directory;$link.Description='BGV Scene Control — native read-only research dashboard';$link.IconLocation=(Join-Path $bundle 'app\SceneControl.ico')
  $link.Save()
 }
 @{owner=$owner;sha256=$a.sha256;registered_at=(Get-Date).ToUniversalTime().ToString('o');due_at=$when.ToUniversalTime().ToString('o');manual_start_used=$false;shortcuts=$links;legacy=$legacyRecord}|ConvertTo-Json -Depth 6|Set-Content -LiteralPath (Join-Path $directory 'installation.json') -Encoding utf8
}
if($Mode -eq 'EnsureService'){
 if(-not $existing){@{state='SERVICE_START_REFUSED'}|ConvertTo-Json -Compress;exit 2}
 Assert-Owned $existing
 if(-not $existing.Settings.Enabled){@{state='SERVICE_DISABLED'}|ConvertTo-Json -Compress;exit 2}
 if($existing.State.ToString() -notin @('Running','Queued')){Start-ScheduledTask -TaskName $taskName -TaskPath '\'}
 @{state='START_REQUESTED';task=$taskName}|ConvertTo-Json -Compress
 exit
}
if($Mode -eq 'Uninstall'){
 if($existing){
  Assert-Owned $existing
  if($existing.State -eq 'Running'){Stop-ScheduledTask -TaskName $taskName -TaskPath '\'}
  Unregister-ScheduledTask -TaskName $taskName -TaskPath '\' -Confirm:$false
 }
 foreach($path in $links){if(Test-Path -LiteralPath $path){Assert-Link $path;Remove-Item -LiteralPath $path}}
 @{owner=$owner;uninstalled=$true;runtime_retained=$true;research_unchanged=$true}|ConvertTo-Json
 exit
}
if($Mode -in @('Disable','Enable')){
 if(-not $existing){throw 'Desktop service is not installed'}
 if($Mode -eq 'Disable'){Disable-ScheduledTask -TaskName $taskName -TaskPath '\'|Out-Null}
 else{Enable-ScheduledTask -TaskName $taskName -TaskPath '\'|Out-Null}
 $existing=Get-ScheduledTask -TaskName $taskName -TaskPath '\'
}
if($Mode -eq 'Open'){if(-not(Test-Path -LiteralPath $launcher)){throw 'Stable launcher is not installed'};Start-Process -FilePath $launcher -WorkingDirectory $directory}
if(-not $existing){throw 'Desktop service is not installed'}
$info=Get-ScheduledTaskInfo -TaskName $taskName -TaskPath '\'
@{owner=$owner;task=$taskName;sha256=$a.sha256;state=$existing.State.ToString();enabled=$existing.Settings.Enabled;last_run=(Utc-OrNull $info.LastRunTime);last_result=$info.LastTaskResult;next_run=(Utc-OrNull $info.NextRunTime);wake=$existing.Settings.WakeToRun;restart_count=$existing.Settings.RestartCount;source=$source;app=$app;launcher=$launcher;shortcuts=$links}|ConvertTo-Json -Depth 6
