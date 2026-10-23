"""Recovery never replays ambiguous work; native permissions and replies remain turn-scoped."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from contextlib import nullcontext
from unittest.mock import Mock, patch
from researchops.worker_service import Service
from researchops.worker_store import OWNER, WorkerError, save, utc
from researchops import winproc


class WorkerServiceTests(unittest.TestCase):
    def test_actual_windows_status_read_lock_cannot_stop_owned_worker(self):
        import ctypes as C
        from ctypes import wintypes as W
        self.service.heartbeat();path=self.store.runtime/'service.json';old=path.read_bytes()
        kernel=C.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,C.c_void_p,W.DWORD,W.DWORD,W.HANDLE];kernel.CreateFileW.restype=W.HANDLE
        kernel.CloseHandle.argtypes=[W.HANDLE]
        handle=kernel.CreateFileW(str(path),0x80000000,3,None,3,0,None)
        self.assertNotEqual(handle,C.c_void_p(-1).value)
        try:
            self.service.last_heartbeat=0
            self.assertFalse(self.service.heartbeat())
            self.assertEqual(path.read_bytes(),old);self.assertEqual(self.service.last_heartbeat,0)
            self.assertEqual(self.service.heartbeat_write_failures,1);self.service.rpc.close.assert_not_called()
        finally:kernel.CloseHandle(handle)
        self.assertTrue(self.service.heartbeat())
        self.assertEqual(json.loads(path.read_bytes())['heartbeat_write_failures'],1)

    def test_unknown_status_write_error_is_not_silenced(self):
        with patch('researchops.worker_service.save',side_effect=OSError('disk error')):
            with self.assertRaises(OSError):self.service.heartbeat()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.review = Mock(return_value={'verdict': 'PASS'})
        self.service = Service(self.root, 'a' * 64, reviewer=self.review)
        self.service.rpc = Mock()
        self.store = self.service.store
        self.cap = patch.object(self.store, 'capability', return_value={'enabled': True, 'skills': [], 'default_model': 'test'})
        self.cap.start(); self.addCleanup(self.cap.stop)

    def turn(self, mode='approval', session=None):
        request = {'id': str(uuid.uuid4()), 'session': session, 'prompt': 'Write a safe marker.', 'mode': mode, 'effort': 'high', 'skills': []}
        self.store.submit(request)
        return self.service.next_turn()

    def begin(self, turn):
        self.service.rpc.call.side_effect = [
            {'thread': {'id': 'owned'}, 'model': turn['model'], 'approvalPolicy': 'never' if turn['mode'] == 'full' else 'untrusted',
             'sandbox': {'type': 'dangerFullAccess' if turn['mode'] == 'full' else 'workspaceWrite'}},
            {'turn': {'id': 'native'}}]
        with patch('researchops.worker_service.charge', return_value='call'):
            self.service.begin(turn)

    def test_actual_native_turn_gets_requested_policy_and_explicit_owned_session(self):
        turn = self.turn('full'); self.begin(turn)
        calls = self.service.rpc.call.call_args_list
        self.assertEqual(calls[-1].args[0], 'turn/start')
        self.assertEqual(calls[-1].args[1]['sandboxPolicy'], {'type': 'dangerFullAccess'})
        self.assertEqual(calls[-1].args[1]['approvalPolicy'], 'never')
        self.assertEqual(calls[-1].args[1]['threadId'], 'owned')
        self.assertEqual(calls[-1].args[1]['model'],turn['model'])
        self.assertNotIn('resume-last',str(calls))

    def test_fast_plan_parameters_are_native_and_plan_is_read_only(self):
        turn=self.turn('full');turn.update(work_mode='plan',service_tier='priority')
        self.service.rpc.call.side_effect=[{'thread':{'id':'owned'},'model':turn['model'],'approvalPolicy':'untrusted','sandbox':{'type':'readOnly'}},{'turn':{'id':'native'}}]
        with patch('researchops.worker_service.charge',return_value='call'):self.service.begin(turn)
        params=self.service.rpc.call.call_args.args[1]
        self.assertEqual(params['serviceTier'],'priority');self.assertEqual(params['collaborationMode']['mode'],'plan')
        self.assertIsNone(params['collaborationMode']['settings']['developer_instructions'])
        self.assertEqual(params['sandboxPolicy'],{'type':'readOnly'})
        self.service.handle({'method':'item/plan/delta','params':{'threadId':'owned','turnId':'native','itemId':'plan','delta':'1. Check inputs'}})
        self.service.handle({'method':'item/completed','params':{'threadId':'owned','turnId':'native','item':{'id':'plan','type':'plan','text':'1. Check inputs\n2. Verify sum\n3. Report'}}})
        self.assertEqual(self.service.review_response(),'1. Check inputs\n2. Verify sum\n3. Report')

    def test_goal_uses_persisted_native_contract_without_resetting_budget(self):
        turn=self.turn('full');turn.update(work_mode='goal',goal_objective='Keep exact accounting',service_tier='priority')
        current={'objective':'Keep exact accounting','status':'paused','tokensUsed':900,'tokenBudget':1000}
        self.service.rpc.call.side_effect=[{'thread':{'id':'owned'},'model':turn['model'],'approvalPolicy':'never','sandbox':{'type':'dangerFullAccess'}},{'goal':current},{'goal':{**current,'status':'active'}},{'turn':{'id':'native'}}]
        with patch('researchops.worker_service.charge',return_value='call'):self.service.begin(turn)
        params=self.service.rpc.call.call_args_list[2].args[1]
        self.assertNotIn('objective',params);self.assertNotIn('tokenBudget',params)
        turn['tool_items']=set()
        self.service.rpc.call.side_effect=[{'goal':{**current,'status':'active'}},{'goal':current}]
        self.service.handle({'method':'turn/completed','params':{'threadId':'owned','turn':{'id':'native','status':'completed'}}})
        self.assertEqual(len(self.store.status()['turns']),1)
        state=json.loads((self.store.runtime/'goals'/turn['session']/'state.json').read_text())
        self.assertEqual(state['tokensUsed'],900);self.assertEqual(state['host_wait'],'NO_ACTION_CONTINUATION_SUPPRESSED')

    def test_productive_goal_continues_only_after_review_and_pause_suppresses_next_dispatch(self):
        self.store.capability.return_value.update(work_modes=['task','goal'])
        for paused in (False,True,'admission','busy'):
            with self.subTest(paused=paused):
                self.store.capability.return_value['enabled']=True
                request={'id':str(uuid.uuid4()),'session':None,'prompt':'Bounded goal stage','mode':'full','effort':'high','skills':[],'work_mode':'goal','goal_objective':'Original objective'}
                self.store.submit(request);turn=self.service.next_turn()
                goal={'objective':'Original objective','status':'active','tokensUsed':100}
                self.service.rpc.call.side_effect=[{'thread':{'id':'owned'},'model':'test','approvalPolicy':'never','sandbox':{'type':'dangerFullAccess'}},{'goal':None},{'goal':goal},{'turn':{'id':'native'}}]
                with patch('researchops.worker_service.charge',return_value='call'):self.service.begin(turn)
                turn['tool_items']={'actual-command'}
                if paused is True:save(self.store.runtime/'goals'/turn['session']/'pause-request.json',{'owner':OWNER})
                if paused=='admission':self.store.capability.return_value['enabled']=False
                self.service.rpc.call.side_effect=[{'goal':goal},{'goal':{**goal,'status':'paused'}}]
                def review(*args):
                    self.assertEqual(self.store.status(turn['session'])['goal']['status'],'paused')
                    self.assertIsNone(self.service.next_turn());return {'verdict':'PASS'}
                self.service.reviewer=review
                with patch.object(self.store,'submit',side_effect=WorkerError('WORKER_BUSY_FINISH_OR_ANSWER_CURRENT_TURN')) if paused=='busy' else nullcontext():
                    self.service.handle({'method':'turn/completed','params':{'threadId':'owned','turn':{'id':'native','status':'completed'}}})
                next_turn=self.service.next_turn()
                if paused:
                    self.assertIsNone(next_turn)
                    self.assertEqual(self.store.status(turn['session'])['turns'][0]['state'],'REVIEW_PASS')
                    self.assertEqual(self.store.status(turn['session'])['goal']['host_wait'],'ADMISSION_PAUSED' if paused=='admission' else 'DISPATCH_PAUSED_WORKER_BUSY_FINISH_OR_ANSWER_CURRENT_TURN' if paused=='busy' else 'USER_PAUSED')
                else:
                    self.assertEqual(next_turn['session'],turn['session']);self.assertEqual(next_turn['goal_objective'],'Original objective');self.assertEqual(next_turn['work_mode'],'goal')
                    self.store.update(next_turn['id'],state='CANCELLED')

    def test_native_policy_mismatch_blocks_before_model(self):
        turn = self.turn()
        self.service.rpc.call.return_value = {'sandbox': {'type': 'dangerFullAccess'}, 'approvalPolicy': 'never'}
        with self.assertRaisesRegex(WorkerError, 'MODE_MISMATCH'), patch('researchops.worker_service.charge') as charged:
            self.service.begin(turn)
        charged.assert_not_called()

    def test_exact_native_denial_sent_once_not_changed_by_next_mode(self):
        turn = self.turn(); self.begin(turn)
        self.service.handle({'id': 91, 'method': 'item/commandExecution/requestApproval',
            'params': {'threadId': 'owned', 'turnId': 'native', 'command': 'write marker'}})
        aid = self.store.status()['approvals'][0]['id']
        self.store.decide({'id': aid, 'turn': turn['id'], 'decision': 'decline'})
        self.service.answer(); self.service.answer()
        self.service.rpc.respond.assert_called_once_with(91, {'decision': 'decline'})

    def test_parallel_approvals_stay_answerable_until_all_are_resolved(self):
        turn = self.turn(); self.begin(turn)
        for rpc_id in (91, 92):
            self.service.handle({'id':rpc_id,'method':'item/commandExecution/requestApproval',
                'params':{'threadId':'owned','turnId':'native','command':'read own files'}})
        approvals=self.store.status()['approvals']
        self.store.decide({'id':approvals[0]['id'],'turn':turn['id'],'decision':'accept'})
        self.service.answer()
        self.assertEqual(self.store.status()['turns'][0]['state'],'WAITING_APPROVAL')
        self.assertEqual(len(self.store.status()['approvals']),1)
        self.store.decide({'id':approvals[1]['id'],'turn':turn['id'],'decision':'decline'})
        self.service.answer();self.service.answer()
        self.assertEqual(self.store.status()['turns'][0]['state'],'RUNNING')
        self.assertEqual(self.service.rpc.respond.call_count,2)

    def test_parallel_user_question_stays_waiting_after_command_reply(self):
        turn=self.turn();self.begin(turn)
        self.service.handle({'id':91,'method':'item/commandExecution/requestApproval',
            'params':{'threadId':'owned','turnId':'native','command':'read own files'}})
        self.service.handle({'id':92,'method':'item/tool/requestUserInput',
            'params':{'threadId':'owned','turnId':'native','questions':[{'id':'scope','question':'Which scope?'}]}})
        command=next(a for a in self.store.status()['approvals'] if a['method']=='item/commandExecution/requestApproval')
        self.store.decide({'id':command['id'],'turn':turn['id'],'decision':'accept'})
        self.service.answer()
        self.assertEqual(self.store.status()['turns'][0]['state'],'WAITING_INPUT')
        question=self.store.status()['approvals'][0]
        with self.assertRaisesRegex(WorkerError,'USER_INPUT_REQUIRES_TEXT_REPLY'):
            self.store.decide({'id':question['id'],'turn':turn['id'],'decision':'accept'})

    def test_foreign_events_cannot_complete_or_request_owned_approval(self):
        turn = self.turn(); self.begin(turn)
        self.service.handle({'method': 'turn/completed', 'params': {'threadId': 'foreign', 'turn': {'id': 'native', 'status': 'completed'}}})
        self.assertIsNotNone(self.service.active_turn); self.review.assert_not_called()

    def test_completed_runs_independent_reviewer_not_model_claim(self):
        turn = self.turn(); self.begin(turn)
        self.review.return_value = {'verdict': 'REWORK'}
        self.service.handle({'method': 'item/agentMessage/delta', 'params': {'threadId': 'owned', 'turnId': 'native', 'delta': 'I passed!'}})
        self.service.handle({'method': 'turn/completed', 'params': {'threadId': 'owned', 'turn': {'id': 'native', 'status': 'completed'}}})
        self.assertEqual(self.store.status()['turns'][0]['state'], 'NEEDS_REWORK')
        self.review.assert_called_once(); self.assertIsNone(self.service.active_turn)

    def test_recovery_live_or_unknown_process_refuses_and_never_replays(self):
        turn = self.turn(); self.store.update(turn['id'], state='RUNNING')
        save(self.root / 'worker/process.json', {'owner': OWNER, 'pid': os.getpid(), 'birth': winproc.identity(os.getpid())})
        for identity in (winproc.identity(os.getpid()), 'UNKNOWN'):
            with patch('researchops.worker_service.winproc.identity', return_value=identity), self.assertRaisesRegex(WorkerError, 'STILL_LIVE_OR_UNKNOWN'):
                self.service.recover()
        with patch('researchops.worker_service.winproc.identity', return_value=None): self.service.recover()
        self.assertEqual(self.store.status()['turns'][0]['state'], 'INTERRUPTED_NEEDS_RECONCILIATION')
        self.assertIsNone(self.service.next_turn())

    def test_explicit_final_answer_is_reviewed_and_public_commentary_preserved(self):
        turn=self.turn();self.begin(turn)
        for ident,phase,text in [('c','commentary','Checking the files'),('f','final_answer','Actual result')]:
            self.service.handle({'method':'item/completed','params':{'threadId':'owned','turnId':'native',
                'item':{'type':'agentMessage','id':ident,'phase':phase,'text':text}}})
        self.service.handle({'method':'turn/completed','params':{'threadId':'owned','turn':{'id':'native','status':'completed'}}})
        self.assertEqual(self.review.call_args.args[2]['response'],'Actual result')
        attempt=self.store.runtime/'turns'/turn['id']/'attempts'/'0'
        messages=json.loads((attempt/'public-messages.json').read_text())['messages']
        self.assertEqual([m['text'] for m in messages],['Checking the files','Actual result'])

    def test_unknown_message_phase_retains_legacy_context_even_with_explicit_final(self):
        self.service.message_text={'c':'known interim','u':'unknown phase','f':'final'}
        self.service.message_phases={'c':'commentary','u':None,'f':'final_answer'}
        self.assertEqual(self.service.review_response(),'unknown phase\nfinal')
        self.service.message_phases['f']=None
        self.assertEqual(self.service.review_response(),'known interim\nunknown phase\nfinal')

    def test_failed_native_turn_expires_approval_without_review(self):
        turn = self.turn(); self.begin(turn)
        self.service.handle({'id': 3, 'method': 'item/fileChange/requestApproval', 'params': {'threadId': 'owned', 'turnId': 'native'}})
        self.service.handle({'method': 'turn/completed', 'params': {'threadId': 'owned', 'turn': {'id': 'native', 'status': 'failed'}}})
        self.assertEqual(self.store.status()['approvals'], [])
        self.assertEqual(self.store.status()['turns'][0]['state'], 'PAUSED_MODEL_ERROR')
        self.review.assert_not_called()

    def test_workspace_content_change_invalidates_review_binding(self):
        from researchops.worker_review import workspace_snapshot
        folder = self.root / 'artifact'; folder.mkdir()
        (folder / 'source.py').write_text('value=1')
        a = workspace_snapshot(folder)['sha256']
        (folder / 'source.py').write_text('value=2')
        self.assertNotEqual(a, workspace_snapshot(folder)['sha256'])
        secret = folder / 'secret.txt'; secret.write_text('sk-' + 'x' * 30)
        with self.assertRaisesRegex(WorkerError, 'SENSITIVE'): workspace_snapshot(folder)

    def test_external_network_failure_pauses_without_review_or_retry(self):
        turn = self.turn(); self.begin(turn)
        with self.assertRaisesRegex(WorkerError, 'PAUSED_NETWORK'):
            self.service.handle({'method': 'turn/completed', 'params': {'threadId': 'owned',
                'turn': {'id': 'native', 'status': 'failed', 'error': {'message': 'Network connection failed'}}}})
        self.review.assert_not_called(); self.assertIsNone(self.service.active_turn)
        self.assertEqual(self.store.status()['turns'][0]['reason'], 'NETWORK')

    def test_pause_retains_queued_work_and_idle_stop_does_not_start_it(self):
        turn = self.turn()
        save(self.root / 'worker/admission-paused.json', {'owner': OWNER})
        self.service.rpc.drain.return_value = []
        self.service.tick()
        self.service.rpc.call.assert_not_called()
        self.assertEqual(self.store.status()['turns'][0]['state'], 'QUEUED')
        save(self.root / 'worker/stop-when-idle.json', {'owner': OWNER})
        self.service.tick(); self.assertTrue(self.service.stop.is_set())
        self.service.rpc.call.assert_not_called()

    def test_resumed_thread_and_each_new_turn_keep_explicit_available_model(self):
        turn = self.turn(); self.begin(turn)
        self.store.update(turn['id'], state='REVIEW_PASS')
        following = self.turn('approval', turn['session'])
        self.service.rpc.call.reset_mock(); self.begin(following)
        calls = self.service.rpc.call.call_args_list
        self.assertEqual(calls[0].args[0], 'thread/resume')
        self.assertEqual(calls[0].args[1]['model'], following['model'])
        self.assertEqual(calls[-1].args[1]['model'], following['model'])
        self.assertEqual(calls[-1].args[1]['approvalPolicy'], 'untrusted')

    def test_unavailable_stored_model_cannot_silently_fallback_or_charge(self):
        turn = self.turn(); self.service.models = ['another-model']
        with self.assertRaisesRegex(WorkerError, 'NO_LONGER_AVAILABLE'), patch('researchops.worker_service.charge') as charged:
            self.service.begin(turn)
        self.service.rpc.call.assert_not_called(); charged.assert_not_called()
        self.assertEqual(self.store.status()['turns'][0]['state'], 'QUEUED')

    def test_timeout_interrupt_ack_keeps_writer_gate_until_matching_native_completion(self):
        turn=self.turn();self.begin(turn)
        self.service.rpc.call.side_effect=None;self.service.rpc.call.return_value={}
        self.service.rpc.call.reset_mock();self.service.rpc.drain.return_value=[]
        turn['running_seconds']=3601
        self.service.tick()
        self.assertEqual(self.store.status()['turns'][0]['state'],'CANCELLING')
        self.assertIs(self.service.active_turn,turn)
        with self.assertRaisesRegex(WorkerError,'WORKER_BUSY'):
            self.turn(session=turn['session'])
        self.service.tick()
        self.service.rpc.call.assert_called_once_with('turn/interrupt',{'threadId':'owned','turnId':'native'})
        self.service.handle({'method':'turn/completed','params':{'threadId':'foreign','turn':{'id':'native','status':'interrupted'}}})
        self.assertIs(self.service.active_turn,turn)
        self.service.handle({'method':'turn/completed','params':{'threadId':'owned','turn':{'id':'native','status':'interrupted'}}})
        self.assertIsNone(self.service.active_turn)
        self.assertEqual(self.store.status()['turns'][0]['state'],'INTERRUPTED')
        self.review.assert_not_called()
        self.assertEqual(self.turn(session=turn['session'])['state'],'QUEUED')

    def test_user_cancel_and_timeout_same_tick_send_only_one_interrupt(self):
        turn=self.turn();self.begin(turn)
        self.service.rpc.call.side_effect=None;self.service.rpc.call.return_value={}
        self.service.rpc.call.reset_mock();self.service.rpc.drain.return_value=[]
        turn['running_seconds']=3601
        self.store.update(turn['id'],cancel_requested=1)
        self.service.tick();self.service.tick()
        self.assertEqual(self.service.rpc.call.call_count,1)
        self.assertEqual(self.store.status()['turns'][0]['state'],'CANCELLING')
        self.assertIs(self.service.active_turn,turn)

    def test_native_terminal_waits_for_all_actual_writer_exit_notifications(self):
        turn=self.turn();self.begin(turn)
        self.service.rpc.call.side_effect=None;self.service.rpc.call.return_value={}
        self.service.rpc.call.reset_mock();self.service.rpc.drain.return_value=[]
        for kind in ('commandExecution','fileChange'):
            self.service.handle({'method':'item/started','params':{'threadId':'owned','turnId':'native',
                'item':{'type':kind,'id':'same-id','status':'inProgress'}}})
        self.service.handle({'method':'turn/completed','params':{'threadId':'owned','turn':{'id':'native','status':'interrupted'}}})
        self.assertEqual(self.store.status()['turns'][0]['state'],'WAITING_TOOL_EXIT')
        with self.assertRaisesRegex(WorkerError,'WORKER_BUSY'):self.turn(session=turn['session'])
        self.store.cancel({'id':turn['id']});self.service.tick()
        self.service.rpc.call.assert_not_called()
        self.service.handle({'method':'item/completed','params':{'threadId':'foreign','turnId':'native',
            'item':{'type':'commandExecution','id':'same-id','status':'completed'}}})
        self.assertEqual(len(self.service.active_writers),2)
        for kind in ('commandExecution','fileChange'):
            self.service.handle({'method':'item/completed','params':{'threadId':'owned','turnId':'native',
                'item':{'type':kind,'id':'same-id','status':'completed'}}})
            if kind=='commandExecution':self.assertEqual(self.store.status()['turns'][0]['state'],'WAITING_TOOL_EXIT')
        self.assertEqual(self.store.status()['turns'][0]['state'],'INTERRUPTED')
        self.assertIsNone(self.service.active_turn);self.review.assert_not_called()

    def test_writer_without_stable_native_identity_fails_closed(self):
        turn=self.turn();self.begin(turn)
        with self.assertRaisesRegex(WorkerError,'NATIVE_WRITER_ID_MISSING'):
            self.service.handle({'method':'item/started','params':{'threadId':'owned','turnId':'native',
                'item':{'type':'commandExecution','status':'inProgress'}}})
        self.assertIs(self.service.active_turn,turn)
        with self.assertRaisesRegex(WorkerError,'NATIVE_WRITER_SCOPE_MISSING'):
            self.service.handle({'method':'item/started','params':{'threadId':'owned',
                'item':{'type':'commandExecution','id':'command','status':'inProgress'}}})
        self.assertIs(self.service.active_turn,turn)

    def test_recovery_marks_waiting_tool_exit_for_reconciliation_not_replay(self):
        turn=self.turn();self.store.update(turn['id'],state='WAITING_TOOL_EXIT')
        self.service.recover()
        self.assertEqual(self.store.status()['turns'][0]['state'],'INTERRUPTED_NEEDS_RECONCILIATION')
        self.assertIsNone(self.service.next_turn())


if __name__ == '__main__': unittest.main()
