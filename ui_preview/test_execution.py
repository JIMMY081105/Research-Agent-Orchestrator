"""The UI must submit exactly one bound turn, escape output and reject forged actions."""
import unittest
from unittest.mock import patch
import app


class ExecutionUITests(unittest.TestCase):
    def setUp(self):self.client=app.create_app().test_client()
    def test_execute_requires_nonce_even_for_local_origin(self):
        self.assertEqual(self.client.post('/execute',data={'prompt':'hello'},headers={'Origin':'http://localhost'}).status_code,403)
    def test_unavailable_worker_keeps_submit_disabled(self):
        with patch('execution.capability',return_value={'enabled':False}):
            page=self.client.get('/').get_data(as_text=True)
        self.assertIn('提交真实任务" disabled',page)
    def test_external_mutation_origin_rejected(self):
        for path in ['/execute','/execution/decision','/execution/cancel']:
            self.assertEqual(self.client.post(path,headers={'Origin':'https://outside.invalid'}).status_code,403)
    def test_submit_uses_server_session_and_escapes_response(self):
        with self.client.session_transaction() as s:s['csrf']='test-nonce';s['request_ids']=['test-id']
        status={'turns':[{'id':'x','prompt':'<script>','state':'REVIEW_PASS','reason':None,'response':'<img src=x>','reworks':0}], 'events':[],'approvals':[],'review_summary':None}
        with patch('execution.submit',return_value={'id':'x','session':'owned'}),patch('execution.status',return_value=status):
            result=self.client.post('/execute',data={'csrf':'test-nonce','request_id':'test-id','prompt':'hello'},headers={'Origin':'http://localhost'})
        self.assertEqual(result.status_code,200);self.assertNotIn(b'<img',result.data);self.assertIn(b'&lt;img',result.data)
        with self.client.session_transaction() as s:self.assertEqual(s['worker_session'],'owned')
    def test_status_of_unowned_session_is_denied_without_backend_read(self):
        with patch('execution.status') as status:
            for path in ['/execution/status/foreign','/execution/progress/foreign']:
                self.assertEqual(self.client.get(path).status_code,403)
            status.assert_not_called()
    def test_forged_request_id_is_not_submitted(self):
        with self.client.session_transaction() as s:s['csrf']='nonce';s['request_ids']=['owned-id']
        with patch('execution.submit') as submit:
            self.assertEqual(self.client.post('/execute',data={'csrf':'nonce','request_id':'foreign'},headers={'Origin':'http://localhost'}).status_code,403)
            submit.assert_not_called()

    def test_owned_task_restores_after_prompt_progress_navigation_even_if_paused(self):
        with self.client.session_transaction() as s:
            s['worker_session']='owned';s['owned_worker_sessions']=['owned']
        with patch('execution.capability',return_value={'enabled':False}),patch('execution.submit') as submit,patch('execution.store') as store:
            for path in ('/view/prompt','/?page=prompt'):
                page=self.client.get(path).get_data(as_text=True)
                self.assertIn('hx-get="/execution/status/owned"',page)
                self.assertIn('hx-trigger="load"',page)
            page=self.client.get('/view/progress').get_data(as_text=True)
            self.assertIn('hx-get="/execution/progress/owned"',page)
            submit.assert_not_called();store.assert_not_called()

    def test_restored_approval_is_visible_without_deciding_or_resubmitting(self):
        with self.client.session_transaction() as s:s['owned_worker_sessions']=['owned']
        status={'turns':[{'id':'turn','prompt':'test','state':'WAITING_APPROVAL','response':'waiting','reworks':0}],
                'events':[],'approvals':[{'id':'approval','turn':'turn','method':'item/commandExecution/requestApproval','params':{'command':'read files'}}], 'review_summary':None}
        with patch('execution.status',return_value=status),patch('execution.capability',return_value={'enabled':False}),patch('execution.store') as store,patch('execution.submit') as submit:
            page=self.client.get('/execution/status/owned').get_data(as_text=True)
            self.assertIn('WAITING_APPROVAL',page);self.assertIn('允许这一次',page)
            self.assertIn('name="id" value="approval"',page)
            self.assertIn('/execution/decision',page)
            store.assert_not_called();submit.assert_not_called()

    def test_new_chat_does_not_restore_or_cancel_previous_task(self):
        with self.client.session_transaction() as s:
            s['worker_session']='owned';s['owned_worker_sessions']=['owned']
        with patch('execution.capability',return_value={'enabled':False}),patch('execution.store') as store:
            page=self.client.get('/view/prompt?new=1').get_data(as_text=True)
            self.assertNotIn('/execution/status/owned',page);store.assert_not_called()
        with self.client.session_transaction() as s:
            self.assertNotIn('worker_session',s);self.assertIn('owned',s['owned_worker_sessions'])


if __name__=='__main__':unittest.main()
