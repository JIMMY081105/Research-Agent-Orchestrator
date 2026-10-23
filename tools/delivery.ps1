[CmdletBinding()]
param([ValidateSet('Install','Status','Disable','Enable','StopWhenIdle','Uninstall')][string]$Mode='Status')
$ErrorActionPreference='Stop'
$env:PSModulePath=Join-Path $PSHOME 'Modules'
$homeDir='E:\Github\Building-Generation-Validation\.runtime\worker-delivery'
$owner='BGV.Worker.ResultDelivery.v1';$name='BGV-Result-Delivery-v1'
if(-not(Test-Path -LiteralPath $homeDir -PathType Container)){throw 'Result delivery runtime unavailable'}
$a=Get-Content -LiteralPath (Join-Path $homeDir 'activation.json') -Raw|ConvertFrom-Json
if($a.owner -cne $owner -or $a.sha256 -cnotmatch '^[0-9a-f]{64}$'){throw 'Unknown publisher activation'}
$source=Join-Path $homeDir ('snapshots\'+$a.sha256+'\source')
if($a.source -cne $source){throw 'Publisher source path mismatch'}
$entry=Join-Path $source 'delivery_agent.py'
& 'C:\Python312\python.exe' -B $entry verify|Out-Null
if($LASTEXITCODE -ne 0){throw 'Publisher source verification failed'}
$task=Get-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction SilentlyContinue
if($task -and ($task.Description -cne $owner -or $task.Actions[0].WorkingDirectory -cne $source)){throw 'Unknown same-name task; not replaced'}
switch($Mode){
 'Install'{
  if($task){throw 'Owned task already exists; inspect it instead of overwriting'}
  $user=[Security.Principal.WindowsIdentity]::GetCurrent()
  $action=New-ScheduledTaskAction -Execute 'C:\Python312\pythonw.exe' -Argument ('-B "'+$entry+'" serve') -WorkingDirectory $source
  $trigger=@((New-ScheduledTaskTrigger -AtLogOn -User $user.Name),(New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15) -RepetitionDuration (New-TimeSpan -Days 3650)))
  $principal=New-ScheduledTaskPrincipal -UserId $user.User.Value -LogonType Interactive -RunLevel Limited
  $settings=New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  Register-ScheduledTask -TaskPath '\' -TaskName $name -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description $owner|Out-Null
 }
 'Disable'{& 'C:\Python312\python.exe' -B $entry disable;if($LASTEXITCODE -ne 0){throw 'Pause failed'};if($task){Disable-ScheduledTask -TaskPath '\' -TaskName $name|Out-Null}}
 'Enable'{& 'C:\Python312\python.exe' -B $entry enable;if($LASTEXITCODE -ne 0){throw 'Resume failed'};if($task){Enable-ScheduledTask -TaskPath '\' -TaskName $name|Out-Null}}
 'StopWhenIdle'{& 'C:\Python312\python.exe' -B $entry stop-when-idle;if($LASTEXITCODE -ne 0){throw 'Idle stop failed'}}
 'Uninstall'{
  $p=Join-Path $homeDir 'service.json'
  if(Test-Path -LiteralPath $p){$s=Get-Content -LiteralPath $p -Raw|ConvertFrom-Json;if($s.owner -cne $owner -or $s.birth -cnotmatch '^[0-9]+$'){throw 'Unknown publisher process identity'};$process=Get-Process -Id $s.pid -ErrorAction SilentlyContinue;if($process -and $process.StartTime.ToUniversalTime().ToFileTimeUtc().ToString() -ceq $s.birth){throw 'Owned publisher still alive; use Disable and StopWhenIdle first'}}
  if($task){Unregister-ScheduledTask -TaskPath '\' -TaskName $name -Confirm:$false}
 }
}
if($Mode -ne 'Uninstall'){Get-ScheduledTask -TaskPath '\' -TaskName $name -ErrorAction SilentlyContinue|Select-Object TaskName,State,Description}
