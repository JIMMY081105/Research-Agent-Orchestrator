"""Real Windows LPAC negative and crash tests; unittest candidate for parent integration."""
import ctypes as C
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from researchops import appcontainer as ac, winproc as wp

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(os.name=='nt','Windows native security test')
class AppContainerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base=ROOT/'.runtime'/'test-appcontainer';base.mkdir(parents=True,exist_ok=True)
        cls.base=Path(tempfile.mkdtemp(prefix='lpac-',dir=base))
        cls.runtime=cls.base/'runtime'
        cls.python=ac.copy_runtime(sys.executable,cls.runtime)
    @classmethod
    def tearDownClass(cls):
        target=cls.base.resolve();boundary=(ROOT/'.runtime'/'test-appcontainer').resolve()
        if boundary not in target.parents:raise RuntimeError('Refusing unowned cleanup')
        shutil.rmtree(target)
    def folder(self,name):
        p=self.base/(name+'-'+os.urandom(5).hex());p.mkdir();return p
    def test_lpac_rejects_other_low_aap_old_profile_and_acl_changes(self):
        run=self.folder('negative');out=run/'out';out.mkdir();old=run/'old';old.mkdir();low=run/'low';low.mkdir();aap=run/'aap';aap.mkdir()
        for p in (low,aap):
            r=subprocess.run([wp.ICACLS,str(p),'/grant','*S-1-3-4:(OI)(CI)F'],capture_output=True,creationflags=0x08000000);self.assertEqual(0,r.returncode)
            r=subprocess.run([wp.ICACLS,str(p),'/setintegritylevel','(OI)(CI)low'],capture_output=True,creationflags=0x08000000);self.assertEqual(0,r.returncode)
        r=subprocess.run([wp.ICACLS,str(aap),'/grant','*S-1-15-2-1:(OI)(CI)M'],capture_output=True,creationflags=0x08000000);self.assertEqual(0,r.returncode)
        script=run/'probe.py';script.write_text(_NEGATIVE_CHILD,encoding='utf-8')
        with ac.AppContainer(run/'old-lease.json',wp.identity) as box:box.protect_output(old)
        with ac.AppContainer(run/'lease.json',wp.identity) as box:
            box.protect_readonly(self.runtime);box.protect_readonly(script);box.protect_output(out)
            paths=[self.runtime/'escape',low/'escape',aap/'escape',old/'escape',Path(os.environ['USERPROFILE'])/'AppData'/'LocalLow'/('bgv-'+os.urandom(5).hex()),box.profile/'escape',box.profile/'AC'/'escape']
            rc,stdout,stderr,_=wp.run_owned([str(self.python),'-I','-B',str(script),*[str(p) for p in paths]],'',out,box.environment(out),30,box.started,512,appcontainer_sid=box.sid,appcontainer_capabilities=box.capabilities)
            self.assertEqual(0,rc,(stdout,stderr));result=json.loads(stdout)
            self.assertEqual(1,result['is_appcontainer'])
            self.assertTrue(all(v=='PermissionError' for v in result['writes']))
            self.assertTrue(all(v==5 for v in result['acl_changes']))
            self.assertTrue((out/'allowed').is_file());self.assertTrue(all(not p.exists() for p in paths));profile=box.profile
        self.assertFalse(profile.exists())
    def test_setup_exception_cleans_profile(self):
        run=self.folder('setup');box=ac.AppContainer(run/'lease.json',wp.identity)
        with patch.object(ac,'exact_tree_acl',side_effect=RuntimeError('INJECTED')):
            with self.assertRaisesRegex(RuntimeError,'INJECTED'):
                with box:pass
        self.assertEqual('CLOSED',json.loads(box.lease.read_text())['state'])
    def test_live_owner_cannot_be_reclaimed(self):
        run=self.folder('live')
        with ac.AppContainer(run/'lease.json',wp.identity) as box:
            with self.assertRaises(RuntimeError):ac.recover_lease(box.lease,wp.identity)
            profile=box.profile
        self.assertFalse(profile.exists())
    def test_crash_recovers_profile_after_owned_job_child_is_dead(self):
        run=self.folder('crash');controller=run/'controller.py';controller.write_text(_CRASH_CONTROLLER,encoding='utf-8')
        done=subprocess.run([sys.executable,str(controller),str(ROOT),str(run),str(self.runtime)],capture_output=True,timeout=30,creationflags=0x08000000)
        self.assertEqual(51,done.returncode,done.stderr.decode('utf-8','replace'))
        lease=run/'crash-lease.json';data=json.loads(lease.read_text());self.assertIsNone(wp.identity(data['child']['pid']))
        self.assertTrue(ac.recover_lease(lease,wp.identity));self.assertFalse(Path(data['profile']).exists())
        self.assertFalse(ac.recover_lease(lease,wp.identity))

_NEGATIVE_CHILD=r'''from pathlib import Path
import os,json,sys,ctypes as C
from ctypes import wintypes as W
A=C.WinDLL('advapi32',use_last_error=True);K=C.WinDLL('kernel32',use_last_error=True);K.GetCurrentProcess.restype=W.HANDLE
A.OpenProcessToken.argtypes=[W.HANDLE,W.DWORD,C.POINTER(W.HANDLE)];A.GetTokenInformation.argtypes=[W.HANDLE,C.c_int,C.c_void_p,W.DWORD,C.POINTER(W.DWORD)]
t=W.HANDLE();assert A.OpenProcessToken(K.GetCurrentProcess(),8,C.byref(t));v=W.DWORD();n=W.DWORD();assert A.GetTokenInformation(t,29,C.byref(v),4,C.byref(n));r={'is_appcontainer':v.value,'writes':[],'acl_changes':[]}
for s in sys.argv[1:]:
 try:Path(s).write_text('escape');r['writes'].append('WROTE')
 except OSError as e:r['writes'].append(type(e).__name__)
A.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes=[W.LPCWSTR,W.DWORD,C.POINTER(C.c_void_p),C.POINTER(W.DWORD)];A.SetFileSecurityW.argtypes=[W.LPCWSTR,W.DWORD,C.c_void_p]
sd=C.c_void_p();assert A.ConvertStringSecurityDescriptorToSecurityDescriptorW('D:(A;;FA;;;WD)',1,C.byref(sd),None)
for s in [sys.argv[1],sys.argv[-1]]:
 ok=A.SetFileSecurityW(str(Path(s).parent),4,sd);r['acl_changes'].append(0 if ok else C.get_last_error())
Path('allowed').write_text('ok');print(json.dumps(r))
'''
_CRASH_CONTROLLER=r'''from pathlib import Path
import sys,os
root,run,runtime=map(Path,sys.argv[1:]);sys.path.insert(0,str(root))
from researchops import appcontainer as ac,winproc as wp
with ac.AppContainer(run/'crash-lease.json',wp.identity) as box:
 box.protect_readonly(runtime);out=run/'out';out.mkdir();box.protect_output(out)
 def started(pid,birth):box.started(pid,birth);os._exit(51)
 wp.run_owned([str(runtime/'python.exe'),'-I','-B','-c','import time; time.sleep(60)'],'',out,box.environment(out),90,started,512,appcontainer_sid=box.sid,appcontainer_capabilities=box.capabilities)
'''
