"""Verified standalone deterministic publisher; no Codex/Claude invocation."""
import argparse,json,sys
from pathlib import Path
sys.dont_write_bytecode=True
from researchops import delivery_agent as d
ROOT=Path(__file__).resolve().parent
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('command',choices=('serve','enroll','reconcile','status','verify','disable','enable','stop-when-idle'));p.add_argument('--task');p.add_argument('--authorize-draft',action='store_true');a=p.parse_args()
 d.verified_activation(d.RUNTIME,ROOT)
 if a.command=='serve':d.serve(d.RUNTIME,ROOT)
 elif a.command=='enroll':print(json.dumps(d.enroll(d.RUNTIME,ROOT,a.task,a.authorize_draft)))
 elif a.command=='reconcile':print(json.dumps(d.reconcile(d.RUNTIME,ROOT,a.task,a.authorize_draft)))
 elif a.command=='status':print(json.dumps(d.load(d.RUNTIME/'worker-delivery/service.json')))
 elif a.command=='verify':print(json.dumps(d.verified_activation(d.RUNTIME,ROOT)))
 else:print(json.dumps(d.control(d.RUNTIME,ROOT,a.command)))
