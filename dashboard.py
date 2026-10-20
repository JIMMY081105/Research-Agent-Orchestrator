"""Scene Control: separate read-only local UI; does not execute research tasks."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from researchops.dashboard_bundle import (OWNER, bundle_manifest, freeze, read_small_json,
                                         safe_path, source_manifest, validate_config, verify)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("source", "bundle", "preview", "freeze", "serve", "verify"))
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--runtime", default=r"E:\Github\Building-Generation-Validation\.runtime")
    parser.add_argument("--config")
    parser.add_argument("--assets")
    parser.add_argument("--tests")
    parser.add_argument("--review")
    parser.add_argument("--expected-hash")
    parser.add_argument("--trigger", choices=("manual-preview", "scheduled-ui"), default="manual-preview")
    parser.add_argument("--run-seconds", type=int)
    args = parser.parse_args()
    root, runtime = safe_path(args.root), safe_path(args.runtime)
    if args.command == "source":
        print(json.dumps(source_manifest(root))); return
    if args.command in ("verify", "serve"):
        bundle = root.parent
        manifest = verify(bundle, args.expected_hash or "")
        if args.command == "verify":
            print(json.dumps({"owner": OWNER, "verified": True, "sha256": manifest["sha256"]})); return
        config = read_small_json(root / "config/live.json")
        assets = root / "assets"
        from researchops.dashboard_server import serve
        serve(runtime, config, assets, manifest["sha256"], args.trigger)
        return
    if not args.config or not args.assets:
        parser.error("--config and --assets required")
    config = validate_config(read_small_json(args.config))
    assets = safe_path(args.assets)
    if args.command == "bundle":
        print(json.dumps(bundle_manifest(root, config, assets))); return
    if args.command == "freeze":
        if not args.tests or not args.review:
            parser.error("freeze needs --tests and --review")
        manifest, target = freeze(root, runtime, config, assets, args.tests, args.review)
        print(json.dumps({"owner": OWNER, "bundle": str(target), "source": str(target / "source"),
                          "source_sha256": manifest["source_sha256"], "sha256": manifest["sha256"]})); return
    if not args.run_seconds or not 5 <= args.run_seconds <= 300:
        parser.error("preview must be bounded to 5..300 seconds")
    # An explicit bounded development preview, never used by the installed task.
    from researchops.dashboard_server import serve
    serve(runtime, config, assets, "DEVELOPMENT_PREVIEW", "manual-preview", args.run_seconds)


if __name__ == "__main__":
    main()
