# Authorization and acceptance policy

The later user request authorizes the separate native Codex execution component
in [WORKER.md](WORKER.md), including per-turn Approval needed and Full Access.
That component intentionally enables native tools/skills and real execution;
Full Access has no local filesystem sandbox and is never described as one.
It does not change the accepted legacy controller's read-only adapters, existing
jobs, global authentication, GPU/publication grants, or exhausted audit cycles.
Its native approvals must be actionable and bound to the exact owned thread,
turn and request. A UI permission switch applies only to the next turn.

The user additionally authorized the read-only local Scene Control UI described
in [DASHBOARD.md](DASHBOARD.md). It has no model, queue-mutation or experiment
control HTTP endpoints. Its separate source/config/assets manifest, fixed
snapshot, tests and independent Claude review govern its own deployment;
installing it does not upgrade or replace the accepted research controller.
The UI's one-off independent reviews append to the same 50/day call ledger
without changing old tasks, pauses or cycles. Its fixed read-only GPU telemetry
uses a separate connection without forwarding/reuse and does not change the
existing 15-minute research observer or reconnect VPN.

Software development belongs to `E:\Github\Research-Agent-Orchestrator`, with origin
`https://github.com/JIMMY081105/Research-Agent-Orchestrator.git`. Verify the exact
directory and origin before Git or installation operations. Software branch/PR
publication requires the user's explicit authorization; merging is never automatic.
Do not re-clone, initialize or replace `.git`. Existing accepted controller source
and research repositories remain unchanged. Persistent live data and accepted
desktop snapshots remain under `E:\Github\Building-Generation-Validation\.runtime`;
this does not authorize writing its research source. Unknown files and existing
experiments remain intact.

The shipped policy permits observation plus explicit `analyze_numbers`, `inspect_text`
and evidence-grounded `analyze_text` actions. Input is bounded literal JSON data, never
a command. The controller computes exact expected values or validates actual quote
offsets/content; the independent reviewer judges grounding and relevance.
No arbitrary process executable or workdir
can be supplied in a queued task; workdirs are generated per task under `.runtime/tasks`.
One application lock serializes controller, queue and audit changes. Writer and reviewer
are opposite CLIs. The writer returns JSON; only the controller writes the artifact.

Codex runs in a new ephemeral, read-only sandbox with user config ignored, provider
fixed to OpenAI subscription auth, shell/unified exec/code mode/apps/plugins/multi-agent
browser automation, computer use, image generation, hooks, skill discovery/install,
sleep and tool suggestions disabled, web search disabled, and approval set to never.
Claude runs in a fresh explicit UUID session with `--safe-mode`, `--tools ""`, no MCP
servers, slash commands disabled and `dontAsk` permissions. `--bare` is not used because
the installed help says it disables subscription OAuth. No bypass-all-permissions flag
is allowed. Unexpected tool events, session mismatches or invalid JSON are rejected.
The live Claude adapter supplies `--json-schema` and requires its native
`structured_output` object. A successful free-form `result` is never used as a fallback.
Known provider error types, HTTP statuses and explicit service messages can classify a
failed call; bare words such as credit or incidental numbers inside output cannot.
Ambiguous failures pause as CLI errors. Diagnostics store only fixed enums, booleans,
response type categories and known status codes, never raw error or model text.

API credential/provider environment variables are removed only from child environments;
global auth, environment and credential files are not changed or copied. Existing
subscription logins are reused. Network/auth/quota failures pause dispatch, without
paid-API fallback or automatic retry. The controller persists only final structured
artifacts and selected metadata; raw model event streams, stderr and hidden reasoning
are not written to logs. Inputs, prompts and review packages must never contain credentials.

