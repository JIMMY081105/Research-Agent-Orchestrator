"""Additional audit service-wait tests. Defaults to production deployment module.
Use run_audit_wait_candidate.py to explicitly test the proposed overlay instead.
"""
from pathlib import Path
from unittest.mock import patch
import unittest
import test_continuous_review as continuous
from researchops import adapters, deployment, winproc
from researchops.integrity import read_json,write_json


class SourceAuditWaitTests(continuous.ContinuousReviewTests):
    def source_audit(self,evidence,cycle,fail=None):
        seen=[]
        def invoke(engine,machine,policy,prompt,schema,cwd,on_start,session,effort=None):
            seen.append(engine);on_start(self.dead_child,'1')
            if fail:raise adapters.CallError(fail)
            package=read_json(Path(cwd)/'package.json')
            return {'binding_sha256':package['binding_sha256'],'verdict':'PASS','issues':[]}, {'exit_code':0,'session_id':session}
        with patch.object(deployment,'verify_repo',return_value={}),patch.object(deployment.adapters,'invoke',invoke):
            value=deployment.independent_review(self.system,evidence,'claude',cycle)
        return value,seen

    def service_wait(self,kind='AUTH'):
        cycle=self.authorize_continuous();evidence=self.audit_evidence()
        with self.assertRaises(adapters.CallError) as failure:self.source_audit(evidence,cycle,kind)
        self.assertEqual(failure.exception.kind,kind)
        self.assertEqual(self.system.cycle(cycle)[1],'AUDIT_WAIT')
        return cycle,evidence

    def test_source_service_wait_explicit_resume_preserves_failed_evidence_and_charges(self):
        cycle,evidence=self.service_wait()
        record=self.system.cycle(cycle)[0];binding=record['binding']['package_binding']
        original=(self.runtime/'independent-review'/binding/'result.json').read_bytes()
        resumed=deployment.resume_source_audit(self.system,cycle,'User explicitly resumed this authenticated source review.')
        self.assertEqual(self.system.calls_today(),1)
        new_evidence=read_json(Path(resumed['tests']))
        self.assertTrue(new_evidence['success']);self.assertIn('audit_resume',new_evidence)
        self.assertEqual(self.source_audit(Path(resumed['tests']),cycle)[0]['status'],'PASS')
        self.assertEqual(self.system.calls_today(),2)
        self.assertEqual(self.system.cycle(cycle)[0]['used']['audit'],2)
        self.assertEqual((self.runtime/'independent-review'/binding/'result.json').read_bytes(),original)
        self.assertIsNone(self.system.meta('paused'))

    def test_source_service_resume_refuses_unknown_original_process(self):
        cycle,evidence=self.service_wait('NETWORK')
        with patch.object(winproc,'identity',return_value='UNKNOWN'):
            with self.assertRaises(ValueError):
                deployment.resume_source_audit(self.system,cycle,'Explicit network retry with uncertain old process.')
        self.assertEqual(self.system.cycle(cycle)[1],'AUDIT_WAIT')
        self.assertEqual(self.system.calls_today(),1)

    def test_source_service_resume_refuses_changed_source(self):
        cycle,evidence=self.service_wait('QUOTA');self.revise(777)
        with self.assertRaises(ValueError):
            deployment.resume_source_audit(self.system,cycle,'Explicit quota retry after this source has changed.')
        self.assertEqual(self.system.calls_today(),1)

    def test_source_service_resume_limit_is_bounded_without_refunding_audits(self):
        cycle,evidence=self.service_wait()
        for _ in range(self.system.policy['max_engine_resumes']):
            resumed=deployment.resume_source_audit(self.system,cycle,'Explicit bounded retry for this same service failure.')
            with self.assertRaises(adapters.CallError):self.source_audit(Path(resumed['tests']),cycle,'AUTH')
        with self.assertRaises(ValueError):
            deployment.resume_source_audit(self.system,cycle,'This attempted fourth resume must be refused.')
        self.assertEqual(self.system.calls_today(),4)
        self.assertEqual(self.system.cycle(cycle)[0]['audit_resume_count'],3)
        self.assertEqual(self.system.cycle(cycle)[1],'AUDIT_WAIT')

    def test_unchanged_source_with_only_new_test_timestamp_does_not_call_model(self):
        cycle=self.authorize_continuous();self.audit('REWORK',reviewer='claude',cycle=cycle)
        evidence=read_json(self.runtime/'tests.json');evidence['new_test_timestamp']='2040-01-01T00:00:00Z'
        path=self.runtime/'new-test-timestamp.json';write_json(path,evidence)
        before=self.system.calls_today()
        result,seen=self.source_audit(path,cycle)
        self.assertEqual(result['status'],'UNCHANGED_SOURCE')
        self.assertEqual(seen,[]);self.assertEqual(self.system.calls_today(),before)
        self.assertEqual(self.system.cycle(cycle)[1],'OPEN')

    def test_user_pause_after_first_rework_survives_second_pass(self):
        cycle=self.authorize_continuous();self.audit('REWORK',reviewer='claude',cycle=cycle)
        self.system.pause();self.revise(803)
        self.audit('PASS',reviewer='claude',cycle=cycle)
        self.assertEqual(self.system.meta('paused'),{'reason':'USER_PAUSED'})

    def test_user_pause_during_service_wait_survives_retry_pass(self):
        cycle,evidence=self.service_wait();self.system.pause()
        resumed=deployment.resume_source_audit(self.system,cycle,'Explicit service retry while dispatch stays user paused.')
        self.source_audit(Path(resumed['tests']),cycle)
        self.assertEqual(self.system.meta('paused'),{'reason':'USER_PAUSED'})


if __name__=='__main__':unittest.main(verbosity=2)
