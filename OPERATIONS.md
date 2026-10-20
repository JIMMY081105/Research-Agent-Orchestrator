# Operations

## Status and task submission

`tools/control.ps1 status` reads current database states even while a model call runs.
Routine status and daily packages keep accepted queue history but mark current evidence
UNVERIFIED/EVIDENCE_RECHECK_DEFERRED. They do not rehash full scientific dependencies.
`projects` retains strict evidence checks, and explicit `daily-report --verify-science`
performs the expensive trusted scientific revalidation. All dispatch, dependency and
snapshot acceptance gates continue to use strict verification. A deferred display cannot
authorize work or certify readiness; historical timestamps and small content hashes are
references only.
Each completed monitoring tick writes `.runtime/STATUS.json` and `.runtime/STATUS.md`.
The wrapper invokes only the activated snapshot, its expected
hash and the one repository runtime. `submit` accepts a UUID, listed action, literal
JSON input file and optional writer (`codex` or `claude`). `analyze_text` accepts a
literal object with `text` and `question`; citations must match the supplied text.
It reads no other files and cannot execute embedded instructions as commands. Source/input/acceptance,
allowed actions, resource limits and workdir are recorded in each task's `spec.json`.
Only explicit queued tasks invoke models; monitoring alone never does. `run` automatically
advances up to six ready stages (check -> execute -> review -> repair -> verify) under a
shared deadline. The schedule calls `run`, with no dependence on an interactive terminal
or on an existing Claude window. Each CLI call has a new recorded session ID. An idle
queue uses no model calls. The system does not create or split arbitrary research goals.

States: `QUEUED -> EXECUTING -> AWAITING_REVIEW -> REVIEWING -> ACCEPTED`.
Rejected calculations or review lead to `REWORK`, then `NEEDS_ATTENTION` at two reworks.
Login/network/quota/timeout (and an optional local engine cap) lead to `WAITING_CODEX` or
`WAITING_CLAUDE`: the stage, prior state and whether the CLI had started are recorded in
`task_waits`, only that engine is paused, and state, wait record, engine pause and event
commit together. `resume --engine claude|codex` returns those tasks to their stage once the
original process is confirmed gone (at most three resumes per task); an executed artifact is
kept and only the pending stage runs. Other failures (tool attempt, invalid output, cycle
limit) lead to `PAUSED_*` and a global pause, with the pause and its event committed together.
A scene workflow whose room fits no measured template ends `NEEDS_ATTENTION`
(`NO_FITTING_TEMPLATE`) with a `no-fit-report.json` and no model call. Interrupted or ambiguous crash attempts lead to
`NEEDS_ATTENTION` with a reason (`START_INTERRUPTED_NO_REPLAY`, `ORPHAN_*`,
`AMBIGUOUS_COMPLETION_NO_REPLAY`). Model output that fails validation is not stored.

`pause` pauses future dispatch without killing a running model or any old task. It may
report Busy while the current short bounded invocation finishes; retry after it exits.
`resume` checks original identities and legacy observations before enabling future
dispatch. It does not silently retry failed tasks. After correcting a login/network
problem externally, `retry UUID` explicitly requeues a `PAUSED_*` task, checking its
original process is gone and consuming a rework round. Quarantined ambiguous attempts
cannot be retried with this command: inspect evidence and submit a new authorized ID
only after reconciling the old attempt. Never use “latest session” to recover.
Pause, resume and explicit retry write `DISPATCH_PAUSED`/`DISPATCH_RESUMED` queue events.

`tools` lists registered tools and skills with pinned and current bindings. `show --id UUID`
lists a task's state, wait, attempts, files, artifact checks (re-validated from disk now),
review and acceptance.

## Evidence

- `.runtime/preflight/`: absolute paths, installed help, login booleans and legacy inventory.
- `.runtime/legacy-registry.json`, `observation.json`: passive known PIDs and UNKNOWN fields.
- `.runtime/queue.sqlite3`: queue, attempts, durable call budget and event history.
- `.runtime/tasks/UUID/`: input/source spec, per-attempt prompts, process identities,
  final structured results, independent review and acceptance checks.
- `.runtime/test-results.json`: current-source tests, including deliberately rejected results,
  duplicate dispatch, crash ambiguity, network/login/quota simulation, stale review and limits.
- `.runtime/independent-review/`: complete fixed-hash source and evidence supplied to a new
  tool-free Claude subprocess, its session identity and verdict.
- `.runtime/snapshots/HASH/source/`, `activation.json`: accepted runtime version and bindings.
- `.runtime/receipts/`, `scheduler-state.json`: application receipt and independent scheduler
  LastRunTime/LastTaskResult. A manual tick is not a time-trigger receipt.
- `.runtime/DEPLOYMENT-REPORT.md`: final true status, scope and remaining limitations.

No evidence is put in Git. UTC is used in records. The monthly interaction archive
is updated using the pre-existing `F:\Personal Data\_archive_system\ai_archive.py annotate`.

## Build and install a revised version

1. Verify current directory, origin and changes; use a local development branch.
2. Configure only `.runtime/machine.json` from `config/machine.example.json`, using
   native executable absolute paths. Never place credential files here.
3. Inspect legacy work and register confirmed metadata read-only; keep unknowns explicit.
4. Run `tools/run_tests.py`; then submit and process a small real Codex-written,
   Claude-reviewed task. Use `researchops.py run` to advance both stages and any authorized task reworks.
