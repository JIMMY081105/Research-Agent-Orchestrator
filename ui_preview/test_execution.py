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


if __name__=='__main__':unittest.main()
