[CmdletBinding(PositionalBinding=$false)]
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$CommandArgs)
$ErrorActionPreference='Stop'
$repo='E:\Github\Building-Generation-Validation'
$runtime=Join-Path $repo '.runtime\github'
$a=Get-Content -LiteralPath (Join-Path $runtime 'activation.json') -Raw | ConvertFrom-Json
if($a.owner -cne 'BGV.Windows.GitHubReview.v1' -or $a.source_sha256 -notmatch '^[0-9a-f]{64}$'){throw 'Invalid GitHub bridge activation'}
$expected=Join-Path $runtime ('snapshots\'+$a.source_sha256+'\source')
if([IO.Path]::GetFullPath($a.source) -cne $expected){throw 'GitHub source outside fixed snapshot'}
if(-not $CommandArgs){$CommandArgs=@('status')}
& 'C:\Python312\python.exe' -B (Join-Path $expected 'github_review.py') --repo $repo --runtime $runtime --expected-source-sha $a.source_sha256 @CommandArgs
exit $LASTEXITCODE