5. Run `researchops.py audit --tests ABSOLUTE_TEST_RESULTS_PATH --reviewer codex|claude`,
   choosing the CLI that did not author the revision. Fix any issues and repeat validation,
   maximum two audit rework rounds since the current activation (failed or crashed audits
   count). Any source change requires new evidence. A runtime from before the durable
   audit counter is migrated once: every retained `independent-review/` attempt (failed,
   crashed or without result) is charged to the current cycle; unreadable or inconsistent
   evidence, or a missing counter after cycle events, refuses the audit instead of using 0.
   Audits outside this command are not program rounds; they are listed in the migration event.
6. Run `researchops.py freeze --tests ABSOLUTE_TEST_RESULTS_PATH`. Freeze refuses stale
   tests/approval and lacks-current-source real dual-CLI evidence.
7. From the accepted snapshot run `tools/schedule.ps1 -Mode Install`. Existing same-name
   tasks are never overwritten. First trigger is one minute later, then every 15 minutes
   (repetition interval PT15M; PT10M is the per-run execution time limit).
8. Wait for actual time-trigger execution; inspect scheduler and application receipts,
   ensure success, exact source hash and scheduler parent provenance, then record DEPLOYED.

When the program audit counter is exhausted, an upgrade needs an explicit user-authorized
cycle. From the development tree (`researchops.py` in the repository root):
`authorize-cycle --cycle-id UUID --task-id TASK --authorization-file FILE --reviewer codex`
(`TASK` is the ID the single acceptance task must later be submitted with),
then `audit --tests FILE --reviewer codex --cycle UUID`. `--audits N` (1-3, default 1) records how many
audits the user authorized for the cycle: a REWORK reopens it only while rounds remain; failure,
timeout or invalid output closes it. The allowance cannot be raised by re-registering. After PASS, open a maintenance window with
`tools/schedule.ps1 -Mode Disable` so the old snapshot cannot take the new-source task,
`submit --id TASK --cycle UUID ...` the one non-sensitive task and run two manual `tick` calls. If it is
not ACCEPTED, `tools/schedule.ps1 -Mode Enable` restores the old schedule unchanged.
Otherwise uninstall the old schedule with its accepted script, run
`freeze --tests FILE --cycle UUID`, and install from the new snapshot. A live cycle that can
no longer complete (failed or exhausted acceptance task, withdrawn authorization) is closed
with `close-cycle --cycle-id UUID --reason-file FILE` once none of its processes can still
be running; consumed allowances are kept.

For an upgrade, uninstall the old schedule using its existing accepted script before
replacing activation. To roll back after activation, uninstall the new schedule with the
new snapshot's script, restore the previous `activation.json` (kept in the new activation's
`previous_activation` and in `snapshots/OLD/accepted.json`) and install from the old
snapshot. Keep all evidence/snapshots. Development edits do not hot-reload.
Manual validation calls share the same persistent daily model budget as scheduled work.
The internal Python API is for trusted local development; Windows user write access to
this repository/runtime is the administrative trust boundary, not a multi-user service.

## Uninstall only this system

Use the accepted snapshot's `tools/schedule.ps1 -Mode Uninstall`. Ownership requires
the exact description, interpreter, snapshot arguments and workdir. A mismatch fails
without changing the task. The command unregisters only this schedule, leaves currently
running work to finish, and retains runtime evidence, queue and snapshots. It never
stops experiments, deletes repositories or alters VPN/archive tasks.

## Continuous repair authorization and daily review cap

The current user authorization sets `daily_review_limit` to 50 shared source/task reviews
per UTC day. Read `status` for `reviews_today`, `review_limit`, `reviews_remaining` and
engine pauses; historical charges are retained. Execution calls have no extra local count
cap while existing subscription quotas still apply. No login, billing or global environment
is changed. Every review reserves its slot atomically before launch, including failed calls.
A task refused for the daily review budget enters WAITING_REVIEW_BUDGET, preserves its
artifact, and only becomes review-ready on the next UTC day if still current; user pauses,
ambiguous processes and engine pauses continue to block dispatch. This is not a counter reset.

New explicit source-repair authorization uses `authorize-cycle ... --continuous --reviewer
claude`. It never reopens a historical closed cycle or changes the legacy program counter.
A REWORK may be followed by repairs, tests and a new source audit; changing just a test
timestamp does not authorize another call. Source audit service failures park in AUDIT_WAIT.
After the service issue is actually resolved, `resume-audit --cycle-id UUID --reason-file FILE`
checks the old process and returns a new `tests` evidence path for the next `audit` command.
Original failed evidence and every charge remain unchanged. At most three such resumes.
The operator still freezes/installs only after fixed-source independent approval plus a real
accepted task. The unattended schedule never edits or upgrades its own source.

For maintenance, use the currently accepted snapshot's `tools/schedule.ps1 -Mode Disable`
and `-Mode Enable`. Inspect the exact action first; do not run a candidate schedule script
against a different activation. Older accepted scripts that lack these modes require native
Disable/Enable only after verifying description, executable, exact arguments and working
directory against the old activation. Do not stop any existing process. A disabled schedule
will not drain queued work; `pause` independently blocks dispatch inside the application.

The manual `tools/verify_live_rework.py` verification uses the real persistent ledger and
both real subscription CLIs. It transparently asks the first Codex call for an incomplete
but grounded draft. The ordinary Claude reviewer must reject it without an instructed
verdict. The production drain must then forward its bound issues, repair the same task and
obtain PASS. A mistaken first PASS fails this negative control; no record is deleted or
rewritten to manufacture success. This is separate from the unmodified real scene task.
