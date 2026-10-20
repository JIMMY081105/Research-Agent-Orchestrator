"""Execute the reviewed installer replacement line on both installed PS hosts."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(os.name=="nt","Windows native installer interop")
class LauncherReplacementTests(unittest.TestCase):
    def test_existing_launcher_replacement_preserves_backup_and_null_negative_control_fails(self):
        lines=[s.strip() for s in (ROOT/"tools/desktop.ps1").read_text(encoding="utf-8").splitlines() if "[IO.File]::Replace($temporary,$launcher," in s]
        self.assertEqual(1,len(lines));line=lines[0]
        broken=line.replace("(Join-Path $directory ('launcher-replaced-'+$stamp+'.exe'))","$null")
        self.assertNotEqual(line,broken)
        hosts=[r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",shutil.which("pwsh.exe") or shutil.which("pwsh")]
        for host in dict.fromkeys(h for h in hosts if h):
            for code,success in ((broken,False),(line,True)):
                with self.subTest(host=host,success=success), tempfile.TemporaryDirectory() as folder:
                    base=Path(folder);target=base/"launcher.exe";temporary=base/"candidate.tmp"
                    target.write_text("old-reviewed-launcher");temporary.write_text("new-reviewed-launcher")
                    def quote(value):return "'"+str(value).replace("'","''")+"'"
                    command=("$ErrorActionPreference='Stop';$directory="+quote(base)+";$stamp='fixture';$launcher="+quote(target)+";$temporary="+quote(temporary)+";"+code)
                    run=subprocess.run([host,"-NoProfile","-NonInteractive","-Command",command],capture_output=True,timeout=25,creationflags=0x08000000,
                        env={**os.environ,"PSModulePath":str(Path(host).parent/"Modules")})
                    if success:
                        self.assertEqual(0,run.returncode,run.stderr.decode("utf-8-sig",errors="replace"))
                        self.assertEqual("new-reviewed-launcher",target.read_text())
                        self.assertEqual("old-reviewed-launcher",(base/"launcher-replaced-fixture.exe").read_text())
                        self.assertFalse(temporary.exists())
                    else:
                        self.assertNotEqual(0,run.returncode)
                        self.assertEqual("old-reviewed-launcher",target.read_text())
                        self.assertTrue(temporary.exists())
