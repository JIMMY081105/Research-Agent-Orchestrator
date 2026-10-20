# Scene Control — local read-only dashboard

The approved four-panel cyberpunk interface uses David for Codex and Lucy for
Claude. Mission occupies two thirds of the upper row; GPU occupies one third.
Blinking is approximately 0.2 seconds and remains an interface effect, not proof
that a model is thinking. Plans and execution metadata are visible; hidden model
reasoning, raw prompts, task inputs and model output are never served.

User-facing timestamps use `Europe/London`, with automatic BST/GMT changes.
The UTC audit timestamps and shared review budget day remain unchanged; the
budget date is explicitly labelled UTC. No Windows system timezone is changed.

The dashboard is a separate standard-library Python service bound only to
`127.0.0.1`. It does not import or instantiate the controller, migrate its SQLite
database, acquire its execution lock, enqueue tasks or run Codex/Claude. It reads
the existing database using `mode=ro` and `query_only`, with bounded queries.
Only a live registered attempt with matching PID and creation time is labelled
running. Other interactive sessions are explicitly outside this observation
scope; process presence cannot establish inference activity or available quota.

The GPU collector runs a fixed read-only probe through the existing
`sunmingyuan1` SSH alias once every 30 seconds. The alias may point to a different
endpoint than an old runbook. It uses no forwarding or connection reuse and
never repairs VPN, modifies routes, starts work or touches remote watchkeepers.
Both `nvidia-smi` query exits are checked. A failed sample preserves its last
good values as DEGRADED, then STALE after 90 seconds. Zero utilization or an
empty GPU process list is not evidence that a research task has finished.

The browser reads the local cache every 2 seconds. Refreshing the page never
runs a model or remote probe. Host/Origin/Fetch-Site restrictions, a fixed
resource map, CSP, bounded request threads and timeouts protect the local
read-only service. No credential files, environments, command lines, arbitrary
runtime paths, directory listings or task-changing HTTP endpoints are exposed.
This is a single-user local tool, not a public Internet web server.

## Open and maintain

Use `tools/dashboard.ps1 -Mode Open` to open the installed local page, and
`-Mode Status` to inspect its dedicated task. `Disable` prevents future UI task
launches; it does not stop a currently running UI process or pause any research
work. `Enable` restores those launch triggers. `Uninstall` verifies exact task
ownership/action and stops/removes only `BGV-ResearchOps-UI-v1`, retaining all
runtime and evidence. The existing `BGV-ResearchOps-Observe-v1`, VPN and archive
tasks are never changed. Page “pause effects” freezes visual motion only.

Windows starts the UI under the current logged-in user's interactive token,
limited privilege, hidden `pythonw`, no password, no wake and no duplicate
instances. A logon trigger keeps it independent of the Codex app and terminal;
a one-time time trigger provides actual installation evidence. Sleep suspends
local collection. After wake or failed SSH, age/health must recover before
fresh online status is displayed. No new model/API subscription is required.

## Versions and verification

UI Python modules contain inspectable HTML/CSS/JavaScript strings, so they fit
the existing controller source allowlist without weakening it or changing the
accepted controller snapshot. The UI has its own explicit complete manifest,
including frontend strings, backend, tests, configuration template, frozen
machine configuration and the two approved avatar JPEGs. Generated avatar
artifacts remain unversioned in `.runtime/dashboard`; their expected SHA256s
are pinned in `dashboard_bundle.py`. No credential is copied to the repository.

The UI is frozen only after current-source tests and a fresh tool-free Claude
review bound to the complete source, live configuration, assets and test hash.
That review is charged once to the original shared 50-reviews-per-UTC-day
ledger, without refunds or rewriting any old cycles/tasks. The UI does not
replace the controller's accepted source or claim a new scientific acceptance.

Runtime reports, service PID/birth, health, natural scheduled-start receipts,
test and independent-review evidence are stored under `.runtime/dashboard`.
Independent component status is reported separately from core and scientific
readiness. No Github publish, research write or GPU experiment is enabled.

References: [Python HTTP handler API](https://docs.python.org/3.12/library/http.server.html),
[SQLite URI read-only connections](https://docs.python.org/3.12/library/sqlite3.html),
[character references](https://www.cyberpunk.net/en/edgerunners).
