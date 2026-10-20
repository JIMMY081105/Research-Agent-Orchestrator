"""Fixed desktop bundle entry point. Only the owned UI service can be recovered."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

sys.dont_write_bytecode = True
from researchops.dashboard_bundle import safe_path, read_small_json
from researchops import desktop_bundle as bundle
from researchops.desktop_recovery import decide, valid_receipt
from researchops.dashboard_state import process_identity

ROOT = Path(r"E:\Github\Building-Generation-Validation")
RUNTIME = ROOT / ".runtime"
URL = "http://127.0.0.1:8765"
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None

def probe(runtime, expected_hash):
    receipt_path = safe_path(runtime / "desktop/service/service.json")
    receipt = read_small_json(receipt_path) if receipt_path.exists() else None
    response = None
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(URL + "/api/status", timeout=2) as stream:
            data = stream.read(1024 * 1024 + 1)
            if len(data) <= 1024 * 1024:
                response = json.loads(data)
    except (OSError, ValueError):
        pass
    port_open = False
    if response is None:
        try:
            with socket.create_connection(("127.0.0.1", 8765), timeout=.5):
                port_open = True
        except OSError:
            pass
    state = decide(receipt, response, expected_hash, process_identity, port_open)
    result = {"state": state, "url": URL, "read_only": True}
    if valid_receipt(receipt):
        result.update(service_pid=receipt["pid"], service_birth=receipt["birth"], service_bundle=receipt["source_sha256"])
    return result

def ensure(source, runtime, expected_hash):
    activation = read_small_json(runtime / "desktop/activation.json")
    if (activation.get("owner") != bundle.OWNER or activation.get("sha256") != expected_hash
            or safe_path(activation.get("source", "")) != source):
        raise ValueError("DESKTOP_ACTIVATION_MISMATCH")
    result = probe(runtime, expected_hash)
    if result["state"] != "STARTABLE":
        return result
    script = source / "tools/desktop.ps1"
    run = subprocess.run([POWERSHELL, "-NoProfile", "-NonInteractive", "-File", str(script),
                          "-Mode", "EnsureService", "-ExpectedHash", expected_hash],
                         capture_output=True, text=True, timeout=20, creationflags=0x08000000)
    if run.returncode:
        try:
            reason = json.loads(run.stdout).get("state", "SERVICE_START_REFUSED")
        except ValueError:
            reason = "SERVICE_START_REFUSED"
        return {"state": reason if reason in ("SERVICE_DISABLED", "SERVICE_START_REFUSED") else "SERVICE_START_REFUSED", "read_only": True, "url": URL}
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = probe(runtime, expected_hash)
        if result["state"] == "READY":
            result["started_via_scheduler"] = True
            return result
        if result["state"] not in ("STARTABLE", "OWNED_PROCESS_UNRESPONSIVE"):
            return result
        time.sleep(.4)
    return {"state": "SERVICE_START_TIMEOUT", "url": URL, "read_only": True}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("source", "bundle", "freeze", "verify", "serve", "ensure"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--runtime", type=Path, default=RUNTIME)
    parser.add_argument("--expected-hash")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--app", type=Path)
    parser.add_argument("--build", type=Path)
    parser.add_argument("--tests", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--trigger", choices=("scheduled-desktop",), default="scheduled-desktop")
    args = parser.parse_args()
    source, runtime = safe_path(args.root), safe_path(args.runtime)
    if runtime != RUNTIME:
        raise ValueError("WRONG_DESKTOP_RUNTIME")
    if args.command == "source":
        print(json.dumps(bundle.source_manifest(source))); return
    if args.command in ("verify", "serve", "ensure"):
        record = bundle.verify(source.parent, args.expected_hash or "")
        if args.command == "verify":
            print(json.dumps({"verified": True, "owner": bundle.OWNER, "sha256": record["sha256"]})); return
        if args.command == "ensure":
            result = ensure(source, runtime, record["sha256"])
            print(json.dumps(result)); return 0 if result["state"] == "READY" else 2
        from researchops.dashboard_server import serve
        serve(runtime, read_small_json(source / "config/live.json"), source / "assets", record["sha256"],
              args.trigger, directory=runtime / "desktop/service", composer=True)
        return
    if source != Path(__file__).resolve().parent or not all((args.config, args.assets, args.app, args.build)):
        raise ValueError("DESKTOP_BUILD_INPUTS_REQUIRED")
    config = read_small_json(args.config)
    if args.command == "bundle":
        print(json.dumps(bundle.bundle_manifest(source, config, args.assets, args.app, args.build))); return
    if not args.tests or not args.review:
        raise ValueError("CURRENT_DESKTOP_EVIDENCE_REQUIRED")
    record, target = bundle.freeze(source, runtime, config, args.assets, args.app, args.build, args.tests, args.review)
    print(json.dumps({"owner": bundle.OWNER, "sha256": record["sha256"], "source_sha256": record["source_sha256"],
                      "bundle": str(target), "source": str(target / "source"), "app": str(target / "app/SceneControl.exe")}))

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        reason = str(error) if isinstance(error, ValueError) and str(error).replace("_", "").isupper() else "DESKTOP_START_FAILED"
        print(json.dumps({"state": reason, "read_only": True}))
        raise SystemExit(2)
