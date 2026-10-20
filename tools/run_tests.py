"""Run all fail-capable tests in isolated processes; retain current-source evidence."""
import argparse
import concurrent.futures
from pathlib import Path
import sys
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/"tests"))
from researchops.integrity import manifest, write_json
from researchops.core import utc


def test_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from test_ids(item)
        else:
            yield item.id()


def run_group(names, log_path):
    """Separate processes keep unittest mocks and temporary queues from crossing groups."""
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    with Path(log_path).open("w", encoding="utf-8") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    value = {"tests_run": result.testsRun, "success": result.wasSuccessful(),
             "failures": [{"test": str(t), "trace": msg} for t, msg in result.failures],
             "errors": [{"test": str(t), "trace": msg} for t, msg in result.errors],
             "skipped": [str(t) for t, _ in result.skipped]}
    write_json(Path(log_path).with_suffix(".json"), value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=3)
    args = parser.parse_args()
    (ROOT/".runtime/tests").mkdir(parents=True, exist_ok=True)
    run = ROOT/".runtime/test-workers"/str(uuid.uuid4())
    run.mkdir(parents=True)
    before = manifest(ROOT)
    names = list(test_ids(unittest.defaultTestLoader.discover(str(ROOT/"tests"))))
    started, results = time.monotonic(), []
    groups = [names[i::args.workers] for i in range(args.workers)]
    if args.workers == 1:
        results.append(run_group(groups[0], run/"worker-0.txt"))
    else:
        # These run repository tests in isolated queues; no live model or remote job dispatch.
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
            pending = {pool.submit(run_group, group, str(run/("worker-%d.txt" % i))): i
                       for i, group in enumerate(groups)}
            for future in concurrent.futures.as_completed(pending):
                result = future.result()
                results.append(result)
                print("Test group %d: %d tests, success=%s" %
                      (pending[future], result["tests_run"], result["success"]), flush=True)
    after = manifest(ROOT)
    count = sum(r["tests_run"] for r in results)
    evidence = {"time": utc(), "source_sha256": before["sha256"],
                "source_unchanged": before == after, "tests_run": count,
                "discovered": len(names), "workers": args.workers,
                "success": bool(names) and count == len(names) and before == after
                           and all(r["success"] for r in results),
                "failures": [v for r in results for v in r["failures"]],
                "errors": [v for r in results for v in r["errors"]],
                "skipped": [v for r in results for v in r["skipped"]],
                "seconds": round(time.monotonic()-started, 3), "worker_evidence": str(run)}
    write_json(ROOT/".runtime/test-results.json", evidence)
    write_json(run/"test-results.json", evidence)
    print({k: evidence[k] for k in ("success", "tests_run", "source_unchanged", "seconds")})
    return 0 if evidence["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
