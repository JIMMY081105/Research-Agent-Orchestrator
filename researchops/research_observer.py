"""Read-only research observation. Static SSH probe; never dispatches models or research work."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import time
import uuid
from datetime import datetime, timezone
from . import winproc
from .integrity import no_links, read_json, write_json

SSH = str(Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32/OpenSSH/ssh.exe')
REMOTE_COMMAND = '/usr/bin/python3 -I -B -'
MAX_RESPONSE_BYTES = 262144
UNKNOWN = 'UNKNOWN'
SSH_OPTIONS = ('BatchMode=yes','NumberOfPasswordPrompts=0','StrictHostKeyChecking=yes','UpdateHostKeys=no',
    'ConnectTimeout=8','ConnectionAttempts=1','ClearAllForwardings=yes','ControlMaster=no','ControlPath=none',
    'ControlPersist=no','PermitLocalCommand=no','RemoteCommand=none','ProxyCommand=none','ProxyJump=none',
    'ForwardAgent=no','ForwardX11=no','SendEnv=-*','IdentitiesOnly=yes','ServerAliveInterval=5','ServerAliveCountMax=1')

# One fixed program. Paths/commands are constants; no model or user command is interpolated.
REMOTE_PROBE = r'''
import os,json,re,time,signal,subprocess,sys
from pathlib import Path
ROOT=sys.argv[1]
PARAMS=json.loads(sys.argv[2])
KNOWN_FILES=PARAMS['known_files']
MONITOR_SCRIPTS=PARAMS['monitor_scripts']
if not re.fullmatch(r'/[A-Za-z0-9_./-]{3,255}',ROOT) or '..' in Path(ROOT).parts or len(Path(ROOT).parts)<3 or ROOT.startswith(('/root','/home','/etc','/proc','/sys','/dev','/run')):raise SystemExit(64)
DEADLINE=time.monotonic()+8
signal.alarm(10)
def allowed(s):
 p=Path(s)
 return p.is_absolute() and '..' not in p.parts and (str(p)==ROOT or str(p).startswith(ROOT+'/')) and not any(x.lower() in ('.ssh','.aws','.claude','.codex','auth.json','credentials.json','.env') for x in p.parts)
def canonical(s):
 try:
  p=str(Path(s).resolve(strict=True))
  return p if allowed(p) else None
 except (OSError,RuntimeError):return None
def text(path,n=4096):
 with open(path,'rb') as f:return f.read(n).decode('utf-8','replace')
def statpid(pid):
 try:
  raw=text('/proc/'+str(pid)+'/stat',4096);rest=raw[raw.rfind(')')+2:].split()
  return {'pid':pid,'start_ticks':rest[19],'ppid':int(rest[1]),'proc_state':rest[0]}
 except (OSError,ValueError,IndexError):return None
def githead(cwd):
 p=Path(cwd)
 while allowed(str(p)):
  dot=p/'.git'
  if dot.exists():
   try:
    if dot.is_file():
     value=text(dot,1024).strip()
     if not value.startswith('gitdir: '):return 'UNKNOWN'
     dot=Path(value[8:]);dot=dot if dot.is_absolute() else p/dot
    real=canonical(dot)
    if not real:return 'UNKNOWN'
    dot=Path(real);head=text(dot/'HEAD',512).strip()
    if re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',head):return head
    if not head.startswith('ref: refs/') or '..' in head:return 'UNKNOWN'
    ref=head[5:];common=dot
    if (dot/'commondir').is_file():
     value=text(dot/'commondir',512).strip();path=Path(value);real=canonical(path if path.is_absolute() else dot/path)
     if not real:return 'UNKNOWN'
     common=Path(real)
    refpath=common/ref
    if canonical(refpath):
     result=text(refpath,256).strip()
     if re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',result):return result
    if canonical(common/'packed-refs'):
     for line in text(common/'packed-refs',131072).splitlines():
      fields=line.split()
      if len(fields)==2 and fields[1]==ref and re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',fields[0]):return fields[0]
   except OSError:pass
   return 'UNKNOWN'
  if str(p)==ROOT:break
  p=p.parent
 return 'UNKNOWN'
def progress(path):
 # Extract finite signals/counters only. Do not return arbitrary log text.
 try:
  with open(path,'rb') as f:
   f.seek(0,2);f.seek(max(0,f.tell()-4096));tail=f.read(4096).decode('utf-8','replace')
  signals=[]
  for word,code in (('completed','COMPLETED'),('checkpoint','CHECKPOINT'),('failed','FAILED'),('running','RUNNING'),('critical_stop','CRITICAL_STOP'),('entire_task_stop_required','ENTIRE_TASK_STOP_REQUIRED')):
   if word in tail.lower():signals.append(code)
  counters={}
  for key,val in re.findall(r'\b(step|epoch|iteration|progress)\s*[:=]\s*([0-9]{1,9})\b',tail.lower()):counters[key]=int(val)
  return {'signals':signals,'counters':counters}
 except OSError:return {'signals':[],'counters':{}}
def metadata(path):
 real=canonical(path)
 if not real:return None
 try:
  p=Path(real);st=p.stat()
  if not p.is_file():return None
  row={'path':real,'size':st.st_size,'mtime_ns':st.st_mtime_ns}
  if p.suffix in ('.log','.md','.txt','.json'):row['progress']=progress(p)
  return row
 except OSError:return None
identities=[];processes=[];complete=True;errors=[]
for pid in sorted(int(p.name) for p in Path('/proc').iterdir() if p.name.isdigit()):
 if len(identities)>=8192 or time.monotonic()>DEADLINE:complete=False;break
 before=statpid(pid)
 if before is None:errors.append(pid);continue
 identities.append(before)
 try:cwd=canonical(os.readlink('/proc/'+str(pid)+'/cwd'))
 except OSError:cwd=None
 if not cwd:continue
 try:
  args=text('/proc/'+str(pid)+'/cmdline',16384).split('\x00')
  script=next((Path(a).name for a in args[1:] if a.endswith('.py') and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',Path(a).name)), 'UNKNOWN')
  exe=Path(os.readlink('/proc/'+str(pid)+'/exe')).name
  if not re.fullmatch(r'[A-Za-z0-9_.+-]{1,100}',exe):exe='UNKNOWN'
 except OSError:script=exe='UNKNOWN';args=[]
 after=statpid(pid)
 if not after or before['start_ticks']!=after['start_ticks']:continue
 files=[]
 for name in ('HANDOFF.md','handoff.md','run.log','train.log','output.log','progress.log','status.json','last.ckpt','checkpoint.pt'):
  item=metadata(Path(cwd)/name)
  if item:files.append(item)
 for i,arg in enumerate(args[:-1]):
  if arg in ('--checkpoint','--ckpt','--log-file','--log_file'):
   item=metadata(args[i+1])
   if item and item not in files:files.append(item)
 kind='MONITOR' if script in MONITOR_SCRIPTS else 'UNCLASSIFIED'
 processes.append({**after,'cwd':cwd,'exe_basename':exe,'script_basename':script,'kind':kind,
                   'cwd_git_head_commit':githead(cwd),'loaded_code_version':'UNVERIFIED','files':files[:16],
                   'tmux_session_id':'UNKNOWN','tmux_session_name':'UNKNOWN'})
 if len(processes)>=64:complete=False;break
panes=[]
try:
 done=subprocess.run(['/usr/bin/tmux','list-panes','-a','-F','#{session_id}\t#{session_name}\t#{pane_pid}'],capture_output=True,text=True,timeout=1)
 if done.returncode==0:
  for line in done.stdout.splitlines()[:64]:
   fields=line.split('\t')
   if len(fields)==3 and re.fullmatch(r'\$[0-9]{1,9}',fields[0]) and re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',fields[1]) and fields[2].isdigit():
    panes.append({'session_id':fields[0],'session_name':fields[1],'pane_pid':int(fields[2])})
except (OSError,subprocess.TimeoutExpired):pass
parents={r['pid']:r['ppid'] for r in identities}
for row in processes:
 chain=set();pid=row['pid']
 for _ in range(64):
  if pid in chain:break
  chain.add(pid);pid=parents.get(pid,0)
  if pid<=0:break
 for pane in panes:
  if pane['pane_pid'] in chain:
   row['tmux_session_id']=pane['session_id'];row['tmux_session_name']=pane['session_name'];break
known=[]
for path in KNOWN_FILES:
 item=metadata(path)
 if item:known.append(item)
try:boot=text('/proc/sys/kernel/random/boot_id',128).strip()
except OSError:boot='UNKNOWN'
try:pid_namespace=os.readlink('/proc/self/ns/pid')
except OSError:pid_namespace='UNKNOWN'
print(json.dumps({'schema':1,'boot_id':boot,'pid_namespace_id':pid_namespace,'inventory_complete':complete,'identity_errors':errors[:8192],
                  'identities':identities,'processes':processes,'tmux':panes,'known_files':known}))
'''

def _utc():return datetime.now(timezone.utc).isoformat()
def _runtime_path(root_runtime):
    raw=Path(root_runtime)
    if not raw.is_absolute():raise ValueError('Trusted root runtime must be absolute')
    root=no_links(raw)
    if root==Path(root.anchor):raise ValueError('Runtime cannot be a volume root')
    result=no_links(root/'research-watch')
    if root not in result.parents:raise ValueError('Observer output escaped runtime')
    return result

def _safe_scope_path(value):
    if type(value) is not str or not re.fullmatch(r'/[A-Za-z0-9_./-]{3,255}',value):return False
    p=PurePosixPath(value)
    if '..' in p.parts or len(p.parts)<3 or value.startswith(('/root','/home','/etc','/proc','/sys','/dev','/run')):return False
    blocked={'.ssh','.aws','.claude','.codex','.config','auth.json','credentials.json','.netrc','.git-credentials'}
    return not any(x.lower() in blocked or x.lower().startswith('.env') or x.lower().endswith(('.pem','.key','.pfx','.p12','.ppk')) for x in p.parts)

def validate_configuration(configuration):
    if type(configuration) is not dict or configuration.get('schema')!=1 or type(configuration.get('enabled')) is not bool:raise ValueError('Invalid observer configuration')
    allowed={'schema','enabled','host_alias','read_root','known_files','monitor_scripts','cadence_seconds'}
    if set(configuration)-allowed:raise ValueError('Unknown observer configuration field')
    if not configuration['enabled']:return {'schema':1,'enabled':False}
    if set(configuration)!=allowed or configuration['cadence_seconds']!=900:raise ValueError('Invalid enabled observer scope')
    host=configuration['host_alias'];root=configuration['read_root']
    if type(host) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}',host) or not _safe_scope_path(root):raise ValueError('Unregistered host or root')
    files=configuration['known_files'];scripts=configuration['monitor_scripts']
    if type(files) is not list or len(files)>16 or any(not _safe_scope_path(x) or not (x==root or x.startswith(root+'/')) for x in files):raise ValueError('Known files escape read root')
    if type(scripts) is not list or len(scripts)>16 or any(type(x) is not str or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',x) for x in scripts):raise ValueError('Invalid monitor script registry')
    return dict(configuration)

def command(configuration):
    cfg=validate_configuration(configuration)
    if not cfg['enabled']:raise ValueError('Observer is disabled')
    data=json.dumps({'known_files':cfg['known_files'],'monitor_scripts':cfg['monitor_scripts']},sort_keys=True,separators=(',',':'))
    fixed_command=REMOTE_COMMAND+' '+shlex.quote(cfg['read_root'])+' '+shlex.quote(data)
    return [SSH,'-T',*[part for option in SSH_OPTIONS for part in ('-o',option)],cfg['host_alias'],fixed_command]

def config_metadata(raw):
    allowed={'hostname','user','port','remoteforward','localforward','dynamicforward','forwardagent','forwardx11'}
    out={}
    for line in raw.splitlines():
        key,_,value=line.partition(' ')
        if key in allowed and len(value)<=160 and re.fullmatch(r'[A-Za-z0-9_:.\[\] -]+',value):out.setdefault(key,[]).append(value)
    try:
        address=ipaddress.ip_address(out['hostname'][0]);port=int(out['port'][0])
        private_ranges=('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','fc00::/7')
        if not any(address.version==ipaddress.ip_network(network).version and address in ipaddress.ip_network(network) for network in private_ranges) or not 1<=port<=65535 or len(out['user'])!=1:raise ValueError()
    except (KeyError,ValueError,IndexError):raise ValueError('SSH endpoint outside fixed research allowlist')
    return out

def _allowed_remote_path(value,root):
    if type(value) is not str or len(value)>1024:return False
    p=PurePosixPath(value)
    return p.is_absolute() and '..' not in p.parts and (value==root or value.startswith(root+'/'))

def validate_snapshot(obj,configuration):
    cfg=validate_configuration(configuration);root=cfg.get('read_root')
    if not root:raise ValueError('Observer disabled')
    if type(obj) is not dict or set(obj)!={'schema','boot_id','pid_namespace_id','inventory_complete','identity_errors','identities','processes','tmux','known_files'} or obj['schema']!=1:raise ValueError('Invalid observer response')
    if type(obj['inventory_complete']) is not bool or type(obj['boot_id']) is not str:raise ValueError('Invalid identity metadata')
    if obj['boot_id']!='UNKNOWN':uuid.UUID(obj['boot_id'])
    if type(obj['pid_namespace_id']) is not str or (obj['pid_namespace_id']!='UNKNOWN' and not re.fullmatch(r'pid:\[[0-9]{1,21}\]',obj['pid_namespace_id'])):raise ValueError('Invalid PID namespace identity')
    for key,cap in (('identities',8192),('identity_errors',8192),('processes',64),('tmux',64),('known_files',16)):
        if type(obj[key]) is not list or len(obj[key])>cap:raise ValueError('Observer response outside bound')
    for row in obj['identities']:
        if type(row) is not dict or set(row)!={'pid','start_ticks','ppid','proc_state'}:raise ValueError('Invalid PID identity')
        if type(row['pid']) is not int or type(row['ppid']) is not int or not 0<row['pid']<2**31 or not 0<=row['ppid']<2**31:raise ValueError('Invalid PID')
        if type(row['start_ticks']) is not str or not re.fullmatch(r'[0-9]{1,21}',row['start_ticks']) or row['proc_state'] not in tuple('RSDZTWXxKPI'):raise ValueError('Invalid PID birth')
    def files(rows):
        if type(rows) is not list or len(rows)>16:raise ValueError('Invalid watched files')
        for f in rows:
            if type(f) is not dict or set(f)-{'path','size','mtime_ns','progress'} or not {'path','size','mtime_ns'}<=set(f) or not _allowed_remote_path(f['path'],root):raise ValueError('Unregistered file metadata')
            if any(type(f[k]) is not int or f[k]<0 for k in ('size','mtime_ns')):raise ValueError('Invalid file stat')
            if 'progress' in f:
                v=f['progress']
                if type(v) is not dict or set(v)!={'signals','counters'} or type(v['signals']) is not list or any(x not in ('COMPLETED','CHECKPOINT','FAILED','RUNNING','CRITICAL_STOP','ENTIRE_TASK_STOP_REQUIRED') for x in v['signals']):raise ValueError('Invalid progress enum')
                if type(v['counters']) is not dict or any(k not in ('step','epoch','iteration','progress') or type(n) is not int or not 0<=n<10**9 for k,n in v['counters'].items()):raise ValueError('Invalid progress counters')
    files(obj['known_files'])
    for p in obj['processes']:
        if type(p) is not dict or set(p)!={'pid','start_ticks','ppid','proc_state','cwd','exe_basename','script_basename','kind','cwd_git_head_commit','loaded_code_version','files','tmux_session_id','tmux_session_name'}:raise ValueError('Invalid process row')
        if not _allowed_remote_path(p['cwd'],root) or p['kind'] not in ('MONITOR','UNCLASSIFIED') or p['loaded_code_version']!='UNVERIFIED':raise ValueError('Unregistered process cwd')
        for k in ('exe_basename','script_basename','tmux_session_name'):
            if type(p[k]) is not str or not re.fullmatch(r'[A-Za-z0-9_.+-]{1,100}',p[k]):raise ValueError('Invalid process label')
        if p['tmux_session_id']!='UNKNOWN' and not re.fullmatch(r'\$[0-9]{1,9}',p['tmux_session_id']):raise ValueError('Invalid tmux identity')
        if p['cwd_git_head_commit']!='UNKNOWN' and not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',p['cwd_git_head_commit']):raise ValueError('Invalid source HEAD')
        if type(p['pid']) is not int or type(p['start_ticks']) is not str or type(p['ppid']) is not int or p['proc_state'] not in tuple('RSDZTWXxKPI') or not any(all(p[k]==i[k] for k in ('pid','start_ticks')) for i in obj['identities']):raise ValueError('Process identity not observed')
        files(p['files'])
    for p in obj['tmux']:
        if type(p) is not dict or set(p)!={'session_id','session_name','pane_pid'} or not re.fullmatch(r'\$[0-9]{1,9}',str(p['session_id'])) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',str(p['session_name'])) or type(p['pane_pid']) is not int:raise ValueError('Invalid tmux record')
    if any(type(pid) is not int or not 0<pid<2**31 for pid in obj['identity_errors']):raise ValueError('Invalid incomplete identity')
    return obj

def assess(previous,snapshot,transport):
    prior=(previous or {}).get('processes',[]);rows=[]
    if transport!='OK':
        return [{**p,'state':'UNKNOWN','reason':'TRANSPORT_UNVERIFIED','historical_metadata':True} for p in prior]
    identities={p['pid']:p for p in snapshot['identities']}
    current={(p['pid'],p['start_ticks']):p for p in snapshot['processes']}
    for p in snapshot['processes']:
        rows.append({**p,'state':'EXITED' if p['proc_state'] in ('Z','X','x') else 'LIVE','reason':'OBSERVED_IDENTITY','historical_metadata':False})
    same_boot=bool(previous and previous.get('boot_id') not in (None,'UNKNOWN') and previous.get('boot_id')==snapshot['boot_id'] and previous.get('pid_namespace_id') not in (None,'UNKNOWN') and previous.get('pid_namespace_id')==snapshot['pid_namespace_id'])
    for old in prior:
        if same_boot and (old['pid'],old['start_ticks']) in current:continue
        actual=identities.get(old['pid']);state='UNKNOWN';reason='IDENTITY_UNVERIFIED'
        if same_boot and actual:
            state='LIVE' if actual['start_ticks']==old['start_ticks'] else 'EXITED';reason='IDENTITY_ALIVE_CWD_UNVERIFIED' if state=='LIVE' else 'PID_REUSED'
        elif same_boot and snapshot['inventory_complete'] and old['pid'] not in snapshot['identity_errors']:
            state='EXITED';reason='SAME_BOOT_NAMESPACE_COMPLETE_PID_ABSENCE'
        rows.append({**old,'state':state,'reason':reason,'historical_metadata':True})
    return rows

def meaningful_fingerprint(report):
    def clean(value):
        if type(value) is dict:return {k:clean(v) for k,v in value.items() if k not in ('observed_at','seconds','process_helpers','proc_state','ppid')}
        if type(value) is list:return [clean(v) for v in value]
        return value
    return hashlib.sha256(json.dumps(clean(report),sort_keys=True,separators=(',',':')).encode()).hexdigest()

def observe(root_runtime,configuration=None,runner=None):
    """Called only with the controller's already verified System.runtime, never a model path."""
    if not Path(root_runtime).is_absolute():raise ValueError('Trusted root runtime must be absolute')
    root_runtime=no_links(Path(root_runtime));runtime=_runtime_path(root_runtime)
    runtime.mkdir(parents=True,exist_ok=True);run=runtime/'runs'/uuid.uuid4().hex;run.mkdir(parents=True)
    execute=runner or winproc.run_owned;helpers=[]
    def started(pid,birth):
        if birth in (None,'UNKNOWN'):raise RuntimeError('Observer helper identity unknown')
        helpers.append({'pid':pid,'birth':birth});write_json(run/'owned-processes.json',helpers)
    keep=('SystemRoot','WINDIR','USERPROFILE','HOMEDRIVE','HOMEPATH','LOCALAPPDATA','APPDATA','PROGRAMDATA','TEMP','TMP','USERNAME','USERDOMAIN','SSH_AUTH_SOCK','SSH_AGENT_PID')
    child_env={key:os.environ[key] for key in keep if key in os.environ}
    child_env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
    def owned(argv,prompt,timeout):return execute(argv,prompt,runtime,child_env,timeout,started,256)
    previous=read_json(runtime/'last-success.json') if (runtime/'last-success.json').exists() else None
    old_report=read_json(runtime/'latest.json') if (runtime/'latest.json').exists() else None
    status='UNKNOWN';metadata={};snapshot=None;reason='CONFIGURATION_UNVERIFIED';host='UNKNOWN';cfg=None
    try:
        if configuration is None:
            path=no_links(root_runtime/'research-watch.json')
            configuration=read_json(path) if path.exists() else {'schema':1,'enabled':False}
        cfg=validate_configuration(configuration)
        if not cfg['enabled']:status='DISABLED';reason='OBSERVER_DISABLED'
        else:
            host=cfg['host_alias']
            rc,out,err,_=owned([SSH,'-G','-o','BatchMode=yes','-o','PermitLocalCommand=no',host],'',10)
            if rc:raise ValueError('CONFIG_PROBE_FAILED')
            metadata=config_metadata(out)
            rc,out,err,_=owned(command(cfg),REMOTE_PROBE,20)
            if rc:
                reason=('OWNED_TIMEOUT' if rc==1460 else 'HOST_KEY_UNVERIFIED' if 'host key verification failed' in err.lower() else 'AUTH_UNVERIFIED' if 'permission denied' in err.lower() else 'SSH_UNVERIFIED')
            elif len(out.encode('utf-8'))>MAX_RESPONSE_BYTES:reason='RESPONSE_BOUND_EXCEEDED'
            else:snapshot=validate_snapshot(json.loads(out),cfg);status='OK';reason='STATIC_READONLY_PROBE'
    except (OSError,ValueError,TypeError,KeyError,RuntimeError):reason='OBSERVATION_FAILED'
    observations=assess(previous,snapshot,status)
    report={'schema':1,'host':host,'observed_at':_utc(),'transport':status,'reason':reason,'ssh_metadata':metadata,
            'boot_id':snapshot['boot_id'] if snapshot else 'UNKNOWN','pid_namespace_id':snapshot['pid_namespace_id'] if snapshot else 'UNKNOWN','processes':observations,
            'known_files':snapshot['known_files'] if snapshot else [],'tmux':snapshot['tmux'] if snapshot else [],
            'process_helpers':helpers,'read_only':True,'model_calls':0,'actions_dispatched':0,
            'limits':{'remote_static_deadline_seconds':8,'ssh_owned_timeout_seconds':20,'process_scope':'cwd beneath configured research root only','loaded_code_version':'UNVERIFIED'}}
    report['fingerprint']=meaningful_fingerprint(report);report['changed']=not old_report or old_report.get('fingerprint')!=report['fingerprint']
    if snapshot:write_json(runtime/'last-success.json',snapshot)
    write_json(run/'report.json',report);write_json(runtime/'latest.json',report)
    return report
