"""Deterministic opt-in delivery of independently reviewed task artifacts."""
import contextlib
import ctypes as C
from ctypes import wintypes as W
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
import threading
import uuid

OWNER='BGV.Worker.ResultDelivery.v1'
RUNTIME=Path(r'E:\Github\Building-Generation-Validation\.runtime')
FILES=('delivery_agent.py','researchops/__init__.py','researchops/delivery_agent.py','tests/test_delivery_agent.py','tools/delivery.ps1','DELIVERY.md')
BRIDGE_FILES=('github_review.py','researchops/__init__.py','researchops/github_review.py','tools/github.ps1','tools/review_github.py','config/github-review.example.json','tests/test_github_review.py','GITHUB.md','POLICY.md','README.md')
BUSY={'QUEUED','STARTING','RUNNING','WAITING_APPROVAL','WAITING_INPUT','REVIEWING','CANCELLING','WAITING_TOOL_EXIT'}

class DeliveryError(ValueError):pass
def canonical(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def sha(b):return hashlib.sha256(b).hexdigest()
def utc():return dt.datetime.now(dt.timezone.utc).isoformat()
def safe(p):
 p=Path(p).absolute()
 if any(x.is_symlink() or x.is_junction() for x in (p,*p.parents)):raise DeliveryError('REPARSE_PATH')
 return p
def read(p,limit=131072):
 with safe(p).open('rb') as f:b=f.read(limit+1)
 if len(b)>limit:raise DeliveryError('INPUT_TOO_LARGE')
 return b
def load(p):return json.loads(read(p).decode('utf-8-sig'))
def save(p,v):
 p=safe(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+'.'+uuid.uuid4().hex+'.tmp')
 with t.open('xb') as f:f.write(canonical(v))
 os.replace(t,p)
def ident(v):
 if type(v) is not str or str(uuid.UUID(v))!=v:raise DeliveryError('INVALID_TASK_ID')
 return v
def manifest(root):
 files={n:sha(read(safe(root)/n,1048576)) for n in FILES}
 return {'files':files,'sha256':sha(canonical(files))}
def identity(pid):
 k=C.WinDLL('kernel32',use_last_error=True)
 k.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];k.OpenProcess.restype=W.HANDLE
 k.GetProcessTimes.argtypes=[W.HANDLE,C.POINTER(W.FILETIME),C.POINTER(W.FILETIME),C.POINTER(W.FILETIME),C.POINTER(W.FILETIME)]
 k.CloseHandle.argtypes=[W.HANDLE]
 h=k.OpenProcess(0x1000,False,pid)
 if not h:return None if C.get_last_error()==87 else 'UNKNOWN'
 a,b,c,d=(W.FILETIME() for _ in range(4))
 try:return str((a.dwHighDateTime<<32)|a.dwLowDateTime) if k.GetProcessTimes(h,C.byref(a),C.byref(b),C.byref(c),C.byref(d)) else 'UNKNOWN'
 finally:k.CloseHandle(h)

def verified_activation(runtime,root):
 a=load(runtime/'worker-delivery/activation.json');m=manifest(root)
 if a.get('owner')!=OWNER or a.get('sha256')!=m['sha256'] or safe(a['source'])!=safe(root):raise DeliveryError('DELIVERY_SOURCE_NOT_ACTIVATED')
 if safe(root)!=safe(runtime/'worker-delivery/snapshots'/m['sha256']/'source'):raise DeliveryError('DELIVERY_SOURCE_PATH_MISMATCH')
 r=load(Path(a['review']));t=load(Path(a['tests']))
 if r.get('verdict')!='PASS' or r.get('issues')!=[] or r.get('delivery_source_sha256')!=m['sha256'] or r.get('tools_disabled') is not True or r.get('evidence',{}).get('exit_code')!=0 or r.get('evidence',{}).get('tools_disabled') is not True or r.get('tests_sha256')!=sha(read(Path(a['tests']),1048576)) or t.get('success') is not True or t.get('source_unchanged') is not True or t.get('delivery_source_sha256')!=m['sha256']:raise DeliveryError('DELIVERY_APPROVAL_MISMATCH')
 return a

