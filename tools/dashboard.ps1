[CmdletBinding()]
param([ValidateSet('Install','Status','Open','Uninstall','Disable','Enable')][string]$Mode='Status')
$ErrorActionPreference='Stop'
$runtime='E:\Github\Building-Generation-Validation\.runtime'
$directory=Join-Path $runtime 'dashboard'
$owner='BGV.Windows.ResearchOps.UI.v1'
$taskName='BGV-ResearchOps-UI-v1'
$activation=Get-Content -LiteralPath (Join-Path $directory 'activation.json') -Raw | ConvertFrom-Json
if($activation.owner -cne $owner){throw 'Wrong UI owner'}
if($activation.sha256 -notmatch '^[0-9a-f]{64}$'){throw 'Invalid UI snapshot hash'}
$bundle=[IO.Path]::GetFullPath((Join-Path $directory ('snapshots\'+$activation.sha256)))
$source=Join-Path $bundle 'source'
if([IO.Path]::GetFullPath($activation.source) -cne $source){throw 'UI source outside approved snapshot'}
$python='C:\Python312\python.exe'
$pythonw='C:\Python312\pythonw.exe'
foreach($path in @($runtime,$directory,$bundle,$source,$python,$pythonw)){
  if(-not(Test-Path -LiteralPath $path)){throw 'Required UI path unavailable'}
  $current=Get-Item -LiteralPath $path
  while($current){
    if($current.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'UI reparse path rejected'}
    $current=$current.Parent
  }
}
if($Mode -ne 'Uninstall'){
  & $python -B (Join-Path $source 'dashboard.py') verify --root $source --expected-hash $activation.sha256 --runtime $runtime
  if($LASTEXITCODE -ne 0){throw 'UI snapshot verification failed'}
}
$arguments='-B "'+(Join-Path $source 'dashboard.py')+'" serve --root "'+$source+'" --runtime "'+$runtime+'" --expected-hash '+$activation.sha256+' --trigger scheduled-ui'
$existing=Get-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction SilentlyContinue
function Assert-Owned($task){
  if($task.Description -cne $owner -or $task.Actions.Count -ne 1 -or
     $task.Actions[0].Execute -cne $pythonw -or $task.Actions[0].Arguments -cne $arguments -or
     $task.Actions[0].WorkingDirectory -cne $source){throw 'Same-name task belongs to another deployment'}
  $expectedSid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  $recordedSid=$task.Principal.UserId
  if($recordedSid -notlike 'S-1-*'){$recordedSid=([Security.Principal.NTAccount]$recordedSid).Translate([Security.Principal.SecurityIdentifier]).Value}
  if($recordedSid -cne $expectedSid -or $task.Principal.LogonType.ToString() -ne 'Interactive' -or
     $task.Principal.RunLevel.ToString() -ne 'Limited'){throw 'Wrong UI task principal'}
}
if($existing){Assert-Owned $existing}
if($Mode -eq 'Install'){
  if($existing){throw 'UI task already exists; no task overwritten'}
  $action=New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $source
  $when=(Get-Date).AddMinutes(1)
  $triggers=@((New-ScheduledTaskTrigger -Once -At $when),(New-ScheduledTaskTrigger -AtLogOn -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name)))
  $settings=New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  $settings.WakeToRun=$false
  $principal=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value) -LogonType Interactive -RunLevel Limited
  Register-ScheduledTask -TaskName $taskName -TaskPath '\' -Action $action -Trigger $triggers -Settings $settings -Principal $principal -Description $owner | Out-Null
  @{owner=$owner;registered_at=(Get-Date).ToUniversalTime().ToString('o');due_at=$when.ToUniversalTime().ToString('o');sha256=$activation.sha256;manual_start_used=$false}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $directory 'schedule-registration.json') -Encoding utf8
  $existing=Get-ScheduledTask -TaskName $taskName -TaskPath '\'
}
if($Mode -eq 'Uninstall'){
  if($existing){
    Assert-Owned $existing
    # Scheduler stops only the exact new UI action, never the research controller.
    if($existing.State -eq 'Running'){Stop-ScheduledTask -TaskName $taskName -TaskPath '\'}
    Unregister-ScheduledTask -TaskName $taskName -TaskPath '\' -Confirm:$false
  }
  @{owner=$owner;uninstalled=$true;controller_unchanged=$true;runtime_retained=$true}|ConvertTo-Json
  exit
}
if($Mode -in @('Disable','Enable')){
  if(-not $existing){throw 'UI task not installed'}
  Assert-Owned $existing
  if($Mode -eq 'Disable'){Disable-ScheduledTask -TaskName $taskName -TaskPath '\'|Out-Null}
  else{Enable-ScheduledTask -TaskName $taskName -TaskPath '\'|Out-Null}
  $existing=Get-ScheduledTask -TaskName $taskName -TaskPath '\'
}
if($Mode -eq 'Open'){
  $config=Get-Content -LiteralPath (Join-Path $source 'config\live.json') -Raw|ConvertFrom-Json
  Start-Process ('http://127.0.0.1:'+$config.port)
}
if(-not $existing){throw 'UI task not installed'}
$info=Get-ScheduledTaskInfo -TaskName $taskName -TaskPath '\'
function ConvertTo-UtcOrNull($value){
  if($null -eq $value){return $null}
  return $value.ToUniversalTime().ToString('o')
}
@{owner=$owner;task=$taskName;state=$existing.State.ToString();last_run=(ConvertTo-UtcOrNull $info.LastRunTime);last_result=$info.LastTaskResult;next_run=(ConvertTo-UtcOrNull $info.NextRunTime);source=$source;sha256=$activation.sha256;wake=$existing.Settings.WakeToRun;enabled=$existing.Settings.Enabled;execution_time_limit=$existing.Settings.ExecutionTimeLimit;user=$existing.Principal.UserId;logon_type=$existing.Principal.LogonType.ToString();run_level=$existing.Principal.RunLevel.ToString();action=$existing.Actions[0].Arguments}|ConvertTo-Json -Depth 5
