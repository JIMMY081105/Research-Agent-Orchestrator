"""The UI must submit exactly one bound turn, escape output and reject forged actions."""
import unittest
from unittest.mock import patch
import app


class ExecutionUITests(unittest.TestCase):
    def setUp(self):
        application=app.create_app(testing=True);self.addCleanup(application.testing_history.cleanup);self.client=application.test_client()
    def test_publisher_identity_dependency_failure_disables_only_delivery(self):
        import execution,json,tempfile,hashlib,datetime as dt
        from pathlib import Path
        import builtins
        real_import=builtins.__import__
        with tempfile.TemporaryDirectory() as directory:
            rt=Path(directory);files={n:hashlib.sha256(b'').hexdigest() for n in ('delivery_agent.py','researchops/__init__.py','researchops/delivery_agent.py','tests/test_delivery_agent.py','tools/delivery.ps1','DELIVERY.md')}
            digest=hashlib.sha256(json.dumps(files,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            home=rt/'worker-delivery';source=home/'snapshots'/digest/'source'
            for name in files:
                p=source/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'')
            (source.parent/'manifest.json').write_text(json.dumps({'files':files}))
            (home/'activation.json').write_text(json.dumps({'owner':'BGV.Worker.ResultDelivery.v1','source':str(source),'sha256':digest}))
            (home/'service.json').write_text('{}')
            def failed_import(name,*args,**kwargs):
                if name=='researchops.dashboard_state':raise ImportError('missing identity dependency')
                return real_import(name,*args,**kwargs)
            with patch.object(execution,'RUNTIME',rt),patch('builtins.__import__',side_effect=failed_import):
                self.assertEqual(execution.delivery_capability(),{'enabled':False})

    def test_task_sidebar_restores_only_owned_session_and_survives_cookie_list_eviction(self):
        with self.client.session_transaction() as s:s['owned_worker_sessions']=['owned']
        with patch('execution.conversations',return_value=[{'id':'owned','title':'A task <script>','state':'RUNNING','model':'gpt-6.1-sol'}]):
            page=self.client.get('/tasks').get_data(as_text=True)
            self.assertIn('/view/progress?task=owned',page);self.assertNotIn('<script>',page)
        with self.client.session_transaction() as s:s['owned_worker_sessions']=[]
        self.assertEqual(self.client.get('/view/prompt?task=owned').status_code,200)
        with self.client.session_transaction() as s:self.assertEqual(s['worker_session'],'owned')
        self.assertEqual(self.client.get('/view/prompt?task=foreign').status_code,403)
        other=self.client.application.test_client()
        self.assertEqual(other.get('/view/prompt?task=owned').status_code,403)

    def test_visualization_is_owned_sandboxed_and_no_external_requests(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'chart.html';path.write_text('<script>fetch("http://localhost/execute")</script>')
            with self.client.session_transaction() as s:s['owned_worker_sessions']=['owned']
            with patch('execution.artifact',return_value=path):
                with self.client.get('/execution/artifact/owned/chart.html') as response:
                    self.assertIn("sandbox allow-scripts",response.headers['Content-Security-Policy'])
                    self.assertIn("connect-src 'none'",response.headers['Content-Security-Policy'])
                    self.assertNotIn('allow-same-origin',response.headers['Content-Security-Policy'])
            with patch('execution.artifact') as backend:
                self.assertEqual(self.client.get('/execution/artifact/foreign/chart.html').status_code,403);backend.assert_not_called()

    def test_native_controls_forward_real_settings_and_visualization_skill(self):
        import execution
        form={'prompt':'Draw a comparison','request_id':'id','permission':'Full Access','effort':'Extra high','speed':'Fast','mode':'Goal','goal_objective':'An inspectable chart','model':'gpt-6.1-sol','visualization':'yes'}
        with patch('execution.capability',return_value={'skills':[{'id':'viz','name':'visualize:visualize'}]}),patch('execution.store') as backend:
            backend.return_value.submit.return_value={'id':'id','session':'owned'};execution.submit(form)
        value=backend.return_value.submit.call_args.args[0]
        self.assertEqual(value['service_tier'],'priority');self.assertEqual(value['work_mode'],'goal');self.assertEqual(value['model'],'gpt-6.1-sol');self.assertEqual(value['skills'],['viz'])

    def test_background_sidebar_polling_never_expires_a_long_composer_draft(self):
        import re
        with patch('execution.capability',return_value={'enabled':False}),patch('execution.conversations',return_value=[]):
            page=self.client.get('/').get_data(as_text=True);nonce=re.search('name="request_id" value="([^"]+)"',page).group(1)
            for _ in range(40):self.client.get('/tasks')
            page=self.client.get('/').get_data(as_text=True)
            self.assertEqual(re.search('name="request_id" value="([^"]+)"',page).group(1),nonce)

    def test_late_cookie_cannot_restore_an_old_task_selection(self):
        with self.client.session_transaction() as s:s['owned_worker_sessions']=['first','second']
        self.client.get('/view/prompt?task=first');self.client.get('/view/prompt?task=second')
        with self.client.session_transaction() as s:s['worker_session']='first'
        page=self.client.get('/view/prompt').get_data(as_text=True)
        self.assertIn('/execution/status/second',page);self.assertNotIn('/execution/status/first',page)

    def test_goal_resume_cannot_replay_completed_execution_waiting_review_or_reset_repairs(self):
        with self.client.session_transaction() as s:s['owned_worker_sessions']=['owned'];s['csrf']='nonce'
        for state,reworks in [('PAUSED_REVIEW',0),('NEEDS_REWORK',2),('INTERRUPTED',2)]:
            with patch('execution.status',return_value={'goal':{'status':'paused'},'turns':[{'state':state,'reworks':reworks}]}),patch('execution.store') as backend:
                response=self.client.post('/execution/goal/resume',data={'session':'owned','csrf':'nonce'},headers={'Origin':'http://localhost'})
                self.assertEqual(response.status_code,409);backend.return_value.submit.assert_not_called()

    def test_goal_followup_keeps_original_objective_and_completed_goal_returns_to_task(self):
        with self.client.session_transaction() as s:s['owned_worker_sessions']=['owned'];s['worker_session']='owned'
        value={'turns':[{'id':'turn','mode':'full','effort':'xhigh','work_mode':'goal','service_tier':'priority'}],'sessions':[{'id':'owned','model':'gpt-6.1-sol'}],'goal':{'objective':'Original goal & evidence','status':'paused'}}
        with patch('execution.status',return_value=value):
            page=self.client.get('/view/prompt').get_data(as_text=True)
            self.assertIn('value="Original goal &amp; evidence" readonly',page)
            value['goal']['status']='complete';page=self.client.get('/view/prompt').get_data(as_text=True)
            self.assertIn('name="mode" value="Task"',page)

    def test_real_adapter_and_store_accept_task_followup_without_resetting_completed_goal(self):
        import tempfile,uuid,json,execution
        from pathlib import Path
        from researchops.worker_store import Store,save
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory),initialize=True);first=str(uuid.uuid4())
            capability={'enabled':True,'models':['test'],'default_model':'test','skills':[],'work_modes':['task','goal']}
            with patch.object(store,'capability',return_value=capability):
                store.submit({'id':first,'session':None,'prompt':'Original goal','mode':'full','effort':'high','skills':[],'model':'test','work_mode':'goal','goal_objective':'Original goal'})
                store.update(first,state='REVIEW_PASS');path=store.runtime/'goals'/first/'state.json'
                save(path,{'objective':'Original goal','status':'complete','tokensUsed':900});before=path.read_bytes()
                following=str(uuid.uuid4())
                with patch('execution.store',return_value=store):
                    result=execution.submit({'request_id':following,'session':first,'prompt':'Return ready','permission':'Full Access','effort':'High','speed':'Standard','mode':'Task','model':'test','goal_objective':'Original goal'})
                self.assertEqual(result['state'],'QUEUED')
                request=json.loads((store.runtime/'turns'/following/'request.json').read_text(encoding='utf-8'))
                self.assertEqual(request['work_mode'],'task');self.assertEqual(request['goal_objective'],'')
                self.assertEqual(path.read_bytes(),before);self.assertEqual(len(store.status(first)['turns']),2)
    def test_unavailable_publisher_blocks_optin_before_queue_admission(self):
        import execution
        form={'prompt':'produce report','publish_result':'yes','permission':'Full Access','effort':'High','speed':'Standard','mode':'Task'}
        with patch('execution.delivery_capability',return_value={'enabled':False}),patch('execution.store') as backend:
            with self.assertRaisesRegex(ValueError,'DELIVERY_SERVICE_NOT_READY'):execution.submit(form)
            backend.assert_not_called()
    def test_selected_skills_and_optin_use_fixed_publisher_command(self):
        import execution
        from pathlib import Path
        from werkzeug.datastructures import MultiDict
        form=MultiDict([('prompt','produce report'),('request_id','id'),('publish_result','yes'),('permission','Full Access'),('effort','High'),('speed','Standard'),('mode','Task'),('skills','chosen1'),('skills','chosen2')])
        with patch('execution.delivery_capability',return_value={'enabled':True,'source':Path('C:/fixed/publisher')}),patch('execution.store') as backend,patch('execution.subprocess.run') as invoke:
            backend.return_value.submit.return_value={'id':'task-id','session':'session-id'};invoke.return_value.returncode=0
            result=execution.submit(form)
        request=backend.return_value.submit.call_args.args[0]
        self.assertEqual(request['skills'],['chosen1','chosen2']);self.assertIn('REPORT.md',request['prompt'])
        self.assertEqual(result['delivery'],'ENROLLED');self.assertEqual(invoke.call_args.args[0][-3:],['--task','task-id','--authorize-draft'])
        self.assertNotIn('shell',invoke.call_args.kwargs)
    def test_analysis_does_not_enroll_or_require_publisher(self):
        import execution
        form={'prompt':'analyze','channel':'analysis','publish_result':'yes','permission':'Full Access','effort':'High','speed':'Standard','mode':'Task'}
        with patch('execution.delivery_capability') as cap,patch('execution.store') as backend,patch('execution.subprocess.run') as invoke:
            backend.return_value.submit.return_value={'id':'id','session':'session'};execution.submit(form)
        cap.assert_not_called();invoke.assert_not_called()
        request=backend.return_value.submit.call_args.args[0];self.assertEqual(request['kind'],'analysis');self.assertEqual(request['mode'],'approval')

    def test_read_only_plan_never_requests_a_write_or_enrolls_delivery(self):
        import execution
        form={'prompt':'Plan only','mode':'Plan','speed':'Fast','publish_result':'yes','permission':'Full Access','effort':'Extra high'}
        with patch('execution.delivery_capability') as cap,patch('execution.store') as backend,patch('execution.subprocess.run') as invoke:
            backend.return_value.submit.return_value={'id':'id','session':'owned'};execution.submit(form)
        cap.assert_not_called();invoke.assert_not_called()
        value=backend.return_value.submit.call_args.args[0]
        self.assertEqual(value['work_mode'],'plan');self.assertNotIn('REPORT.md',value['prompt'])
    def test_delivery_link_and_late_writer_exit_keep_real_polling(self):
        with self.client.session_transaction() as s:s['owned_worker_sessions']=['owned']
        status={'turns':[{'id':'x','prompt':'task','state':'WAITING_TOOL_EXIT','response':'','reworks':0}], 'events':[],'approvals':[],'review_summary':None,'delivery':{'state':'PUBLISHING'}}
        with patch('execution.status',return_value=status):
            html=self.client.get('/execution/status/owned').get_data(as_text=True)
        self.assertIn('hx-trigger="every 2s"',html);self.assertIn('PUBLISHING',html)
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

    def test_progress_keeps_agents_and_stages_without_prompt_or_raw_commands(self):
        with self.client.session_transaction() as s:s['owned_worker_sessions']=['owned']
        status={'session':'owned','sessions':[{'id':'owned','model':'actual-model'}],
                'turns':[{'id':'turn','state':'RUNNING','effort':'high','mode':'full','reworks':0,'reason':None}],
                'approvals':[],'review_summary':None,'events':[{'kind':'COMMAND','body':'RAW_COMMAND_MUST_STAY_IN_PROMPT'}]}
        with patch('execution.status',return_value=status),patch('execution.capability',return_value={'enabled':False}):
            page=self.client.get('/execution/progress/owned').get_data(as_text=True)
        self.assertEqual(page.count('<video '),2)
        for value in ('David','Lucy','actual-model','CURRENT STAGE','data-view="progress"','hx-target="this"'):
            self.assertIn(value,page)
        for value in ('RAW_COMMAND_MUST_STAY_IN_PROMPT','prompt-form','live-answer'):
            self.assertNotIn(value,page)

    def test_idle_and_offline_progress_keep_both_avatars_without_fake_activity(self):
        for enabled in (False,True):
            cap={'enabled':enabled,'models':['actual-model'],'default_model':'actual-model'}
            with patch('execution.capability',return_value=cap):page=self.client.get('/view/progress').get_data(as_text=True)
            self.assertEqual(page.count('<video '),2)
            self.assertIn('David',page);self.assertIn('Lucy',page)
            self.assertNotIn('prompt-form',page);self.assertNotIn('SCENE–001',page)

    def test_review_pause_is_shown_on_reviewer_after_executor_completed(self):
        with self.client.session_transaction() as s:s['owned_worker_sessions']=['owned']
        status={'session':'owned','sessions':[{'id':'owned','model':'actual-model'}],
                'turns':[{'id':'turn','state':'PAUSED_REVIEW','effort':'high','mode':'approval','reworks':0,'reason':'CONTEXT_LIMIT'}],
                'approvals':[],'review_summary':None,'events':[]}
        with patch('execution.status',return_value=status):
            page=self.client.get('/execution/progress/owned').get_data(as_text=True)
        self.assertIn('执行完成 · 等待审核',page);self.assertIn('<h2>审核暂停</h2>',page)
        self.assertIn('CONTEXT_LIMIT',page);self.assertNotIn('<h2>等待 Codex 交接</h2>',page)


if __name__=='__main__':unittest.main()
