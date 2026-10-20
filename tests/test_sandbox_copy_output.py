"""Regression fixtures for source-copy pin coverage and output pre-read reparse rejection."""
import json
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from researchops import appcontainer as ac, scene

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(os.name=='nt','Native Windows junction regression')
class SandboxCopyOutputTests(unittest.TestCase):
    def setUp(self):
        boundary=ROOT/'.runtime'/'test-sandbox-copy-output';boundary.mkdir(parents=True,exist_ok=True)
        self.boundary=boundary.resolve();self.base=Path(tempfile.mkdtemp(prefix='case-',dir=boundary))
    def tearDown(self):
        target=self.base.resolve()
        if self.boundary not in target.parents:raise RuntimeError('Refusing unowned test cleanup')
        # shutil.rmtree on Windows removes junction itself and does not traverse target.
        shutil.rmtree(target)
    def test_prepare_copies_only_code_suffixes_covered_by_external_pin(self):
        source=self.base/'registered-source';source.mkdir();(source/'config.py').write_text('KNOWN = 1\n')
        profiles=source/'profiles';profiles.mkdir();(profiles/'generic.yaml').write_text('profile: known\n')
        suffixes=['.py','.yaml'];before=scene.tree_sha256(source,suffixes)
        unexpected=source/'config.pyd';unexpected.write_bytes(b'FAKE_NONEXECUTABLE_NATIVE_BYTES')
        self.assertEqual(before,scene.tree_sha256(source,suffixes),'The fixture must expose the pin coverage gap')
        project=self.base/'project';(project/'researchops').mkdir(parents=True);(project/'researchops'/'scene_runner.py').write_text('# fake runner; never executed\n')
        stage=self.base/'stage';stage.mkdir();packages=self.base/'packages';packages.mkdir()
        for name in ('numpy','scipy','trimesh','pxr','yaml','_yaml'):(packages/name).mkdir()
        system=SimpleNamespace(root=project,machine={'python':'FAKE_INTERPRETER_NOT_EXECUTED'})
        tools={'external':{'buildingsgen':{'path':str(source),'suffixes':suffixes}}}
        def runtime_copy(_python,dest,_packages):
            Path(dest).mkdir(parents=True);(Path(dest)/'python.exe').write_bytes(b'FAKE_NOT_EXECUTED')
        original=Path.read_bytes
        def guarded_read(path):
            if path==unexpected:raise AssertionError('Unpinned native source read/copied')
            return original(path)
        with patch.object(scene.importlib.util,'find_spec',side_effect=lambda name:SimpleNamespace(submodule_search_locations=[str(packages/name)])),patch.object(ac,'copy_runtime',side_effect=runtime_copy),patch.object(Path,'read_bytes',guarded_read):
            base,_,_,_,_=scene.prepare_sandbox(system,{},tools,stage,'stair.candidates',{})
        files={p.relative_to(base/'src/buildingsgen').as_posix() for p in (base/'src/buildingsgen').rglob('*') if p.is_file()}
        self.assertEqual({'config.py','profiles/generic.yaml'},files)
        self.assertFalse((base/'src/buildingsgen/config.pyd').exists())
    def test_run_tool_rejects_output_junction_before_reading_any_output(self):
        import _winapi
        work=self.base/'work';work.mkdir();stage=work/'exec-fixture'
        outside=self.base/'outside';outside.mkdir();(outside/'FAKE_PUBLIC_FIXTURE.txt').write_text('NON_SENSITIVE_FIXTURE_ONLY')
        sandbox=stage/'_sandbox';base=sandbox/'base';base.mkdir(parents=True);(base/'placeholder').write_text('known')
        copied=sandbox/'inputs';copied.mkdir()
        system=SimpleNamespace(root=self.base,runtime=self.base/'runtime',policy={'tool_timeout_seconds':30,'tool_memory_mb':512},remaining_timeout=lambda value:value)
        tool_id='registered.probe';tools={'external':{'buildingsgen':{'repository':str(self.base)}},'scenes':{},'tools':{tool_id:{'runner':'fixed_probe','params':{},'bindings':[]}}}
        class Box:
            sid=None;capabilities=None
            def __init__(self,*_):pass
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def protect_readonly(self,*_):pass
            def protect_output(self,*_):pass
            def environment(self,*_):return {}
            def started(self,*_):pass
        out=stage/tool_id;output_reads=[]
        def owned(_argv,_prompt,_cwd,_env,_timeout,on_start,*args,**kwargs):
            (out/'result.json').write_text(json.dumps({'ok':True,'result':{'must_not_be_read':True}}))
            _winapi.CreateJunction(str(outside),str(out/'redirect'))
            self.assertTrue((out/'redirect').is_junction(),'Native junction fixture must be real')
            on_start(os.getpid(),'fixture-birth')
            return 0,'','',0.01
        original_read=scene.read_json
        def guarded_json(path):
            path=Path(path)
            if path==out/'result.json':
                output_reads.append(str(path));raise AssertionError('Child output read before entire tree was vetted')
            return original_read(path)
        with patch.object(scene,'registry',return_value=(tools,{})),patch.object(scene,'check_bindings',return_value={}),patch.object(scene,'restore_low_labels'),patch.object(scene,'recover_tool_profiles'),patch.object(scene,'listing_sha256',return_value='unchanged'),patch.object(scene,'prepare_sandbox',return_value=(base,ac.hash_tree(base),copied,ac.hash_tree(copied),{})),patch.object(ac,'AppContainer',Box),patch.object(scene.winproc,'run_owned',side_effect=owned),patch.object(scene,'read_json',side_effect=guarded_json):
            with self.assertRaisesRegex(ValueError,'Reparse'):
                scene.run_tool(system,{'workdir':str(work)},tool_id,{},stage)
        self.assertEqual([],output_reads)
        self.assertEqual('NON_SENSITIVE_FIXTURE_ONLY',(outside/'FAKE_PUBLIC_FIXTURE.txt').read_text())
