"""Summarize reported numeric usage from private evidence; old missing usage stays unknown."""
import argparse
import contextlib
import json
import os
import sqlite3
from pathlib import Path
import sys
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from researchops.dashboard_bundle import safe_path
from researchops.token_usage import safe_usage


def summarize(runtime):
    runtime=safe_path(runtime)
    ledger={}
    if (runtime/'queue.sqlite3').exists():
        with contextlib.closing(sqlite3.connect(safe_path(runtime/'queue.sqlite3').as_uri()+'?mode=ro',uri=True)) as db:
            ledger={row[0]:row[1] for row in db.execute('SELECT c.id,e.engine FROM calls c LEFT JOIN call_engines e ON e.call=c.id')}
    records={ident:None for ident in ledger};thread_records={}
    excluded={'.git','.venv','snapshots','source','work','assets','checkpoints','node_modules','old-release-backup'}
    examined=0
    for folder,dirs,files in os.walk(runtime,followlinks=False):
        dirs[:]=[d for d in dirs if d not in excluded and not Path(folder,d).is_symlink() and not Path(folder,d).is_junction()]
        for name in files:
            if name not in ('result.json','failure.json','token-usage.json'):continue
            path=safe_path(Path(folder)/name);examined+=1
            if examined>10000:raise ValueError('USAGE_REPORT_SCAN_LIMIT')
            if path.stat().st_size>2*1024*1024:continue
            try:record=json.loads(path.read_bytes())
            except (OSError,ValueError):continue
            if type(record) is not dict:continue
            evidence=record.get('evidence',{})
            if type(evidence) is not dict:continue
            usage=safe_usage(evidence.get('token_usage',record.get('token_usage')))
            ident=record.get('call_id') or (path.parent.name if path.parent.name in ledger else None) or evidence.get('requested_session_id') or evidence.get('session_id') or record.get('session_id')
            if not ident:continue
            if ledger and ident not in ledger:continue
            # Native snapshots are cumulative per thread; never sum them as per-turn costs.
            cumulative=bool(usage and usage['scope']=='THREAD_CUMULATIVE')
            target=thread_records if cumulative else records
            if cumulative:ident='thread:'+str(record.get('thread_id',ident))
            if type(ident) is not str or len(ident)>180:continue
            prior=target.get(ident)
            score=lambda u: (len(u['metrics']),sum(u['metrics'].values())) if u else (-1,-1)
            if ident not in target or score(usage)>score(prior):target[ident]=usage
    totals={};cumulative=[];unknown=0;models={};by_engine={}
    for ident,usage in records.items():
        engine=ledger.get(ident) or ('claude' if usage and usage['source']=='CLAUDE_RESULT' else 'codex' if usage else 'unknown')
        group=by_engine.setdefault(engine,dict(reported_calls=0,unknown_calls=0,metrics={}))
        if not usage or not usage['metrics']:
            unknown+=1;group['unknown_calls']+=1
        else:
            group['reported_calls']+=1
            for key,value in usage['metrics'].items():
                totals[key]=totals.get(key,0)+value
                group['metrics'][key]=group['metrics'].get(key,0)+value
        for item in usage['models'] if usage else []:
            values=models.setdefault(item['model'],{})
            for key,value in item['metrics'].items():values[key]=values.get(key,0)+value
    for ident,usage in thread_records.items():
        cumulative.append(dict(thread=ident[7:],metrics=usage['metrics']))
    return dict(status='REPORTED_DATA_ONLY',time_scope='ALL_RETAINED_CALLS',estimated=False,records=len(records),unknown_records=unknown,
                ledger_binding='CALL_ID_VERIFIED' if ledger else 'ABSENT_UNVERIFIED_EVIDENCE_DIRECTORY',
                reported_call_totals=totals,by_engine=by_engine,per_model_reported=models,thread_cumulative=cumulative,
                semantics='Missing is UNKNOWN. Model-only counters are not added to aggregate totals. Codex cached input is a subset of input; Claude cache counters are separate. These are tokens, not subscription percentages or API bills.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,default=Path(r'E:\Github\Building-Generation-Validation\.runtime'))
    args=parser.parse_args()
    try:print(json.dumps(summarize(args.runtime)));return 0
    except (OSError,ValueError,sqlite3.Error):print(json.dumps(dict(status='USAGE_REPORT_UNAVAILABLE')));return 2


if __name__=='__main__':raise SystemExit(main())
