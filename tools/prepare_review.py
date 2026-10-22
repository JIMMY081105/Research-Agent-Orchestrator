"""Prepare a bound source-review packet without any model call or budget charge."""
import argparse
import json
from pathlib import Path
import sys
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from researchops import desktop_bundle as b, review_context


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--tests',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--baseline-snapshot',type=Path)
    parser.add_argument('--baseline-review',type=Path)
    parser.add_argument('--scope',choices=('auto','full','delta'),default='auto')
    parser.add_argument('--include',action='append',default=[])
    args=parser.parse_args()
    try:
        source=b.source_manifest(args.root)
        packet,criteria,metrics=review_context.prepare(args.root,source,args.tests,snapshot=args.baseline_snapshot,
            review_path=args.baseline_review,scope=args.scope,include=args.include)
        if source!=b.source_manifest(args.root):raise ValueError('REVIEW_SOURCE_BINDING_CHANGED')
        target=b.safe_path(args.output)
        if target.exists():raise ValueError('REVIEW_OUTPUT_EXISTS_RETAINED')
        target.mkdir(parents=True)
        (target/'package.json').write_bytes(b.canonical(packet)+b'\n')
        (target/'criteria.txt').write_text(criteria,encoding='utf-8',newline='\n')
        result=dict(status='PREPARED_NOT_REVIEWED',source_sha256=source['sha256'],scope=packet['scope'],
                    selected_files=len(packet['selected_paths']),total_files=len(source['files']),
                    package_sha256=b.digest(b.canonical(packet)),model_calls=0,**metrics)
        (target/'PREPARED.json').write_bytes(b.canonical(result)+b'\n')
        print(json.dumps(result));return 0
    except (ValueError,OSError,KeyError) as error:
        reason=str(error) if isinstance(error,ValueError) else 'PREPARATION_FAILED'
        print(json.dumps(dict(status='DEFERRED',reason=reason,model_calls=0)));return 2


if __name__=='__main__':raise SystemExit(main())
