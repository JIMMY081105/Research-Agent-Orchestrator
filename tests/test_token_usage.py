"""Usage is numeric provider evidence, not prompt size, a model claim or a guessed zero."""
import json
from pathlib import Path
import tempfile
import sqlite3
import unittest
import uuid
from unittest.mock import Mock,patch
from researchops import adapters,token_usage as u
from tools.token_usage import summarize


class UsageTests(unittest.TestCase):
    def test_claude_counts_and_per_model_are_separate(self):
        value=u.claude_usage({'usage':{'input_tokens':11,'output_tokens':7,'cache_read_input_tokens':300,'cache_creation_input_tokens':20},
            'modelUsage':{'claude-opus-5-5':{'inputTokens':11,'outputTokens':7,'cacheReadInputTokens':300}}})
        self.assertEqual(value['metrics'],dict(input_tokens=11,output_tokens=7,cache_read_input_tokens=300,cache_creation_input_tokens=20))
        self.assertEqual(value['models'][0]['metrics']['input_tokens'],11)
        self.assertFalse(value['estimated'])

    def test_missing_is_unavailable_but_explicit_zero_is_reported(self):
        self.assertEqual(u.claude_usage({})['status'],'UNAVAILABLE')
        self.assertEqual(u.claude_usage({'usage':{'input_tokens':0}})['status'],'REPORTED')
        self.assertEqual(u.claude_usage({})['metrics'],{})

    def test_negative_bool_nan_or_text_never_become_token_counts(self):
        for bad in (-1,True,float('nan'),'1200',2**80):
            with self.subTest(value=bad):self.assertEqual(u.claude_usage({'usage':{'input_tokens':bad}})['metrics'],{})

    def test_unknown_keys_and_reasoning_prose_are_not_retained(self):
        marker='FAKE-SECRET-MUST-NOT-RETAIN'
        value=u.claude_usage({'usage':{'input_tokens':3,'reasoning':marker,'api_key':marker},
            'modelUsage':{marker:{'inputTokens':3},'claude-test':{'inputTokens':2,'reasoning':marker}}})
        self.assertNotIn(marker,json.dumps(value))
        self.assertEqual(value['models'],[{'model':'claude-test','metrics':{'input_tokens':2}}])

    def test_codex_reads_only_completion_usage_not_agent_text(self):
        events=[{'type':'item.completed','item':{'type':'agent_message','text':'{"usage":{"input_tokens":99999}}'}},
                {'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':60,'output_tokens':5}},
                {'type':'turn.completed','usage':{'input_tokens':20,'cached_input_tokens':10,'output_tokens':2}}]
        value=u.from_output('codex','\n'.join(json.dumps(v) for v in events))
        self.assertEqual(value['metrics'],dict(input_tokens=120,cache_read_input_tokens=70,output_tokens=7))

    def test_app_server_total_is_cumulative_not_last_request(self):
        value=u.app_server_usage({'tokenUsage':{'total':{'inputTokens':800,'outputTokens':50,'cachedInputTokens':500,'cacheWriteInputTokens':4},
                                             'last':{'inputTokens':2,'outputTokens':1}}})
        self.assertEqual(value['scope'],'THREAD_CUMULATIVE')
        self.assertEqual(value['metrics']['input_tokens'],800)
        self.assertEqual(value['metrics']['cache_creation_input_tokens'],4)

    def test_failed_cli_still_retains_reported_usage_without_raw_output(self):
        session=str(uuid.uuid4());envelope={'is_error':True,'result':"You've hit your session limit",'usage':{'input_tokens':4,'output_tokens':3},'hidden':'FAKE-SECRET'}
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/'schema.json';path.write_text('{}')
            with patch.object(adapters.winproc,'run_owned',return_value=(1,json.dumps(envelope),'',.01)):
                with self.assertRaises(adapters.CallError) as failed:
                    adapters.invoke('claude',{'claude':'mock.exe'},{'timeout_seconds':1,'memory_mb':256},'safe',path,Path(name),lambda *a:None,session)
        self.assertEqual(failed.exception.kind,'QUOTA')
        self.assertEqual(failed.exception.evidence['token_usage']['metrics'],dict(input_tokens=4,output_tokens=3))
        self.assertNotIn('FAKE-SECRET',json.dumps(failed.exception.evidence))

    def test_success_cli_evidence_survives_sanitization(self):
        session=str(uuid.uuid4());envelope={'subtype':'success','is_error':False,'session_id':session,'structured_output':{'ok':True},'usage':{'input_tokens':0,'output_tokens':8}}
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/'schema.json';path.write_text('{}')
            with patch.object(adapters.winproc,'run_owned',return_value=(0,json.dumps(envelope),'',.01)):
                value,evidence=adapters.invoke('claude',{'claude':'mock.exe'},{'timeout_seconds':1,'memory_mb':256},'safe',path,Path(name),lambda *a:None,session)
        self.assertEqual(value,{'ok':True})
        self.assertEqual(adapters.safe_evidence(evidence)['token_usage']['metrics']['output_tokens'],8)

    def test_summary_deduplicates_calls_and_keeps_unknown_history(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            usage=u.claude_usage({'usage':{'input_tokens':10,'output_tokens':3},'modelUsage':{'claude-test':{'inputTokens':10}}})
            for folder,file,record in [('one','result.json',{'call_id':'same','evidence':{'token_usage':usage}}),
                                       ('two','failure.json',{'call_id':'same','evidence':{'token_usage':usage}}),
                                       ('three','result.json',{'call_id':'historic','evidence':{}})]:
                dest=root/folder;dest.mkdir();(dest/file).write_text(json.dumps(record))
            report=summarize(root)
            self.assertEqual(report['records'],2);self.assertEqual(report['unknown_records'],1)
            self.assertEqual(report['reported_call_totals'],dict(input_tokens=10,output_tokens=3))

    def test_repeated_native_thread_snapshots_are_not_added_to_totals(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            for i,n in enumerate((10,20,20)):
                dest=root/str(i);dest.mkdir();usage=u.app_server_usage({'tokenUsage':{'total':{'inputTokens':n}}})
                (dest/'token-usage.json').write_text(json.dumps({'call_id':str(i),'thread_id':'owned-thread','token_usage':usage}))
            report=summarize(root)
            self.assertEqual(report['reported_call_totals'],{})
            self.assertEqual(report['thread_cumulative'],[{'thread':'owned-thread','metrics':{'input_tokens':20}}])

    def test_report_uses_real_ledger_and_ignores_unregistered_mock_evidence(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            with sqlite3.connect(root/'queue.sqlite3') as db:
                db.executescript('CREATE TABLE calls(id TEXT);CREATE TABLE call_engines(call TEXT,engine TEXT);')
                db.execute('INSERT INTO calls VALUES(?)',('real',));db.execute('INSERT INTO call_engines VALUES(?,?)',('real','codex'))
                db.execute('INSERT INTO calls VALUES(?)',('old',));db.execute('INSERT INTO call_engines VALUES(?,?)',('old','claude'))
            db.close()
            for ident,n in (('real',10),('fake-test-fixture',100000)):
                dest=root/ident;dest.mkdir();(dest/'result.json').write_text(json.dumps(dict(call_id=ident,evidence={'token_usage':u.codex_usage([{'type':'turn.completed','usage':{'input_tokens':n}}])})))
            report=summarize(root)
            self.assertEqual(report['reported_call_totals']['input_tokens'],10)
            self.assertEqual(report['unknown_records'],1)
            self.assertEqual(report['ledger_binding'],'CALL_ID_VERIFIED')

    def test_owned_native_notification_is_saved_but_foreign_turn_is_ignored(self):
        from researchops.worker_service import Service
        with tempfile.TemporaryDirectory() as name:
            service=Service(Path(name),'a'*64,reviewer=Mock())
            turn=dict(id=str(uuid.uuid4()),session=str(uuid.uuid4()),thread='owned',native_turn='native',call_id=str(uuid.uuid4()))
            service.active_turn=turn
            params=dict(threadId='foreign',turnId='native',tokenUsage={'total':{'inputTokens':99}})
            service.handle(dict(method='thread/tokenUsage/updated',params=params))
            path=Path(name)/'worker/turns'/turn['id']/'token-usage.json';self.assertFalse(path.exists())
            params['threadId']='owned';service.handle(dict(method='thread/tokenUsage/updated',params=params))
            self.assertEqual(json.loads(path.read_bytes())['token_usage']['metrics']['input_tokens'],99)
            self.assertEqual(json.loads(path.read_bytes())['call_id'],turn['call_id'])


if __name__=='__main__':unittest.main()
