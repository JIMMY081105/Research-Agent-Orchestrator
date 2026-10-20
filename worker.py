"""Fixed native Codex worker service; UI service restarts cannot restart these tasks."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from researchops import desktop_bundle as bundle
from researchops.worker_store import OWNER, Store, WorkerError, save, utc

RUNTIME = Path(r"E:\Github\Building-Generation-Validation\.runtime")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("serve", "status"))
    parser.add_argument("--runtime", type=Path, default=RUNTIME)
    parser.add_argument("--expected-hash", required=True)
    parser.add_argument("--trigger", choices=("scheduled-worker",), default="scheduled-worker")
    args = parser.parse_args()
    runtime = bundle.safe_path(args.runtime)
    source = bundle.safe_path(Path(__file__).parent)
    if runtime != RUNTIME:
        raise WorkerError("WRONG_WORKER_RUNTIME")
    bundle.verify(source.parent, args.expected_hash)
    activation = bundle.read_small_json(runtime / "worker/activation.json")
    if (activation.get("owner") != OWNER or activation.get("sha256") != args.expected_hash
            or bundle.safe_path(activation.get("source", "")) != source):
        raise WorkerError("WORKER_ACTIVATION_MISMATCH")
    if args.command == "status":
        print(json.dumps(Store(runtime).status(), ensure_ascii=True)); return 0
    import msvcrt
    directory = bundle.safe_path(runtime / "worker")
    directory.mkdir(parents=True, exist_ok=True)
    with bundle.safe_path(directory / "service.lock").open("a+b") as lock:
        if lock.seek(0, 2) == 0:
            lock.write(b"0"); lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise WorkerError("WORKER_SERVICE_ALREADY_RUNNING") from None
        from researchops.worker_service import Service
        Service(runtime, args.expected_hash, args.trigger).run()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"state": "PAUSED", "reason": str(error) if isinstance(error, WorkerError) else "WORKER_START_FAILED"}))
        raise SystemExit(2)
