"""Delivery requires a real fixed PASS, opt-in, unchanged artifacts and readback."""
import contextlib,json,sqlite3,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch,Mock
from researchops import delivery_agent as d
from researchops.github_review import relative,inspect_file
from researchops.worker_context import packet

class FakeBridge:
 def __init__(self,root):self.root=root;self.published=0;self.prepared=0;self.check_name=relative;self.check_file=inspect_file
 def directory(self,tid,kind):return self.root/'github'/kind/tid
 def prepare(self,tid):self.prepared+=1;return {'sha256':'c'*64}
 def publish(self,tid,expected,authorize=False):
  assert authorize is True;self.published+=1
  return {'state':'PUBLISHED_DRAFT','url':'https://github.com/JIMMY081105/Building-Generation-Validation/pull/99'}

class DeliveryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.rt=Path(self.temp.name)
  self.tid=str(uuid.uuid4());self.session=str(uuid.uuid4());self.root=self.rt/'source';self.w=self.rt/'worker/workspaces'/self.session;self.w.mkdir(parents=True)
  (self.w/'REPORT.md').write_text('# Result\nLimited test evidence. Not scientific READY.\n',encoding='utf-8')
  (self.w/'code.py').write_text('value=42\n',encoding='utf-8')
  with contextlib.closing(sqlite3.connect(self.rt/'worker/worker.sqlite3')) as db:
   db.executescript('CREATE TABLE sessions(id TEXT,workspace TEXT);CREATE TABLE turns(id TEXT,session TEXT,input_hash TEXT,prompt TEXT,response TEXT,state TEXT,kind TEXT,created TEXT);')
   db.execute('INSERT INTO sessions VALUES(?,?)',(self.session,str(self.w)))
   db.execute('INSERT INTO turns VALUES(?,?,?,?,?,?,?,?)',(self.tid,self.session,'a'*64,'Prepare report','Report prepared','REVIEW_PASS','task','2026-10-23T13:00:00+00:00'))
   db.commit()
  d.save(self.rt/'worker/activation.json',{'sha256':'b'*64})
  self.active=patch.object(d,'verified_activation',return_value={'activated_at':'2026-10-23T12:00:00+00:00','sha256':'e'*64});self.active.start();self.addCleanup(self.active.stop)
  self.archive=patch.object(d.subprocess,'run',return_value=Mock(returncode=0));self.archive.start();self.addCleanup(self.archive.stop)
  self.context();self.b=FakeBridge(self.rt)
 def context(self):
  t=d.turn(self.rt,self.tid);files=d.current_files(self.w)
  snap={'files':files,'contents':{n:(self.w/n).read_text(encoding='utf-8') for n in files},'sha256':d.sha(d.canonical(files)),'scope':'LOCAL_OWNED_WORKSPACE_ONLY'}
  ctx,_=packet(t,'b'*64,snap);review={'binding_sha256':ctx['binding_sha256'],'verdict':'PASS','issues':[]};ctx['review']=review
  home=self.rt/'worker/turns'/self.tid;d.save(home/'review-context.json',ctx)
  d.save(home/'reviews/review/result.json',{'status':'PASS','binding_sha256':ctx['binding_sha256'],'review':review,'evidence':{'tools_disabled':True,'exit_code':0}})
 def enroll(self):return d.enroll(self.rt,self.root,self.tid,True)
 def run_delivery(self):return d.tick(self.rt,self.root,bridge_factory=lambda _:self.b)
 def state(self):return d.load(self.rt/'worker-delivery/intents'/self.tid/'state.json')
 def update(self,**fields):
  with contextlib.closing(sqlite3.connect(self.rt/'worker/worker.sqlite3')) as db:
   for k,v in fields.items():db.execute('UPDATE turns SET '+k+'=? WHERE id=?',(v,self.tid))
   db.commit()
 def test_normal_delivery_is_once_only_and_not_a_model_call(self):
  self.enroll();self.run_delivery();self.run_delivery()
  self.assertEqual(self.state()['state'],'DELIVERED');self.assertEqual(self.b.published,1);self.assertEqual(self.b.prepared,1)
 def test_real_worker_review_producer_contract_is_accepted(self):
  from researchops.worker_review import review_turn
  store=Mock();store.runtime=self.rt/'worker'
  def actual_schema_reply(*args,**kwargs):
   package=d.load(args[5].parent/'package.json')
   return {'binding_sha256':package['binding_sha256'],'verdict':'PASS','issues':[]},{'tools_disabled':True,'exit_code':0}
  with patch('researchops.worker_review.active',return_value=(None,None,None,{},{})),patch('researchops.worker_review.charge',return_value='test-call'),patch('researchops.worker_review.adapters.invoke',side_effect=actual_schema_reply):
   review_turn(self.rt,store,d.turn(self.rt,self.tid),'b'*64)
  self.enroll();self.run_delivery();self.assertEqual(self.b.published,1)
 def test_without_optin_pass_does_not_publish(self):
  self.assertEqual(self.run_delivery(),[]);self.assertEqual(self.b.published,0)
 def test_foreign_malformed_marker_does_not_stop_valid_delivery(self):
  self.enroll();p=self.rt/'worker-delivery/pending/not-a-task.json';p.write_text('foreign')
  self.run_delivery();self.assertEqual(p.read_text(),'foreign');self.assertEqual(self.b.published,1)
  self.assertTrue(list((self.rt/'worker-delivery/rejected-markers').glob('*.json')))
 def test_explicit_reconcile_resumes_only_proven_pre_write_failure(self):
  self.enroll()
  with patch.object(d,'verify_task',side_effect=OSError('transient')):self.run_delivery()
  self.assertEqual(self.state()['phase'],'WAITING_REVIEW')
  with self.assertRaisesRegex(d.DeliveryError,'AUTHORIZATION_REQUIRED'):d.reconcile(self.rt,self.root,self.tid)
  d.reconcile(self.rt,self.root,self.tid,True);self.run_delivery()
  self.assertEqual(self.b.published,1);self.assertTrue(list((self.rt/'worker-delivery/intents'/self.tid).glob('reconciliation-*.json')))
 def test_reconcile_never_replays_uncertain_external_intent(self):
  self.enroll();folder=self.rt/'worker-delivery/intents'/self.tid
  for phase in ('PREPARING','PUBLISHING'):
   d.save(folder/'state.json',{'state':'PAUSED','phase':phase})
   with self.assertRaisesRegex(d.DeliveryError,'EXTERNAL_INTENT'):d.reconcile(self.rt,self.root,self.tid,True)
  self.assertEqual(self.b.published,0)
 def test_reconcile_refuses_stale_review(self):
  self.enroll();d.save(self.rt/'worker-delivery/intents'/self.tid/'state.json',{'state':'PAUSED','phase':'WAITING_REVIEW'})
  (self.w/'REPORT.md').write_text('changed')
  with self.assertRaisesRegex(d.DeliveryError,'CHANGED_AFTER_REVIEW'):d.reconcile(self.rt,self.root,self.tid,True)
 def test_explicit_authorization_required(self):
  with self.assertRaisesRegex(d.DeliveryError,'AUTHORIZATION_REQUIRED'):d.enroll(self.rt,self.root,self.tid)
 def test_historical_tasks_not_adopted(self):
  self.update(created='2026-10-22T00:00:00+00:00')
  with self.assertRaisesRegex(d.DeliveryError,'HISTORICAL_TASK'):self.enroll()
 def test_analysis_has_no_artifact_publication(self):
  self.update(kind='analysis')
  with self.assertRaisesRegex(d.DeliveryError,'TEXT_ANALYSIS'):self.enroll()
 def test_in_progress_and_rework_never_publish(self):
  self.enroll()
  for s in ('RUNNING','REVIEWING','NEEDS_REWORK','PAUSED_REVIEW'):
   self.update(state=s);self.assertEqual(self.run_delivery(),[])
  self.assertEqual(self.b.published,0)
 def test_report_changed_after_pass_is_rejected(self):
  self.enroll();(self.w/'REPORT.md').write_text('changed');self.run_delivery()
  self.assertEqual(self.state()['reason'],'WORKSPACE_CHANGED_AFTER_REVIEW');self.assertEqual(self.b.published,0)
 def test_unchanged_report_does_not_hide_changed_source(self):
  self.enroll();(self.w/'code.py').write_text('value=0');self.run_delivery()
  self.assertEqual(self.state()['state'],'PAUSED');self.assertEqual(self.b.published,0)
 def test_added_unreviewed_source_invalidates_pass(self):
  self.enroll();(self.w/'new.py').write_text('value=0');self.run_delivery();self.assertEqual(self.b.published,0)
 def test_input_changed_after_enrollment_rejected(self):
  self.enroll();self.update(input_hash='d'*64);self.run_delivery();self.assertEqual(self.state()['reason'],'TASK_BINDING_CHANGED')
 def test_failed_or_tool_enabled_review_is_not_a_real_pass(self):
  self.enroll();p=self.rt/'worker/turns'/self.tid/'reviews/review/result.json';r=d.load(p);r['evidence']['exit_code']=1;d.save(p,r)
  self.run_delivery();self.assertEqual(self.state()['reason'],'REAL_INDEPENDENT_PASS_REQUIRED');self.assertEqual(self.b.published,0)
 def test_forged_review_context_cannot_pass_hash_binding(self):
  self.enroll();p=self.rt/'worker/turns'/self.tid/'review-context.json';v=d.load(p);v['final_response']='fake';d.save(p,v)
  self.run_delivery();self.assertEqual(self.state()['reason'],'PASS_BINDING_MISMATCH')
 def test_uncertain_crash_intent_is_not_replayed(self):
  self.enroll();p=self.rt/'worker-delivery/intents'/self.tid/'state.json';d.save(p,{'state':'PUBLISHING','package_sha256':'c'*64})
  self.run_delivery();self.assertEqual(self.b.prepared,0);self.assertEqual(self.b.published,0);self.assertEqual(self.state()['state'],'PAUSED')
 def test_preparing_crash_does_not_reprepare(self):
  self.enroll();d.save(self.rt/'worker-delivery/intents'/self.tid/'state.json',{'state':'PREPARING'})
  self.run_delivery();self.assertEqual(self.b.prepared,0)
 def test_external_failure_pauses_without_retry(self):
  self.enroll();self.b.publish=Mock(side_effect=RuntimeError('must not log raw provider text'))
  self.run_delivery();self.run_delivery();self.b.publish.assert_called_once();self.assertEqual(self.state()['reason'],'RuntimeError')
 def test_unsafe_readback_url_is_rejected(self):
  self.enroll();self.b.publish=Mock(return_value={'state':'PUBLISHED_DRAFT','url':'https://evil.invalid/pull/1'})
  self.run_delivery();self.assertEqual(self.state()['reason'],'DRAFT_READBACK_NOT_CONFIRMED')
 def test_different_repository_intent_is_rejected(self):
  self.enroll();p=self.rt/'worker-delivery/intents'/self.tid/'intent.json';v=d.load(p);v['repository']='wrong/repo';d.save(p,v)
  self.run_delivery();self.assertEqual(self.b.published,0)
 def test_publisher_does_not_copy_code_as_an_artifact(self):
  (self.w/'delivery.json').write_text(json.dumps({'files':['code.py']}));self.context();self.enroll();self.run_delivery()
  self.assertEqual(self.b.published,0);self.assertFalse((self.rt/'github/intake'/self.tid/'code.py').exists())
 def test_hidden_runtime_artifacts_cannot_be_published(self):
  (self.w/'delivery.json').write_text(json.dumps({'files':['.runtime/out.md']}));self.context();self.enroll();self.run_delivery();self.assertEqual(self.b.published,0)
 def test_sensitive_filename_refused_before_contents_read(self):
  (self.w/'auth.json').write_text('placeholder')
  with self.assertRaisesRegex(d.DeliveryError,'SENSITIVE'):d.current_files(self.w)
 def test_existing_intake_never_overwritten(self):
  self.enroll();p=self.rt/'github/intake'/self.tid;p.mkdir(parents=True);(p/'KEEP.md').write_text('keep')
  self.run_delivery();self.assertEqual((p/'KEEP.md').read_text(),'keep');self.assertEqual(self.b.published,0)
 def test_duplicate_enrollment_keeps_identity(self):
  self.assertEqual(self.enroll(),self.enroll())
 def test_paused_publisher_does_not_admit_new_delivery(self):
  d.save(self.rt/'worker-delivery/admission-paused.json',{'owner':d.OWNER})
  with self.assertRaisesRegex(d.DeliveryError,'RESULT_DELIVERY_PAUSED'):self.enroll()
 def test_upgrade_does_not_silently_adopt_prior_source_intent(self):
  self.enroll();p=self.rt/'worker-delivery/intents'/self.tid/'intent.json';v=d.load(p);v['publisher_source_sha256']='f'*64;d.save(p,v)
  self.run_delivery();self.assertEqual(self.b.published,0);self.assertEqual(self.state()['reason'],'PUBLISHER_VERSION_CHANGED_NEEDS_RECONCILIATION')
 def test_archive_failure_does_not_republish_successful_package(self):
  self.enroll()
  with patch.object(d.subprocess,'run',return_value=Mock(returncode=1)):self.run_delivery()
  self.run_delivery();self.assertEqual(self.b.published,1);self.assertEqual(self.state()['archive_status'],'FAILED_NO_PUBLICATION_RETRY')
 def test_slow_archive_child_is_not_killed_while_holding_shared_lock(self):
  import subprocess,sys
  run=subprocess.run;marker=self.rt/'simulated-archive.lock'
  code='import pathlib,time; p=pathlib.Path('+repr(str(marker))+');p.write_text("held");time.sleep(.3);p.unlink();print("appended verified")'
  def slow_archive(*args,**kwargs):
   # Compress only the injected external deadline. A forced timeout would kill
   # the harmless real child and leave its simulated shared lock behind.
   if 'timeout' in kwargs:kwargs['timeout']=.1
   return run([sys.executable,'-c',code],**kwargs)
  self.enroll()
  with patch.object(d.subprocess,'run',side_effect=slow_archive):self.run_delivery()
  self.assertFalse(marker.exists());self.assertEqual(self.state()['archive_status'],'APPENDED');self.assertEqual(self.b.published,1)
 def test_unknown_pause_record_is_not_overwritten(self):
  p=self.rt/'worker-delivery/admission-paused.json';d.save(p,{'owner':'someone-else'})
  with self.assertRaisesRegex(d.DeliveryError,'UNKNOWN_PAUSE'):d.control(self.rt,self.root,'disable')
  self.assertEqual(d.load(p)['owner'],'someone-else')

if __name__=='__main__':unittest.main()
