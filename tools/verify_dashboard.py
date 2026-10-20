"""Actual localhost browser/status evidence, never a mock task or model dispatch."""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--evidence", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"http://127\.0\.0\.1:[0-9]{4,5}", args.url):
        parser.error("Only the local dashboard is allowed")
    directory = Path(args.evidence).resolve(); directory.mkdir(parents=True, exist_ok=True)
    def get(path, **kwargs):
        request = urllib.request.Request(args.url + path, **kwargs)
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, dict(response.headers), response.read()
    code, headers, data = get("/api/status")
    state = json.loads(data)
    checks = {"status_200": code == 200, "read_only": state.get("read_only") is True,
              "database_ok": state.get("controller", {}).get("database") == "OK",
              "both_engines_present": set(state.get("engines", {})) == {"codex", "claude"},
              "gpu_actual": state.get("gpu", {}).get("status") == "OK",
              "no_cors": "Access-Control-Allow-Origin" not in headers,
              "no_store": headers.get("Cache-Control") == "no-store"}
    for name, path, kwargs, expected in (
        ("post_refused", "/api/status", {"method": "POST", "data": b"{}"}, 405),
        ("origin_refused", "/api/status", {"headers": {"Origin": "https://example.invalid"}}, 403),
        ("host_refused", "/api/status", {"headers": {"Host": "example.invalid"}}, 403),
        ("runtime_file_refused", "/.runtime/machine.json", {}, 404),
        ("dispatch_refused", "/api/submit", {"method": "POST", "data": b"{}"}, 405),
    ):
        try:
            result = get(path, **kwargs)[0]
        except urllib.error.HTTPError as error:
            result = error.code
        checks[name] = result == expected
    initial_checks = state["service"]["gpu_checks"]
    for _ in range(40):
        latest = json.loads(get("/api/status")[2])
    checks["http_reads_do_not_probe_gpu"] = latest["service"]["gpu_checks"] - initial_checks <= 1
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    arguments = [edge, "--headless=new", "--disable-gpu", "--disable-background-networking",
                 "--disable-extensions", "--disable-sync", "--no-first-run", "--no-default-browser-check",
                 "--user-data-dir=" + str(directory / "edge-profile"), "--window-size=1200,1450",
                 "--virtual-time-budget=4000", "--screenshot=" + str(directory / "dashboard.png"),
                 "--dump-dom", args.url]
    run = subprocess.run(arguments, capture_output=True, encoding="utf-8", errors="replace",
                         timeout=35, creationflags=0x08000000)
    (directory / "dashboard.dom.html").write_text(run.stdout, encoding="utf-8")
    checks["browser_exit_success"] = run.returncode == 0
    checks["browser_has_live_page"] = ('data-connection' in run.stdout and "DESIGN DEMO" not in run.stdout
                                        and "本次为监控视图" in run.stdout)
    checks["browser_received_state"] = bool(re.search(r'data-code-state[^>]*>IDLE<', run.stdout)
                                              or re.search(r'data-code-state[^>]*>RUNNING<', run.stdout)
                                              or re.search(r'data-code-state[^>]*>PAUSED<', run.stdout))
    checks["browser_uk_time_labels"] = bool(re.search(r"UK / (?:BST|GMT)", run.stdout))
    checks["browser_budget_utc_labeled"] = bool(re.search(r"UTC\s*账本日|账本日\s*UTC", run.stdout))
    checks["screenshot_saved"] = (directory / "dashboard.png").is_file()
    report = {"observed_at": dt.datetime.now(dt.timezone.utc).isoformat(), "url": args.url,
              "scope": "REAL_READ_ONLY_LOCAL_UI", "success": all(checks.values()), "checks": checks,
              "engines": {key: value.get("state") for key, value in state.get("engines", {}).items()},
              "controller": state.get("controller"), "gpu": state.get("gpu"),
              "model_requests_started": 0, "task_dispatches": 0,
              "evidence": str(directory / "dashboard.png")}
    (directory / "BROWSER-VERIFICATION.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"success": report["success"], "checks": checks,
                      "engines": report["engines"], "evidence": str(directory)}, ensure_ascii=False))
    raise SystemExit(0 if report["success"] else 1)


if __name__ == "__main__": main()
