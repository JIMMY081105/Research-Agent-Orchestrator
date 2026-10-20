[CmdletBinding(PositionalBinding=$false)]
param([Parameter(ValueFromRemainingArguments=$true)][string[]]$CommandArgs)
$ErrorActionPreference='Stop'
$runtime='E:\Github\Building-Generation-Validation\.runtime'
$a=Get-Content -LiteralPath (Join-Path $runtime 'activation.json') -Raw | ConvertFrom-Json
$m=Get-Content -LiteralPath (Join-Path $runtime 'machine.json') -Raw | ConvertFrom-Json
if($a.owner -ne 'BGV.Windows.ResearchOps.v1'){throw 'Invalid deployment owner'}
if(-not $CommandArgs){$CommandArgs=@('status')}
& $m.python (Join-Path $a.source 'researchops.py') --root $a.source --runtime $runtime --expected-hash $a.source_sha256 @CommandArgs
exit $LASTEXITCODE
