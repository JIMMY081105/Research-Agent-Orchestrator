"""GitHub result-review bridge CLI; publication always requires an explicit package hash."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from researchops import github_review as bridge


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=bridge.MAIN)
    p.add_argument("--runtime", type=Path)
    p.add_argument("--expected-source-sha")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    for name in ("prepare", "publish", "reconcile"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--id", required=True)
        if name != "prepare":
            cmd.add_argument("--expected-hash", required=True)
        if name == "publish":
            cmd.add_argument("--authorize-draft-pr", action="store_true")
    args = p.parse_args()
    try:
        root = Path(__file__).resolve().parent
        if bridge.safe(args.repo) != bridge.safe(bridge.MAIN) or args.runtime and bridge.safe(args.runtime) != bridge.safe(bridge.MAIN / ".runtime/github"):
            raise bridge.BridgeError("RUNTIME_OR_REPOSITORY_NOT_AUTHORIZED")
        if args.expected_source_sha and bridge.manifest(root)["sha256"] != args.expected_source_sha:
            raise bridge.BridgeError("SOURCE_HASH_CHANGED")
        app = bridge.Bridge(args.repo, args.runtime, root)
        if args.command == "status":
            result = app.connection()
        elif args.command == "prepare":
            with bridge.lock(app.runtime):
                result = app.prepare(args.id)
        elif args.command == "publish":
            result = app.publish(args.id, args.expected_hash, args.authorize_draft_pr)
        else:
            result = app.reconcile(args.id, args.expected_hash)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except bridge.BridgeError as error:
        print(json.dumps({"state": "BLOCKED", "reason": str(error)}, ensure_ascii=True))
        return 2
    except (OSError, KeyError, ValueError, TypeError):
        print(json.dumps({"state": "BLOCKED", "reason": "INVALID_LOCAL_STATE"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
