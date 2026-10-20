"""Actual WinPS child must work when a Python parent inherits foreign module paths."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import desktop
from researchops import desktop_bundle as bundle

@unittest.skipUnless(os.name == "nt", "Windows built-in PowerShell modules")
class NativePowerShellEnvironmentTests(unittest.TestCase):
    def test_disabled_response_survives_foreign_parent_module_path_without_changing_parent(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder); source=base/"source"; runtime=base/"runtime"
            (source/"tools").mkdir(parents=True); (runtime/"desktop").mkdir(parents=True)
            sha="a"*64
            (runtime/"desktop/activation.json").write_bytes(bundle.canonical(dict(owner=bundle.OWNER,sha256=sha,source=str(source))))
            # Read-only fixture: uses real Utility and ScheduledTasks command discovery,
            # never creates/starts/stops a task or accesses the installed runtime.
            (source/"tools/desktop.ps1").write_text(r"""param([string]$Mode,[string]$ExpectedHash)
$ErrorActionPreference='Stop'
if($Mode -cne 'EnsureService' -or $ExpectedHash -cne ('a'*64)){throw 'Wrong fixture arguments'}
$null=Get-FileHash -LiteralPath $PSCommandPath
$null=Get-Command Get-ScheduledTask -ErrorAction Stop
@{state='SERVICE_DISABLED'}|ConvertTo-Json -Compress
exit 2
""",encoding="utf-8")
            foreign=str(base/"foreign-modules")
            shadow=Path(foreign)/"Microsoft.PowerShell.Utility"; shadow.mkdir(parents=True)
            (shadow/"Microsoft.PowerShell.Utility.psd1").write_text(
                "@{RootModule='Utility.psm1';ModuleVersion='99.0';GUID='608762c1-0482-48b1-96cc-0607b79de262';FunctionsToExport=@('Get-FileHash');CmdletsToExport=@();AliasesToExport=@()}",encoding="utf-8")
            (shadow/"Utility.psm1").write_text(
                "function Get-FileHash { throw 'FIXTURE_FOREIGN_MODULE_REJECTED' }; Export-ModuleMember -Function Get-FileHash",encoding="utf-8")
            with patch.dict(os.environ,{"PSModulePath":foreign}), patch.object(desktop,"probe",return_value={"state":"STARTABLE"}):
                real_run=desktop.subprocess.run
                def broken_inherited_environment(*args,**kwargs):
                    kwargs.pop("env",None)
                    return real_run(*args,**kwargs)
                with patch.object(desktop.subprocess,"run",side_effect=broken_inherited_environment):
                    broken=desktop.ensure(source,runtime,sha)
                self.assertEqual("SERVICE_START_REFUSED",broken["state"])
                result=desktop.ensure(source,runtime,sha)
                self.assertEqual("SERVICE_DISABLED",result["state"])
                self.assertEqual(foreign,os.environ["PSModulePath"])
