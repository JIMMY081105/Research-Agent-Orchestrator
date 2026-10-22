"""Complete UI and desktop regression; no models, SSH or task registration."""
import argparse
import datetime as dt
import io
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from researchops.desktop_bundle import source_manifest

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    before = source_manifest(ROOT)
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    suite = unittest.TestSuite()
    for pattern in ('test_dashboard*.py', 'test_desktop*.py', 'test_worker*.py', 'test_mission*.py',
                    'test_review*.py', 'test_token_usage.py', 'test_adapter_diagnostics.py'):
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern=pattern))
    count = suite.countTestCases()
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    unchanged = before == source_manifest(ROOT)
    record = dict(started_at=started, completed_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                  source_sha256=before['sha256'], source_unchanged=unchanged, discovered=count,
                  tests_run=result.testsRun, success=result.wasSuccessful() and unchanged,
                  failures=[str(t) for t, _ in result.failures], errors=[str(t) for t, _ in result.errors],
                  skipped=[str(t) for t, _ in result.skipped], scope='COMPLETE_UI_AND_DESKTOP_REGRESSION_NO_MODELS_OR_REMOTE_CALLS')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2), encoding='utf-8')
    args.output.with_suffix('.txt').write_text(output.getvalue(), encoding='utf-8')
    print(json.dumps({key: record[key] for key in ('success', 'source_sha256', 'discovered', 'tests_run', 'source_unchanged')}))
    return 0 if record['success'] else 2

if __name__ == '__main__':
    raise SystemExit(main())
