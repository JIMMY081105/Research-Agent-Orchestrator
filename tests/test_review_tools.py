"""Skill ownership and CLI preparation are exercised in temporary directories only."""
import json
from pathlib import Path
import tempfile
import contextlib
import io
import sys
import unittest
from unittest.mock import patch
from tools.install_review_skills import install

ROOT=Path(__file__).resolve().parents[1]


class SkillInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.homes={'codex':self.base/'codex','claude':self.base/'claude'}

    def test_both_clients_receive_exact_skills_and_repeat_check_is_idempotent(self):
        result=install(ROOT,self.homes)
        self.assertEqual(len(result),6)
        self.assertTrue(all(r['verified'] for r in result))
        before={r['path']:Path(r['path']).read_bytes() for r in result}
        self.assertTrue(all(r['verified'] for r in install(ROOT,self.homes,check=True)))
        install(ROOT,self.homes)
        self.assertEqual(before,{p:Path(p).read_bytes() for p in before})

    def test_unknown_skill_preflight_prevents_every_write(self):
        path=self.homes['claude']/'skills/diff-review';path.mkdir(parents=True)
        (path/'SKILL.md').write_text('unknown user content')
        with self.assertRaisesRegex(ValueError,'UNKNOWN_OR_EDITED_SKILL_RETAINED'):install(ROOT,self.homes)
        self.assertFalse(self.homes['codex'].exists())
        self.assertEqual((path/'SKILL.md').read_text(),'unknown user content')

    def test_manual_edits_to_our_skill_are_retained(self):
        result=install(ROOT,self.homes)
        path=Path(result[0]['path']);path.write_text('user override')
        with self.assertRaisesRegex(ValueError,'UNKNOWN_OR_EDITED_SKILL_RETAINED'):install(ROOT,self.homes)
        self.assertEqual(path.read_text(),'user override')


class AuditCliTests(unittest.TestCase):
    def setUp(self):
        from test_review_context import ContextTests
        self.fixture=ContextTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.fixture.write('researchops/mission_web.py','CSS = "changed layout"\n')
        self.fixture.prepare()
        self.runtime=self.fixture.base/'runtime';self.runtime.mkdir()
        self.config=self.fixture.base/'config.json';self.config.write_text('{}')
        self.build=self.fixture.base/'build.json';self.build.write_text('{}')

    def invoke(self,verdict='PASS',tamper=False,extra=()):
        from tools import review_desktop as cli
        from researchops.token_usage import claude_usage
        args=['review_desktop.py','--config',str(self.config),'--assets',str(self.fixture.base),
              '--app',str(self.fixture.base),'--build',str(self.build),'--tests',str(self.fixture.tests),
              '--baseline-snapshot',str(self.fixture.snapshot),'--baseline-review',str(self.fixture.review),*extra]
        def packed(*_):return dict(sha256='c'*64,source_sha256=self.fixture.manifest()['sha256'])
        def model(engine,machine,policy,prompt,schema,cwd,on_start,session,effort):
            spec=json.loads(Path(schema).read_bytes())['properties']
            value=dict(source_sha256=spec['source_sha256']['const'],package_sha256=spec['package_sha256']['const'],
                       verdict=verdict,issues=['Missing dependency'] if verdict=='NEEDS_CONTEXT' else [])
            if tamper:(Path(cwd).parent/'package.txt').write_text('tampered after model input')
            return value,dict(exit_code=0,tools_disabled=True,session_id=session,token_usage=claude_usage({'usage':{'input_tokens':4,'output_tokens':2}}))
        with patch.object(cli,'ROOT',self.fixture.root),patch.object(cli,'RUNTIME',self.runtime),\
             patch.object(cli.bundle,'source_manifest',side_effect=lambda _:self.fixture.manifest()),\
             patch.object(cli.bundle,'bundle_manifest',side_effect=packed),\
             patch.object(cli,'active_modules',return_value=(None,None,None,{},{})),\
             patch.object(cli,'charge',return_value=('owned-call','original-cycle')) as charge,\
             patch.object(cli.source_adapters,'invoke',side_effect=model) as invoke,\
             patch.object(sys,'argv',args),contextlib.redirect_stdout(io.StringIO()):
            code=cli.main()
        records=list((self.runtime/'worker/feature-audits').glob('*/result.json'))
        self.assertEqual(len(records),1)
        return code,json.loads(records[0].read_bytes()),charge.call_count,invoke.call_count

    def test_source_review_uses_delta_packet_and_retains_actual_usage_evidence(self):
        code,record,charged,calls=self.invoke()
        self.assertEqual((code,charged,calls),(0,1,1))
        self.assertEqual(record['review_scope'],'DELTA_WITH_CONTEXT')
        self.assertEqual(record['evidence']['token_usage']['metrics']['input_tokens'],4)

    def test_needs_context_is_deferred_and_never_pass(self):
        code,record,charged,calls=self.invoke(verdict='NEEDS_CONTEXT')
        self.assertEqual((code,charged,calls),(2,1,1))
        self.assertEqual(record['status'],'DEFERRED_NEEDS_CONTEXT')
        self.assertEqual(record['verdict'],'NEEDS_CONTEXT')

    def test_changed_package_after_invocation_rejects_model_pass(self):
        code,record,charged,calls=self.invoke(tamper=True)
        self.assertEqual((code,charged,calls),(2,1,1))
        self.assertEqual(record['verdict'],'REWORK')

    def test_preflight_missing_context_does_not_charge_or_invoke(self):
        code,record,charged,calls=self.invoke(extra=['--include','missing.py'])
        self.assertEqual((code,charged,calls),(2,0,0))
        self.assertEqual(record['status'],'BLOCKED_REVIEW_CONTEXT_FILE_UNKNOWN')


if __name__=='__main__':unittest.main()
