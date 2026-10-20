"""Run every dashboard regression and bind actual results to all component sources."""
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
from researchops.dashboard_bundle import source_manifest, safe_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    before = source_manifest(ROOT)
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), "test_dashboard_*.py")
    discovered = suite.countTestCases()
    capture = io.StringIO()
    started = dt.datetime.now(dt.timezone.utc)
    result = unittest.TextTestRunner(stream=capture, verbosity=2).run(suite)
    after = source_manifest(ROOT)
    same = before == after
    output = safe_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    record = {"started_at": started.isoformat(), "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "source_sha256": before["sha256"], "source_unchanged": same,
              "discovered": discovered, "tests_run": result.testsRun,
              "success": result.wasSuccessful() and same and discovered == result.testsRun,
              "failures": [{"test": str(test), "traceback": trace[-4000:]} for test, trace in result.failures],
              "errors": [{"test": str(test), "traceback": trace[-4000:]} for test, trace in result.errors],
              "skipped": [str(test) for test, _ in result.skipped],
              "scope": "COMPLETE_DASHBOARD_REGRESSION_NO_REAL_MODEL_OR_REMOTE_CALLS"}
    output.write_text(json.dumps(record, indent=2), encoding="utf-8")
    output.with_suffix(".txt").write_text(capture.getvalue(), encoding="utf-8")
    print(json.dumps({key: record[key] for key in ("source_sha256", "discovered", "tests_run", "success", "source_unchanged")}))
    return 0 if record["success"] else 1


if __name__ == "__main__": raise SystemExit(main())
