# BGV Scene Control — native Windows app

Open **BGV Scene Control** from the Desktop or Start menu. This compiled
Windows Forms application embeds WebView2 in its own window, icon and taskbar
entry. It never opens an Edge/Chrome tab or uses browser app mode. The existing
WebView2 Runtime and .NET Framework compiler are reused; SDK DLLs are pinned
in `config/desktop-dependencies.json` and installed only under `.runtime`.

The default window is maximized. Four panels keep key status values on screen;
history/details expand inside panels. David/Lucy animations remain visual
feedback, not inference proof. Times use Europe/London, with automatic BST/GMT;
audit timestamps and the shared review budget day stay UTC.

## Restart, sleep and re-open

The fixed desktop/start-menu entry uses `SceneControlLauncher.exe`. On every open it reads the current activation, verifies the complete accepted snapshot and its own matching binary, then opens that version. It prevents an old pinned version from silently staying in use after an upgrade. No model is called during connection.

The native window opens first, verifies its fixed package and checks its own
service. When the service has exited, opening requests a start of the exact
owned Windows task. A live matching PID is never killed or duplicated. Another
version, occupied unknown port, unreadable identity or explicit Disable is
reported, not taken over. A Retry button needs no PowerShell commands. Resume
rechecks the connection and freshness with bounded attempts, never model calls.

The background task uses the current user, Limited/Interactive, hidden pythonw,
logon and missed-start recovery, IgnoreNew, NoWake and three bounded crash
restarts. It runs independently of the chat, terminal and native window. Closing
the app leaves monitoring running. Windows cannot collect while asleep or off;
on wake, old samples remain stale until real collection succeeds. E: and the
installed paths must remain available. A remote-access failure affects GPU
freshness, not the native app's ability to show its status/error screen.

## Operations and scope

`tools/desktop.ps1 -Mode Open|Status|Disable|Enable|Uninstall` manages only this
component. Disable/Enable affect future launches. Uninstall verifies ownership,
removes only the dedicated service task and matching shortcuts, and retains
runtime/evidence. It does not uninstall the core or stop research sessions.

New service: `BGV-SceneControl-Service-v1`. Installation disables/stops only the
exact verified old standalone UI task `BGV-ResearchOps-UI-v1`, retaining its task,
snapshot and evidence to prevent duplicate sampling. The core 15-minute task
`BGV-ResearchOps-Observe-v1` remains unchanged.

Status collection remains read-only. The Mission composer accepts only the
existing authorized `analyze_text` action: a question, supplied reference text
and a writer (Codex or Claude), with the other engine reviewing. It never grants
filesystem tools, research writes, GPU compute, GitHub publication, new API
billing or credential access. Submission persists one UUID and input; retries
cannot create duplicate tasks. The existing controller owns execution, pauses,
budgets, rework limits and acceptance. A submitted task may wait for the next
scheduled check or an existing engine pause; submission is not completion.
Native navigation and requests are fixed to localhost; host objects, web messages, permissions,
downloads and external windows are disabled. WebView2 uses its own runtime profile.

Enter a question and paste supporting material in Mission, select the writer,
then submit. The response shows its task ID and state; task feedback displays
the structured answer and independent review. This entry is for supplied-text
analysis and draft proposals. It cannot yet browse for assets, execute an
unrestricted master prompt or authorize a production research goal. Avatars
retain their original aspect ratio. Wide windows display more task and review
information instead of stretching portraits or scaling the whole page.

## Build and acceptance

Complete source, tests, templates, compiled executable, three pinned DLLs, icon,
configuration and approved avatar bytes are bound in an independent desktop
manifest. build.json binds compiler inputs and output hashes. A current complete
regression and fresh tools-disabled Claude review are required before freezing.
The original desktop-feature audit cycle and all calls are retained. It defaults
to three reviews; the explicit user extension authorizes ten TOTAL in the same
cycle, including failures and prior calls. No new cycle, reset or refund is permitted.
The old exhausted UI cycle is retained and unchanged. All reviews share the existing 50/UTC-day
ledger, with no refunds or resets.

Local evidence is in `.runtime/desktop`. Fixture layout tests are explicitly
separate from installed-service tests. Physical sleep, reboot and disconnects
are not induced around old work; owned-service failure/re-open tests verify
the recovery paths. Actual untested conditions are listed in deployment reports.

References: [WebView2 distribution](https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution),
[WebView2 security](https://learn.microsoft.com/microsoft-edge/webview2/concepts/security).
