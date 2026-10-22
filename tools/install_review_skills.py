"""Install only this project's three original review skills; never overwrite unknown skills."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import uuid
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from researchops.dashboard_bundle import safe_path,canonical,digest,read_small_json
from researchops.review_context import SKILLS

OWNER='ResearchAgentOrchestrator.ReviewSkills.v1'
RECEIPT='.research-agent-orchestrator.json'


def install(root, homes, *, check=False):
    items=[]
    for engine,home in homes.items():
        base=safe_path(Path(home)/'skills')
        for name in SKILLS:
            source=safe_path(Path(root)/name);raw=source.read_bytes();ident=source.stem
            if len(raw)>16384 or f'name: {ident}\n' not in raw.decode('utf-8').replace('\r\n','\n'):
                raise ValueError('SKILL_SOURCE_INVALID')
            directory=safe_path(base/ident)
            if directory.parent!=base:raise ValueError('SKILL_INSTALL_BOUNDARY')
            target=safe_path(directory/'SKILL.md');receipt=safe_path(directory/RECEIPT)
            if directory.exists():
                if (not receipt.is_file() or not target.is_file()
                        or read_small_json(receipt).get('owner')!=OWNER
                        or read_small_json(receipt).get('sha256')!=digest(target.read_bytes())):
                    raise ValueError('UNKNOWN_OR_EDITED_SKILL_RETAINED')
            elif check:raise ValueError('SKILL_NOT_INSTALLED')
            items.append((engine,directory,target,receipt,raw))
    # Preflight every destination before changing any of the six skill copies.
    for engine,directory,target,receipt,raw in items:
        if check:
            if target.read_bytes()!=raw:raise ValueError('INSTALLED_SKILL_STALE')
            continue
        safe_path(directory);directory.mkdir(parents=True,exist_ok=True)
        record=dict(owner=OWNER,name=directory.name,sha256=digest(raw),installed_at=dt.datetime.now(dt.timezone.utc).isoformat())
        for path,data in ((target,raw),(receipt,canonical(record)+b'\n')):
            temporary=safe_path(path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp'))
            with temporary.open('xb') as stream:stream.write(data)
            safe_path(path);temporary.replace(path)
    return [dict(engine=e,name=d.name,path=str(t),sha256=digest(raw),verified=t.read_bytes()==raw)
            for e,d,t,r,raw in items]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    args=parser.parse_args()
    homes={'codex':Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex'))),'claude':Path.home()/'.claude'}
    try:
        result=install(ROOT,homes,check=args.check)
        print(json.dumps(dict(success=True,skills=result,model_calls=0)));return 0
    except (OSError,ValueError) as error:
        print(json.dumps(dict(success=False,reason=str(error) if isinstance(error,ValueError) else 'SKILL_INSTALL_IO_ERROR')));return 2


if __name__=='__main__':raise SystemExit(main())