The current explicit authorization allows at most 50 reviews per UTC day, shared across
independent source audits and both CLIs' task reviews, including all recognizable historical
charges lacking newer engine metadata. Execution calls do not consume review allowance;
all calls remain in the original ledger and none are refunded. The earlier 20-total-calls
policy remains historical evidence. Review-budget waiting tasks keep their artifact and
resume only the pending review on the next UTC day, subject to source/input/identity checks
and any user or engine pause. `engine_daily_limits`
may set an optional local cap per engine; both are null. Every call is still recorded in
the one ledger before launch (engine, task, stage, time, then attempt, session and result)
in one write transaction with any round or cycle charge. Real service limits surface as
login/quota/network/timeout errors: the task then waits at its stage for that engine
(`WAITING_CODEX`/`WAITING_CLAUDE`), only that engine is paused, and work for the other
engine continues. Nothing is retried automatically: `resume --engine` returns waiting tasks
to their stage after confirming the original process is gone, at most three times per
task, without re-running a completed execution, without consuming a rework round and
without clearing a user pause. Consumed calls and cycle allowances are never refunded.
Models and reasoning settings are not changed to save calls; no API billing, paid usage or
top-up is enabled. Codex cannot stand in for a Claude review. Task rework is at most two rounds
after the first attempt. Calls have a bounded wall time, private Windows Job Object
memory/process limits, and process creation identities. Each child is created suspended
and already a member of its private kill-on-close job (job membership is an attribute of
CreateProcess itself), then its identity is recorded and only then is it resumed. The
controller holds the only job handle, so its death at any point ends the child.
Timeout termination affects only that job. No process-tree scanning or killing old
experiments is allowed. Recovery quarantines interrupted or ambiguous attempts and never
replays automatically.

Registered tools (`config/tools.json`) are fixed adapters with schema-checked parameters.
They run in a fresh LPAC AppContainer with only registryRead capability, no network
capability and ALL APPLICATION PACKAGES opt-out. A copied runtime, registered research
source and inputs are granted RX; only this tool's output is granted Modify, excluding
WRITE_DAC and WRITE_OWNER. OWNER RIGHTS RC prevents implicit owner DACL rewriting.
The profile itself is made read-only and deleted after the private kill-on-close Job has
closed. All setup lives in the cleanup scope. Durable leases precede profile creation;
crash recovery first checks controller and child PID creation times and never redispatches
or kills an old process. Low integrity alone is not a filesystem sandbox. Legacy Low
labels may only be restored to Medium during migration. Only owned copied trees and
this attempt's profile/output ACLs are changed, never external research or Python ACLs.
Copy content hashes and original registered research listings are checked before/after.
OpenUSD authoring uses a deeper private scratch directory within the permitted output
to keep its accessible-prefix path probing inside that owned tree; no ancestor ACL is
opened. stdout+stderr share a fixed 8 MiB capture budget; overflow discards all raw text,
terminates only the private Job and returns OUTPUT_LIMIT. The scheduled drain shares one
480-second deadline across tools and CLI calls, within the schedule's 10-minute limit.
An audit pauses dispatch globally until its fixed-source result is PASS; normal task
service failures pause only the affected engine. A user pause survives a later audit PASS.
A scene report is re-validated against its tool outputs and pinned bindings again after the
reviewer returns, immediately before acceptance is written.
External source, package versions, scene inputs and skill files are pinned by hash; any
drift refuses submission and invalidates acceptance. Skills (`config/skills.json`,
`skills/*.md`) fix the tool order, the single model step and acceptance. A model chooses
only among values the orchestrator computed; it never supplies a command, path or tool.

Model output is validated (exact keys, types, sizes, IDs and bindings) before anything is
persisted. Rejected output is dropped: only a fixed failure kind and bounded process
metadata (engine, session IDs, exit code, duration) are kept, never the text.

Acceptance requires exit success, exact structured schema/value checks, actual artifact
content, independent review and current source/input/artifact bindings. File existence,
model claims, exit zero and HEAD alone are insufficient. Source manifests include
every allowlisted source, test, document, config and prompt template; files off the
allowlist and credential-like files are refused by path before reading, which stops
hashing, auditing, freezing and scheduled runs. Runtime machine config is separately bound
in deployment approval. Task source or input changes invalidate old reviews.

Installation requires passing current-source fail-capable tests, a fresh tool-free
audit of all source/test evidence by the CLI that did not author the revision, and
a real Codex -> Claude accepted task at the same source hash. The program audit counter
allows an initial plus at most two rework rounds per revision cycle; once exhausted it is
never reset or rewritten. Further work needs an explicitly authorized review cycle
(`authorize-cycle`): a new cycle ID recording the user's authorization text, its parent
state and fixed allowances of one audit and, only after PASS, one Codex execution and
one Claude review for the one acceptance task at the audited source. The task ID
registered with the cycle is that acceptance task's ID; `submit` refuses any other ID. Allowances are charged
with the budget slot; re-registering an ID adds nothing; one live cycle at a time; an
interrupted cycle audit is closed only when its process is verifiably gone, without
refund. Freeze re-verifies, at its final gate, the on-disk spec, input hash, artifact,
review, acceptance and attempt records against the queue database and the approval,
before any snapshot is published or activation written. A fixed snapshot is verified
before scheduling and at each scheduled run. No future unattended source upgrades. The new explicitly authorized `--continuous`
cycle has no legacy three-audit ceiling, but all reviews share the 50/day gate; old
cycles/counters remain untouched. Its acceptance task may execute/review at most three
times under the same ID. No-change re-audits cost zero model calls. Source service failures
enter AUDIT_WAIT and require identity-checked `resume-audit`, at most three times, with
new transparent retry evidence and no overwritten failed package. Normal task REWORK
feeds only the exact prior bound review issues to the writer as untrusted data; the same
authorized tools remain in effect. The scheduler advances task repairs, not arbitrary
source-code edits or installation of revised snapshots.

