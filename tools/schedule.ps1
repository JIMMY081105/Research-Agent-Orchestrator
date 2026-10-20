param(
  [Parameter(Mandatory=$true)][ValidateSet('Install','Inspect','Uninstall','Disable','Enable')][string]$Mode,
  [string]$Runtime = 'E:\Github\Building-Generation-Validation\.runtime'
)
$ErrorActionPreference = 'Stop'
$name = 'BGV-ResearchOps-Observe-v1'
$owner = 'BGV.Windows.ResearchOps.v1'
if ([IO.Path]::GetFullPath($Runtime) -cne 'E:\Github\Building-Generation-Validation\.runtime') { throw 'Wrong runtime' }
$machine = Get-Content -LiteralPath (Join-Path $Runtime 'machine.json') -Raw | ConvertFrom-Json
$activation = Get-Content -LiteralPath (Join-Path $Runtime 'activation.json') -Raw | ConvertFrom-Json
if ($activation.owner -ne $owner) { throw 'Wrong activation owner' }
$source = [IO.Path]::GetFullPath($activation.source)
$expected = Join-Path $Runtime ('snapshots\' + $activation.source_sha256 + '\source')
if ($source -cne $expected) { throw 'Snapshot outside approved runtime' }
foreach ($path in @($Runtime,$source,$machine.python,$machine.pythonw,(Join-Path $source 'researchops.py'))) {
  if (-not (Test-Path -LiteralPath $path)) { throw "Required path unavailable: $path" }
  if ((Get-Item -LiteralPath $path).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse path rejected' }
}
$arguments = '"' + (Join-Path $source 'researchops.py') + '" --root "' + $source + '" --runtime "' + $Runtime + '" --expected-hash ' + $activation.source_sha256 + ' run --trigger scheduled'
$existing = Get-ScheduledTask -TaskName $name -TaskPath '\' -ErrorAction SilentlyContinue
function Assert-Owned($task) {
  if ($task.Description -ne $owner -or $task.Actions.Count -ne 1 -or
      $task.Actions[0].Execute -cne $machine.pythonw -or
      $task.Actions[0].Arguments -cne $arguments -or
      $task.Actions[0].WorkingDirectory -cne $source) { throw 'Same-name task is not exactly this deployment; refusing change' }
}
if ($existing) { Assert-Owned $existing }
if ($Mode -eq 'Uninstall') {
  if ($existing) { Unregister-ScheduledTask -TaskName $name -TaskPath '\' -Confirm:$false }
  @{owner=$owner;task=$name;unregistered=$true;data_retained=$true} | ConvertTo-Json
  exit 0
}
if ($Mode -in @('Disable','Enable')) {
  # Maintenance window for this system only: the exact owned task is paused or restored, never replaced.
  if (-not $existing) { throw 'System task not installed' }
  if ($Mode -eq 'Disable') { Disable-ScheduledTask -TaskName $name -TaskPath '\' | Out-Null }
  else { Enable-ScheduledTask -TaskName $name -TaskPath '\' | Out-Null }
  $existing = Get-ScheduledTask -TaskName $name -TaskPath '\'
  Assert-Owned $existing
}
if ($Mode -eq 'Install') {
  # Verify full snapshot + machine binding with accepted executable before registering.
  & $machine.python (Join-Path $source 'researchops.py') --root $source --runtime $Runtime --expected-hash $activation.source_sha256 identity
  if ($LASTEXITCODE -ne 0) { throw 'Snapshot/repository identity verification failed' }
  if ($existing) { throw 'Task already exists; use Inspect. No task overwritten.' }
  $action = New-ScheduledTaskAction -Execute $machine.pythonw -Argument $arguments -WorkingDirectory $source
  $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
  $settings = New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  $settings.WakeToRun = $false
  $sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  $principal = New-ScheduledTaskPrincipal -UserId $sid -LogonType Interactive -RunLevel Limited
  Register-ScheduledTask -TaskName $name -TaskPath '\' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description $owner | Out-Null
  $existing = Get-ScheduledTask -TaskName $name -TaskPath '\'
  Assert-Owned $existing
}
if (-not $existing) { throw 'System task not installed' }
$info = Get-ScheduledTaskInfo -TaskName $name -TaskPath '\'
$record = @{owner=$owner;task=$name;state=$existing.State.ToString();action=$arguments;
  executable=$existing.Actions[0].Execute;working_directory=$existing.Actions[0].WorkingDirectory;
  last_run=$info.LastRunTime.ToUniversalTime().ToString('o');last_result=$info.LastTaskResult;
  next_run=$info.NextRunTime.ToUniversalTime().ToString('o');interval=$existing.Triggers[0].Repetition.Interval;
  wake=$existing.Settings.WakeToRun;start_when_available=$existing.Settings.StartWhenAvailable;
  multiple_instances=$existing.Settings.MultipleInstances.ToString();logon_type=$existing.Principal.LogonType.ToString();
  user=$existing.Principal.UserId;run_level=$existing.Principal.RunLevel.ToString();
  execution_time_limit=$existing.Settings.ExecutionTimeLimit;enabled=$existing.Settings.Enabled}
$record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $Runtime 'scheduler-state.json') -Encoding UTF8
$record | ConvertTo-Json -Depth 5