def turn(runtime,tid):
 ident(tid)
 with contextlib.closing(sqlite3.connect((safe(runtime)/'worker/worker.sqlite3').as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
  db.row_factory=sqlite3.Row;r=db.execute('SELECT t.*,s.workspace FROM turns t JOIN sessions s ON s.id=t.session WHERE t.id=?',(tid,)).fetchone()
 if r is None:raise DeliveryError('UNKNOWN_TASK')
 return dict(r)

def enroll(runtime,root,tid,authorize=False):
 if authorize is not True:raise DeliveryError('EXPLICIT_DRAFT_DELIVERY_AUTHORIZATION_REQUIRED')
 a=verified_activation(runtime,root);t=turn(runtime,tid)
 if any((runtime/'worker-delivery'/n).exists() for n in ('admission-paused.json','stop-when-idle.json')):raise DeliveryError('RESULT_DELIVERY_PAUSED')
 if dt.datetime.fromisoformat(t['created'])<dt.datetime.fromisoformat(a['activated_at']):raise DeliveryError('HISTORICAL_TASK_NOT_ENROLLED')
 if t['kind']!='task':raise DeliveryError('TEXT_ANALYSIS_IS_NOT_ARTIFACT_DELIVERY')
 d=safe(runtime/'worker-delivery/intents'/ident(tid));d.mkdir(parents=True,exist_ok=True)
 p=d/'intent.json';v={'owner':OWNER,'task':tid,'session':t['session'],'input_hash':t['input_hash'],'repository':'JIMMY081105/Building-Generation-Validation','draft_only':True,'worker_bundle':load(runtime/'worker/activation.json')['sha256'],'publisher_source_sha256':a['sha256']}
 if p.exists():
  old=load(p)
  if old!=v:raise DeliveryError('DELIVERY_INTENT_CONFLICT')
 else:
  with p.open('xb') as f:f.write(canonical(v))
 pending=runtime/'worker-delivery/pending'/(tid+'.json')
 if pending.exists():
  if load(pending)!={'owner':OWNER,'task':tid}:raise DeliveryError('UNKNOWN_PENDING_DELIVERY')
 else:save(pending,{'owner':OWNER,'task':tid})
 return v

def bridge(runtime):
 home=runtime/'github';a=load(home/'activation.json');root=safe(home/'snapshots'/a['source_sha256']/'source')
 if a.get('owner')!='BGV.Windows.GitHubReview.v1' or safe(a['source'])!=root:raise DeliveryError('GITHUB_BRIDGE_IDENTITY_MISMATCH')
 hashes={n:sha(read(root/n,1048576)) for n in BRIDGE_FILES}
 if sha(canonical(hashes))!=a['source_sha256']:raise DeliveryError('GITHUB_BRIDGE_SOURCE_CHANGED')
 spec=importlib.util.spec_from_file_location('bgv_delivery_bridge_'+a['source_sha256'],root/'researchops/github_review.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
 b=m.Bridge(runtime=home,root=root);b.verify_release();b.check_name=m.relative;b.check_file=m.inspect_file
 return b

def current_files(workspace):
 files={};stack=[workspace];excluded={'.git','.venv','.runtime','__pycache__','node_modules','logs','checkpoints'}
 while stack:
  for p in stack.pop().iterdir():
   p=safe(p)
   if p.is_dir():
    if p.name not in excluded:stack.append(p)
   else:
    if len(files)>=256:raise DeliveryError('WORKSPACE_LIMIT_REACHED')
    if p.name.lower().startswith(('.env','auth.json','credentials','id_rsa','id_ed25519')) or p.suffix.lower() in ('.key','.pem','.pfx','.p12','.ppk','.kdbx'):raise DeliveryError('SENSITIVE_WORKSPACE_PATH')
    data=read(p,16*1048576);files[p.relative_to(workspace).as_posix()]={'sha256':sha(data),'bytes':len(data)}
 return files

def verify_task(runtime,intent):
 tid=ident(intent['task']);t=turn(runtime,tid)
 if intent.get('owner')!=OWNER or intent.get('repository')!='JIMMY081105/Building-Generation-Validation' or intent.get('draft_only') is not True or intent['session']!=t['session'] or intent['input_hash']!=t['input_hash']:raise DeliveryError('TASK_BINDING_CHANGED')
 if t['state']!='REVIEW_PASS':return None
 with contextlib.closing(sqlite3.connect((runtime/'worker/worker.sqlite3').as_uri()+'?mode=ro',uri=True,timeout=2)) as db:
  if any(row[0] in BUSY for row in db.execute('SELECT state FROM turns WHERE session=?',(t['session'],))):return None
 workspace=safe(t['workspace'])
 if workspace!=safe(runtime/'worker/workspaces'/ident(t['session'])):raise DeliveryError('WORKSPACE_IDENTITY_MISMATCH')
 ctx=json.loads(read(runtime/'worker/turns'/tid/'review-context.json',8*1048576).decode('utf-8-sig'))
 binding=ctx.get('binding_sha256');unsigned={k:v for k,v in ctx.items() if k not in ('binding_sha256','review')}
 if sha(canonical(unsigned))!=binding or ctx.get('review',{}).get('verdict')!='PASS' or ctx['review'].get('issues')!=[] or ctx['review'].get('binding_sha256')!=binding or ctx.get('task')!=tid or ctx.get('request')!=t['prompt'] or ctx.get('final_response')!=t['response'] or ctx.get('source_sha256')!=intent['worker_bundle']:raise DeliveryError('PASS_BINDING_MISMATCH')
 receipts=[load(p) for p in (runtime/'worker/turns'/tid/'reviews').glob('*/result.json')]
 # The real worker receipt binds source through binding_sha256 over the full
 # context, not through a redundant top-level source_sha256 receipt field.
 if not any(r.get('status')=='PASS' and r.get('binding_sha256')==binding and r.get('review')==ctx['review'] and r.get('evidence',{}).get('tools_disabled') is True and r.get('evidence',{}).get('exit_code')==0 for r in receipts):raise DeliveryError('REAL_INDEPENDENT_PASS_REQUIRED')
 if current_files(workspace)!=ctx['workspace']['files']:raise DeliveryError('WORKSPACE_CHANGED_AFTER_REVIEW')
 return t,workspace,ctx

def prepare(runtime,b,intent,proof):
 t,workspace,ctx=proof;tid=t['id'];files=ctx['workspace']['files']
 names=['REPORT.md']
 if 'delivery.json' in files:
  raw=read(workspace/'delivery.json');v=json.loads(raw)
  if sha(raw)!=files['delivery.json']['sha256'] or type(v) is not dict or set(v)!={'files'} or type(v['files']) is not list or len(v['files'])>15:raise DeliveryError('INVALID_ARTIFACT_CATALOG')
  names+=v['files']
 if len(set(names))!=len(names):raise DeliveryError('DUPLICATE_ARTIFACT')
 intake=b.directory(tid,'intake');intake.mkdir(parents=True,exist_ok=False)
 items=[]
 for name in names:
  b.check_name(name)
  if type(name) is not str or name not in files or Path(name).is_absolute() or '..' in Path(name).parts or '\\' in name or ':' in name:raise DeliveryError('UNREVIEWED_ARTIFACT_PATH')
  data=read(workspace/name,8*1048576)
  if sha(data)!=files[name]['sha256'] or len(data)!=files[name]['bytes']:raise DeliveryError('ARTIFACT_CHANGED_AFTER_REVIEW')
  b.check_file(name,data)
  dest=safe(intake/name);dest.parent.mkdir(parents=True,exist_ok=True)
  with dest.open('xb') as f:f.write(data)
  items.append({'path':name,'sha256':sha(data)})
 save(intake/'ready.json',{'schema':1,'id':tid,'title':'Task result '+tid,'summary':'Independent task-workspace review passed. This is a reviewable result package, not scientific READY or merge authorization.','reported_status':'PARTIAL','files':items})
 return b.prepare(tid)

def archive_delivery(folder,intent,state):
 """Append factual delivery evidence without force-killing the shared archiver."""
 try:
  note=folder/'archive.md';note.write_text('**ACTUAL EXECUTION**\nDeterministic reviewed result delivery. Task: '+intent['task']+'\nDraft PR: '+state['url']+'\nPackage SHA256: '+state['package_sha256']+'\nStatus: SUCCESS\nNo scientific acceptance or merge performed.\n',encoding='utf-8')
  # The archiver owns a shared lock and bounded lock-acquisition wait. A shorter
  # forced deadline can strand that lock and block unrelated agents. Our service
  # heartbeat remains independent while the existing archiver finishes.
  archived=subprocess.run([r'C:\Python312\python.exe',r'F:\Personal Data\_archive_system\ai_archive.py','annotate','--platform','OpenAI Codex','--title','Reviewed task result delivery '+intent['task'],'--body-file',str(note)],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  return 'APPENDED' if archived.returncode==0 else 'FAILED_NO_PUBLICATION_RETRY'
 except (OSError,subprocess.TimeoutExpired):return 'UNVERIFIED_NO_PUBLICATION_RETRY'

def tick(runtime,root,bridge_factory=bridge):
 activation=verified_activation(runtime,root);home=runtime/'worker-delivery'
 results=[]
 for marker in sorted((home/'pending').glob('*.json')):
  # Completed history stays immutable; only this owned queue marker is retired.
  folder=None;state={'state':'WAITING_REVIEW'}
  try:
   ident(marker.stem);folder=safe(home/'intents'/marker.stem)
   if load(marker)!={'owner':OWNER,'task':folder.name}:raise DeliveryError('UNKNOWN_PENDING_DELIVERY')
   ident(folder.name);intent=load(folder/'intent.json');state=load(folder/'state.json') if (folder/'state.json').exists() else {'state':'WAITING_REVIEW'}
   if state['state']=='DELIVERED':safe(marker).unlink();continue
   if state['state']=='PAUSED':continue
   if intent.get('publisher_source_sha256')!=activation['sha256']:raise DeliveryError('PUBLISHER_VERSION_CHANGED_NEEDS_RECONCILIATION')
   proof=verify_task(runtime,intent)
   if proof is None:continue
   if state['state']=='WAITING_REVIEW':
    # Persist before external calls. A crash never automatically replays them.
    save(folder/'state.json',{'state':'PREPARING','at':utc()})
    b=bridge_factory(runtime);package=prepare(runtime,b,intent,proof)
    state={'state':'PREPARED','package_sha256':package['sha256'],'at':utc()};save(folder/'state.json',state)
   elif state['state']!='PREPARED':raise DeliveryError('RECONCILIATION_REQUIRED_NO_REPLAY')
   else:b=bridge_factory(runtime)
   if verify_task(runtime,intent) is None:continue
   save(folder/'state.json',{**state,'state':'PUBLISHING','at':utc()})
   result=b.publish(intent['task'],state['package_sha256'],authorize=True)
   if result.get('state') not in ('PUBLISHED_DRAFT','OPEN_FOR_USER_REVIEW') or not re.fullmatch(r'https://github.com/JIMMY081105/Building-Generation-Validation/pull/[1-9][0-9]*',str(result.get('url'))):raise DeliveryError('DRAFT_READBACK_NOT_CONFIRMED')
   state={'state':'DELIVERED','url':result['url'],'package_sha256':state['package_sha256'],'at':utc()};save(folder/'state.json',state);results.append(state)
   # Archive the action, never the artifact or raw model/provider output.
   state['archive_status']=archive_delivery(folder,intent,state)
   save(folder/'state.json',state)
   safe(marker).unlink()
  except Exception as e:
   reason=str(e) if isinstance(e,DeliveryError) or (type(e).__name__=='BridgeError' and re.fullmatch(r'[A-Z0-9_]{1,80}',str(e))) else type(e).__name__
   if folder is None:
    # Foreign malformed markers stay untouched and cannot stop valid deliveries.
    save(home/'rejected-markers'/(sha(marker.name.encode())+'.json'),{'owner':OWNER,'marker':marker.name,'reason':reason})
    continue
   save(folder/'state.json',{'state':'PAUSED','reason':reason,'phase':state.get('state','UNKNOWN'),'at':utc()});results.append({'state':'PAUSED','task':folder.name,'reason':reason})
 return results

def reconcile(runtime,root,tid,authorize=False):
 """Explicit bounded recovery: only proven pre-write work can be requeued."""
 if authorize is not True:raise DeliveryError('EXPLICIT_DRAFT_DELIVERY_AUTHORIZATION_REQUIRED')
 activation=verified_activation(runtime,root);folder=safe(runtime/'worker-delivery/intents'/ident(tid))
 intent=load(folder/'intent.json');state=load(folder/'state.json')
 if state.get('state')!='PAUSED' or intent.get('publisher_source_sha256')!=activation['sha256']:raise DeliveryError('RECONCILIATION_STATE_OR_VERSION_MISMATCH')
 if verify_task(runtime,intent) is None:raise DeliveryError('RECONCILIATION_REQUIRES_CURRENT_PASS')
 # Never recreate/retry a branch/PR after an uncertain external intent.
 if state.get('phase')!='WAITING_REVIEW' or any((runtime/'github'/kind/tid).exists() for kind in ('intake','outbox')):raise DeliveryError('EXTERNAL_INTENT_REQUIRES_READ_ONLY_BRIDGE_RECONCILIATION')
 save(folder/('reconciliation-'+uuid.uuid4().hex+'.json'),{'owner':OWNER,'prior_state':state,'authorized_at':utc(),'method':'PROVEN_PRE_EXTERNAL_WRITE_ONLY'})
 save(folder/'state.json',{'state':'WAITING_REVIEW','at':utc(),'reconciled':True})
 save(runtime/'worker-delivery/pending'/(tid+'.json'),{'owner':OWNER,'task':tid})
 return {'state':'WAITING_REVIEW','task':tid}

@contextlib.contextmanager
def lock(home):
 import msvcrt
 home.mkdir(parents=True,exist_ok=True)
 with safe(home/'service.lock').open('a+b') as f:
  if f.seek(0,2)==0:f.write(b'0');f.flush()
  f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
  try:yield
  finally:f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)

def serve(runtime,root):
 a=verified_activation(runtime,root);home=runtime/'worker-delivery'
 with lock(home):
  stop=threading.Event()
  def heartbeat(state=None):
   paused=any((home/n).exists() for n in ('admission-paused.json','stop-when-idle.json'))
   save(home/'service.json',{'owner':OWNER,'pid':os.getpid(),'birth':identity(os.getpid()),'parent_pid':os.getppid(),'source_sha256':a['sha256'],'state':state or ('PAUSED' if paused else 'RUNNING'),'observed_at':utc()})
  def beat():
   while not stop.wait(3):heartbeat()
  heartbeat();thread=threading.Thread(target=beat,daemon=True);thread.start()
  try:
   while not (home/'stop-when-idle.json').exists():
    if not (home/'admission-paused.json').exists():tick(runtime,root)
    stop.wait(10)
  finally:stop.set();thread.join(4);heartbeat('STOPPED')

def control(runtime,root,mode):
 verified_activation(runtime,root);home=runtime/'worker-delivery'
 if mode in ('disable','stop-when-idle'):
  path=home/('admission-paused.json' if mode=='disable' else 'stop-when-idle.json')
  if path.exists():
   if load(path).get('owner')!=OWNER:raise DeliveryError('UNKNOWN_PAUSE_RECORD')
  else:save(path,{'owner':OWNER,'at':utc()})
 elif mode=='enable':
  for n in ('admission-paused.json','stop-when-idle.json'):
   p=home/n
   if p.exists():
    if load(p).get('owner')!=OWNER:raise DeliveryError('UNKNOWN_PAUSE_RECORD')
    os.replace(p,p.with_name('resumed-'+uuid.uuid4().hex+'-'+n))
 return {'owner':OWNER,'operation':mode,'at':utc()}