The independent `BGV-ResearchOps-Observe-v1` task uses the current Windows user's
interactive token at limited privilege, no saved password, hidden `pythonw`, absolute
paths, no wake, start when available, and ignore new concurrent instances. It needs
the user to remain logged in. It does not depend on the Codex app or a terminal parent.
Removal verifies exact ownership/action and unregisters only this task, retaining evidence.
VPN watchdog, archive sync and other scheduled tasks must never be modified.

Runtime DBs, locks, logs, prompts, full model outputs, evidence, snapshots, machine paths
and `.venv` are not committed. Credentials may not be copied anywhere in the repository.
F:\Personal Data is used only through the existing archive annotate utility; do not
create or use F:\ResearchOps as a new control location.

Project governance fixes Claude as coordinator/reviewer and Codex as worker. Only a
trusted local operator can approve the exact plan/rules/source digest. Model proposals
do not authorize commands, research writes, GPU use or publishing. Project-bound tasks
must use their dedicated project/goal/task output directory and accepted dependencies.
Changes invalidate approval; operations smoke tests are not scientific readiness.

The optional registered SSH observer is read-only and throttled to 900 seconds. It
never starts remote work or changes forwarding/VPN/routes. Missing connectivity means
UNKNOWN, not process death. Raw environments, argument strings and log tails are not saved.
Scientific readiness needs registered layer-specific target/positive/negative evidence;
local daily packages retain explicit missing gates/images and never publish themselves.
<!-- Desktop component authorization: additive feature, not a reset of UI reviews. -->
The native desktop feature uses one separate bounded three-review cycle under
the explicit desktop-app request. Prior UI reviews remain exhausted and retained;
all review attempts share the unchanged global 50-per-UTC-day ledger. Desktop
recovery may start only its verified UI service, respect Disable, and never kill
an unresponsive process or take over research, VPN, or unknown listeners.

The later explicit ten-total desktop grant preserves that original cycle and
all prior charges. Further user-authorized single-call additions use immutable
hash-linked JSON grant records in `worker/feature-audits/authorizations/` under
the private runtime. Every child adds exactly one, keeps the same original cycle
hash and binds its leaf source hash to the reviewed code. No reset, refund,
automatic grant creation, model-produced authorization or new cycle is allowed.
The manual operator must obtain explicit user consent before creating a child;
the record is evidence of that consent, not authentication of the person.
`tools/review_desktop.py` validates the entire chain in source and reserves calls
atomically against both its total and the shared 50/UTC-day ledger. Its trusted
review prompt reports the validated current total, so a historical ten-call
grant is not mistaken for a permanent ban on later explicit consent. A failed
or REWORK review remains charged and cannot approve a deployment. Temporary
runtime monkeypatches are not an upgrade or review-authorization mechanism.

The desktop Mission composer is explicitly authorized to submit only standalone
`analyze_text` tasks through the verified active controller. The operator may
choose either writer; the other engine reviews. This does not change project
governance or approve a production goal. UI writes require same-origin JSON and
a per-service CSRF token, bounded input, canonical UUID and persistent idempotent
admission. Status refreshes never dispatch work. Submission cannot resume a
paused engine, alter budgets or execute commands supplied in model output.
## Review context and usage evidence

The local preparer may use an independently approved baseline plus a complete
content-bound delta and explicit required context for defined UI paths. The
current revision still needs a new decision; the prior PASS is never carried
forward as current approval. Initial, sensitive and unknown changes require
full context. Missing context returns NEEDS_CONTEXT; context limits defer
without truncation or a model charge. New review grants are not inferred.

Numeric provider usage is retained on successful and failed native responses
when present. Missing is UNKNOWN, never fabricated as zero. Cumulative native
thread samples and per-model counts are not added to per-call aggregates.
No raw streams, hidden reasoning or credentials are stored for usage reporting.
Skills are review criteria, not permission, budget or deployment bypasses.
