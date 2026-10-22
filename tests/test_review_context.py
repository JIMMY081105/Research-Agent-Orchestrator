"""Scope/size/staleness checks must reject broken review inputs without model calls."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from researchops import review_context as c

ROOT=Path(__file__).resolve().parents[1]


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'repo';self.root.mkdir()
        self.policy=json.loads((ROOT/'config/review-context.json').read_bytes())
        for name in self.policy['ui_context']:
            self.write(name,'CSS = "old layout"\n' if name!='native/SceneControl.cs' else 'class Window { private const string Probe = @"old geometry"; }\n')
        for name in c.SKILLS:self.write(name,(ROOT/name).read_text(encoding='utf-8'))
        self.write('config/review-context.json',json.dumps(self.policy))
        self.write('researchops/unrelated.py','# unchanged unrelated source\n'*300)
        self.initial=self.manifest();self.tests=self.base/'tests.json'
        files={'source/'+n:h for n,h in self.initial['files'].items()}
        manifest=dict(owner='BGV.Windows.SceneControl.Desktop.v1',files=files,sha256=c.digest(c.canonical(files)),source_sha256=self.initial['sha256'])
        self.snapshot=self.base/manifest['sha256'];self.snapshot.mkdir()
        for name in self.initial['files']:
            dest=self.snapshot/'source'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((self.root/name).read_bytes())
        (self.snapshot/'manifest.json').write_bytes(c.canonical(manifest))
        self.review=self.base/'review.json';self.proof=dict(owner=manifest['owner'],status='PASS',verdict='PASS',issues=[],tools_disabled=True,evidence={'exit_code':0},bundle_sha256=manifest['sha256'],source_sha256=self.initial['sha256'])
        self.review.write_bytes(c.canonical(self.proof))

    def write(self,name,text):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(text.encode('utf-8'))

    def manifest(self):
        files={p.relative_to(self.root).as_posix():c.digest(p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}
        return dict(files=files,sha256=c.digest(c.canonical(files)))

    def prepare(self,**kwargs):
        source=self.manifest()
        tests=dict(source_sha256=source['sha256'],success=True,source_unchanged=True,tests_run=205,discovered=205,errors=[],failures=[],skipped=[],transcript='x'*100000)
        self.tests.write_bytes(c.canonical(tests))
        return c.prepare(self.root,source,self.tests,snapshot=self.snapshot,review_path=self.review,**kwargs)

    def test_uncommitted_ui_change_uses_delta_and_full_cross_language_context(self):
        self.write('researchops/mission_web.py','CSS = "new layout"\n')
        packet,criteria,metrics=self.prepare()
        self.assertEqual(packet['scope'],'DELTA_WITH_CONTEXT')
        self.assertEqual(packet['changed_paths'],['researchops/mission_web.py'])
        self.assertIn('old layout',packet['changes'][0]['diff'])
        self.assertIn('new layout',packet['changes'][0]['diff'])
        self.assertEqual(set(packet['contents']),set(self.policy['ui_context']))
        self.assertNotIn('researchops/unrelated.py',packet['contents'])
        self.assertIn('researchops/unrelated.py',packet['source_manifest']['files'])
        self.assertNotIn('transcript',packet['tests']);self.assertIn('NEEDS_CONTEXT',criteria)
        self.assertLess(metrics['packet_bytes'],30000)

    def test_permissions_change_cannot_force_delta(self):
        self.write('researchops/mission_web.py','fetch("/api/worker/approval");\n')
        self.assertEqual(self.prepare()[0]['scope'],'FULL_SOURCE')
        with self.assertRaisesRegex(ValueError,'FULL_SCOPE_REQUIRED'):self.prepare(scope='delta')

    def test_host_code_change_outside_probe_requires_full_source(self):
        self.write('native/SceneControl.cs','class Other { private const string Probe = @"old geometry"; }\n')
        self.assertEqual(self.prepare()[0]['scope'],'FULL_SOURCE')

    def test_geometry_probe_change_can_use_delta(self):
        self.write('native/SceneControl.cs','class Window { private const string Probe = @"new geometry"; }\n')
        self.assertEqual(self.prepare()[0]['scope'],'DELTA_WITH_CONTEXT')

    def test_new_file_or_deleted_file_is_not_silently_skipped(self):
        self.write('researchops/new_queue.py','permission = "changed"\n')
        packet,_,_=self.prepare();self.assertEqual(packet['scope'],'FULL_SOURCE')
        self.assertIn('researchops/new_queue.py',packet['changed_paths'])
        (self.root/'researchops/mission_web.py').unlink()
        packet,_,_=self.prepare();change=next(v for v in packet['changes'] if v['path']=='researchops/mission_web.py')
        self.assertEqual(change['operation'],'DELETE');self.assertIn('old layout',change['diff'])

    def test_stale_baseline_rejected_even_if_head_unchanged(self):
        (self.snapshot/'source/researchops/mission_web.py').write_text('tampered')
        with self.assertRaisesRegex(ValueError,'SOURCE_BINDING_CHANGED'):self.prepare()

    def test_failed_or_mismatched_baseline_cannot_approve_delta(self):
        for patch in ({'status':'REWORK'},{'source_sha256':'a'*64},{'tools_disabled':False}):
            self.review.write_bytes(c.canonical({**self.proof,**patch}))
            with self.assertRaises(ValueError):self.prepare()

    def test_over_budget_packet_fails_instead_of_truncating_diff(self):
        self.policy['max_packet_bytes']=8192
        self.write('config/review-context.json',json.dumps(self.policy))
        self.write('researchops/unrelated.py','x'*15000)
        self.policy['max_full_packet_bytes']=8192
        self.write('config/review-context.json',json.dumps(self.policy))
        with self.assertRaisesRegex(ValueError,'CONTEXT_LIMIT'):self.prepare()

    def test_changed_source_after_manifest_capture_is_rejected(self):
        manifest=self.manifest();self.write('researchops/mission_web.py','edited')
        with self.assertRaisesRegex(ValueError,'SOURCE_BINDING_CHANGED'):c.read_sources(self.root,manifest)

    def test_sensitive_path_is_rejected_before_reading(self):
        for name in ('../auth.json','.runtime/machine.json','config/.env','C:/token.txt','x\\auth.json'):
            with self.subTest(path=name),self.assertRaisesRegex(ValueError,'UNSAFE_SOURCE_PATH'):c.relative(name)

    def test_missing_requested_context_is_not_guessed(self):
        self.write('researchops/mission_web.py','CSS = "new layout"\n')
        with self.assertRaisesRegex(ValueError,'CONTEXT_FILE_UNKNOWN'):self.prepare(include=['missing.py'])

    def test_incomplete_test_run_is_not_compacted_into_success(self):
        with self.assertRaisesRegex(ValueError,'CURRENT_TESTS_REQUIRED'):
            c.compact_tests(dict(source_sha256='x',success=True,source_unchanged=True,tests_run=9,discovered=10,errors=[],failures=[],skipped=[]),'x','x')

    def test_no_baseline_defaults_full_and_explicit_delta_refuses(self):
        source=self.manifest()
        self.tests.write_bytes(c.canonical(dict(source_sha256=source['sha256'],success=True,source_unchanged=True,tests_run=1,discovered=1,errors=[],failures=[],skipped=[])))
        packet,_,_=c.prepare(self.root,source,self.tests)
        self.assertEqual(packet['scope'],'FULL_SOURCE')
        with self.assertRaisesRegex(ValueError,'BASELINE_REQUIRED'):c.prepare(self.root,source,self.tests,scope='delta')

    def test_no_change_is_deferred_without_resending_approved_source(self):
        with self.assertRaisesRegex(ValueError,'NO_SOURCE_CHANGE'):self.prepare()


if __name__=='__main__':unittest.main()
