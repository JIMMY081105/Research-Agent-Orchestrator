[CmdletBinding()]
param([ValidateSet('Install','Status','Disable','Enable','StopWhenIdle','Uninstall')][string]$Mode='Status')
$ErrorActionPreference='Stop'
$runtime='E:\Github\Building-Generation-Validation\.runtime'
foreach($required in @($runtime,(Join-Path $runtime 'worker'),(Join-Path $runtime 'worker\activation.json'))){
 $item=Get-Item -LiteralPath $required
 while($item){if($item.Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Worker reparse path'};$item=$item.Parent}
}
$a=Get-Content -LiteralPath (Join-Path $runtime 'worker\activation.json') -Raw | ConvertFrom-Json
$owner='BGV.Windows.CodexWorker.v1'
$name='BGV-Codex-Worker-v1'
$python='C:\Python312\pythonw.exe'
if($a.owner -cne $owner -or $a.sha256 -notmatch '^[0-9a-f]{64}$'){throw 'Invalid worker activation'}
$source=Join-Path $runtime ('desktop\snapshots\'+$a.sha256+'\source')
if([IO.Path]::GetFullPath($a.source) -cne $source){throw 'Worker source outside snapshot'}
& 'C:\Python312\python.exe' -B (Join-Path $source 'desktop.py') verify --root $source --runtime $runtime --expected-hash $a.sha256 | Out-Null
if($LASTEXITCODE -ne 0){throw 'Worker snapshot verification failed'}
$arguments='-B "'+(Join-Path $source 'worker.py')+'" serve --runtime "'+$runtime+'" --expected-hash '+$a.sha256+' --trigger scheduled-worker'
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$task=Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue
if($task){
 $actualSid=$task.Principal.UserId
 if($actualSid -notlike 'S-1-*'){$actualSid=([Security.Principal.NTAccount]$actualSid).Translate([Security.Principal.SecurityIdentifier]).Value}
 if($task.Description -cne $owner -or $task.Actions.Count -ne 1 -or $task.Actions[0].Execute -cne $python -or $task.Actions[0].Arguments -cne $arguments -or $task.Actions[0].WorkingDirectory -cne $source -or $actualSid -cne $sid -or $task.Principal.LogonType.ToString() -ne 'Interactive' -or $task.Principal.RunLevel.ToString() -ne 'Limited'){throw 'Worker task ownership/version mismatch'}
}
if($Mode -eq 'Install'){
 if($task){throw 'Worker task already exists'}
 $action=New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $source
 $triggers=@((New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1))),(New-ScheduledTaskTrigger -AtLogOn -User $sid))
 $settings=New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
 $settings.WakeToRun=$false
 $principal=New-ScheduledTaskPrincipal -UserId $sid -LogonType Interactive -RunLevel Limited
 Register-ScheduledTask -TaskName $name -TaskPath '\' -Description $owner -Action $action -Trigger $triggers -Settings $settings -Principal $principal | Out-Null
} elseif($Mode -eq 'Disable'){
 if(-not $task){throw 'Worker task missing'}
 Disable-ScheduledTask -TaskName $name -TaskPath '\' | Out-Null
 @{owner=$owner;created_at=(Get-Date).ToUniversalTime().ToString('o')}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $runtime 'worker\admission-paused.json') -Encoding UTF8
 # Existing active turns and approval replies continue; only new admissions pause.
} elseif($Mode -eq 'Enable'){
 if(-not $task){throw 'Worker task missing'}
 foreach($file in @('admission-paused.json','review-pause.json','stop-when-idle.json')){
  $path=Join-Path $runtime ('worker\'+$file)
  if(Test-Path -LiteralPath $path){
   $record=Get-Content -LiteralPath $path -Raw|ConvertFrom-Json
   if($record.owner -cne $owner){throw 'Unknown worker pause record'}
   $preserved=Join-Path $runtime ('worker\'+[guid]::NewGuid().ToString()+'-'+$file)
   Move-Item -LiteralPath $path -Destination $preserved
  }
 }
 Enable-ScheduledTask -TaskName $name -TaskPath '\' | Out-Null
 if($task.State.ToString() -notin @('Running','Queued')){Start-ScheduledTask -TaskName $name -TaskPath '\'}
} elseif($Mode -eq 'StopWhenIdle'){
 if(-not $task){throw 'Worker task missing'}
 @{owner=$owner;created_at=(Get-Date).ToUniversalTime().ToString('o')}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $runtime 'worker\stop-when-idle.json') -Encoding UTF8
} elseif($Mode -eq 'Uninstall'){
 if($task){
  $db=Join-Path $runtime 'worker\worker.sqlite3'
  if($task.State.ToString() -in @('Running','Queued')){throw 'Worker service is running; retain active work and uninstall only after an owned idle shutdown'}
  Unregister-ScheduledTask -TaskName $name -TaskPath '\' -Confirm:$false
 }
} elseif($task){
 $info=Get-ScheduledTaskInfo -TaskName $name -TaskPath '\'
 @{owner=$owner;state=$task.State.ToString();enabled=$task.Settings.Enabled;last_result=$info.LastTaskResult}|ConvertTo-Json -Compress
} else {@{state='NOT_INSTALLED'}|ConvertTo-Json -Compress}
