import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import uuid
from researchops import research_observer as obs

REPO=Path(__file__).resolve().parents[1]
def configuration():
 return {'schema':1,'enabled':True,'host_alias':'research_test_host','read_root':'/data/approved_research','known_files':[],'monitor_scripts':['monitor_fixture.py'],'cadence_seconds':900}
def fixture(pid=123,birth='987',boot='11111111-2222-3333-4444-555555555555'):
 i={'pid':pid,'start_ticks':birth,'ppid':1,'proc_state':'S'}
 p={**i,'cwd':'/data/approved_research/repos/example','exe_basename':'python3','script_basename':'train.py','kind':'UNCLASSIFIED','cwd_git_head_commit':'a'*40,'loaded_code_version':'UNVERIFIED','files':[],'tmux_session_id':'UNKNOWN','tmux_session_name':'UNKNOWN'}
 return {'schema':1,'boot_id':boot,'pid_namespace_id':'pid:[4026533000]','inventory_complete':True,'identity_errors':[],'identities':[i],'processes':[p],'tmux':[],'known_files':[]}

class ObserverTests(unittest.TestCase):
 def setUp(self):
  self.boundary=REPO/'.runtime/stages234-development/observer-candidate/test-tmp';self.boundary.mkdir(parents=True,exist_ok=True)
  self.base=Path(tempfile.mkdtemp(prefix='observer-',dir=self.boundary))
 def tearDown(self):
  p=self.base.resolve()
  if self.boundary.resolve() not in p.parents:raise RuntimeError('Unowned cleanup')
  shutil.rmtree(p)
 def test_fixed_host_no_user_shell(self):
  for host in ('-oBadOption','research_test_host; whoami','research_test_host -R 1'):
   with self.assertRaises(ValueError):obs.command({**configuration(),'host_alias':host})
  command=obs.command(configuration())
  import shlex
  remote=shlex.split(command[-1]);self.assertEqual(['/usr/bin/python3','-I','-B','-'],remote[:4]);self.assertEqual(configuration()['read_root'],remote[4]);self.assertEqual(configuration()['known_files'],json.loads(remote[5])['known_files'])
  for flag in ('StrictHostKeyChecking=yes','UpdateHostKeys=no','ClearAllForwardings=yes','BatchMode=yes','ControlPath=none','PermitLocalCommand=no','ProxyCommand=none','SendEnv=-*'):
   self.assertIn(flag,command)
 def test_config_filters_secret_identity_and_unknown_endpoint(self):
  raw='hostname 10.23.45.67\nport 2222\nuser research\nidentityfile FAKE_SECRET_NEVER_SAVE\nremoteforward [127.0.0.1]:17890 [127.0.0.1]:10809\n'
  row=obs.config_metadata(raw);self.assertNotIn('FAKE_SECRET',json.dumps(row));self.assertEqual(['2222'],row['port'])
  with self.assertRaises(ValueError):obs.config_metadata(raw.replace('10.23.45.67','203.0.113.4'))
 def test_unknown_network_never_proves_death(self):
  before=fixture();rows=obs.assess(before,None,'UNKNOWN');self.assertEqual('UNKNOWN',rows[0]['state'])
 def test_same_identity_live_and_reused_old_identity_exited(self):
  old=fixture();now=fixture(birth='999');rows=obs.assess(old,now,'OK')
  self.assertEqual(['LIVE','EXITED'],[r['state'] for r in rows]);self.assertEqual('PID_REUSED',rows[1]['reason'])
 def test_exit_requires_same_boot_complete_inventory(self):
  old=fixture();now=fixture();now.update(processes=[],identities=[])
  self.assertEqual('EXITED',obs.assess(old,now,'OK')[0]['state'])
  now['inventory_complete']=False;self.assertEqual('UNKNOWN',obs.assess(old,now,'OK')[0]['state'])
 def test_same_boot_different_pid_namespace_cannot_prove_exit(self):
  old=fixture();now=fixture();now.update(processes=[],identities=[],pid_namespace_id='pid:[4026534000]')
  self.assertEqual('UNKNOWN',obs.assess(old,now,'OK')[0]['state'])
 def test_reboot_or_permission_error_is_unknown(self):
  old=fixture();now=fixture();now.update(processes=[],identities=[],boot_id='99999999-2222-3333-4444-555555555555')
  self.assertEqual('UNKNOWN',obs.assess(old,now,'OK')[0]['state'])
  now['boot_id']=old['boot_id'];now['identity_errors']=[123];self.assertEqual('UNKNOWN',obs.assess(old,now,'OK')[0]['state'])
 def test_snapshot_rejects_raw_content_and_unregistered_paths(self):
  row=fixture();row['processes'][0]['argv']='FAKE_RAW_SECRET'
  with self.assertRaises(ValueError):obs.validate_snapshot(row,configuration())
  row=fixture();row['processes'][0]['cwd']='/root/private'
  with self.assertRaises(ValueError):obs.validate_snapshot(row,configuration())
  row=fixture();row['known_files']=[{'path':'/data/approved_research/progress.log','size':4,'mtime_ns':7,'progress':{'signals':['FAKE_RAW_SECRET'],'counters':{}}}]
  with self.assertRaises(ValueError):obs.validate_snapshot(row,configuration())
 def test_snapshot_accepts_state_switch_same_birth(self):
  row=fixture();row['processes'][0]['proc_state']='R';self.assertIs(row,obs.validate_snapshot(row,configuration()))
 def fake_runner(self,snapshot,rc=0):
  def runner(argv,prompt,cwd,env,timeout,started,memory):
   self.assertEqual(256,memory);self.assertNotIn('OPENAI_API_KEY',env);started(os.getpid(),'FIXTURE-BIRTH')
   if '-G' in argv:return 0,'hostname 10.23.45.67\nport 2222\nuser research\n','',.01
   self.assertEqual(obs.REMOTE_PROBE,prompt);self.assertEqual(obs.command(configuration()),argv)
   return rc,json.dumps(snapshot) if snapshot else '', 'Permission denied FAKE_SECRET' if rc else '',.01
  return runner
 def test_repeated_unchanged_observation_no_models_or_dispatch(self):
  a=obs.observe(self.base,configuration(),runner=self.fake_runner(fixture()));b=obs.observe(self.base,configuration(),runner=self.fake_runner(fixture()))
  self.assertTrue(a['changed']);self.assertFalse(b['changed']);self.assertEqual(0,b['model_calls']);self.assertEqual(0,b['actions_dispatched'])
 def test_failure_after_success_preserves_identity_unknown_and_drops_raw(self):
  obs.observe(self.base,configuration(),runner=self.fake_runner(fixture()));row=obs.observe(self.base,configuration(),runner=self.fake_runner(None,255))
  self.assertEqual('UNKNOWN',row['processes'][0]['state']);self.assertNotIn('FAKE_SECRET',json.dumps(row));self.assertEqual('AUTH_UNVERIFIED',row['reason'])
  self.assertTrue((self.base/'research-watch/last-success.json').is_file())
 def test_owned_timeout_is_unknown(self):
  obs.observe(self.base,configuration(),runner=self.fake_runner(fixture()));row=obs.observe(self.base,configuration(),runner=self.fake_runner(None,1460))
  self.assertEqual('OWNED_TIMEOUT',row['reason']);self.assertEqual('UNKNOWN',row['processes'][0]['state'])
 def test_output_root_requires_trusted_absolute_runtime(self):
  with self.assertRaises(ValueError):obs.observe(Path('relative-runtime'),configuration(),runner=self.fake_runner(fixture()))
 def test_disabled_default_never_invokes_ssh(self):
  with patch.object(obs.winproc,'run_owned',side_effect=AssertionError('Disabled observer invoked SSH')):
   row=obs.observe(self.base)
  self.assertEqual('DISABLED',row['transport']);self.assertEqual(0,row['model_calls'])
 def test_runtime_config_rejects_shell_and_credential_roots(self):
  for root in ('/','/root/project','/data/research/.ssh','/data/research/.env.live','/data/a;echo','/data/../private'):
   with self.assertRaises(ValueError):obs.validate_configuration({**configuration(),'read_root':root})
  with self.assertRaises(ValueError):obs.validate_configuration({**configuration(),'known_files':['/data/unregistered/status.json']})
 def test_static_probe_never_reads_environ_or_starts_research(self):
  for forbidden in ('/environ','os.environ','os.system(','eval(','exec(','Popen(','nvidia-smi','kill-session','srun ','sbatch ','pip install'):
   self.assertNotIn(forbidden,obs.REMOTE_PROBE)
  self.assertIn("['/usr/bin/tmux','list-panes'",obs.REMOTE_PROBE)

if __name__=='__main__':unittest.main()
