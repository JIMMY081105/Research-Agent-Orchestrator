# Native Codex execution and approvals

The user authorized a separate real Codex executor with selectable Full Access and
Approval needed. It uses the installed Codex App Server's private stdio protocol,
existing ChatGPT subscription login, existing skill discovery and native command/
file approval messages. There is no paid API fallback, permission-bypass CLI flag,
change to global config/auth, or adoption of an old interactive session.

In Mission choose **Codex 工作**, write a task and send. A new task creates an
isolated directory under `.runtime/worker/workspaces/<UUID>`. Replies and native
command/file statuses update immediately; these turns do not wait for the legacy
15-minute observation schedule. **文本分析** uses a fresh native read-only session.

The capability release pins the already installed desktop CLI by absolute path and
SHA-256 in the worker activation, without changing npm, global config or login.
Models/efforts/Fast come from its actual catalog. New conversations default to
`gpt-6.1-sol` and `xhigh` when available. Fast forwards the advertised `priority`
service tier through the existing subscription; it can consume quota faster.

Plan forwards native `collaborationMode: plan` with built-in instructions and an
enforced read-only sandbox. Its public plan text is distinct from hidden reasoning.
Goal uses native persisted thread goals. Every productive continuation is a new
durable reviewed turn; review/approval/accounting remain mandatory. Pause during
review prevents the next dispatch; Resume retains native usage and objective.
No-action stages suppress automatic continuation. Goal mode currently has no
final-stage automatic Draft PR delivery; use Task for that delivery contract.

The task sidebar is scoped to the signed browser profile with durable local
ownership. Select a task to restore its conversation and Codex/Claude board.
Visualisation selects the discovered skill explicitly and displays bounded
task-owned HTML/PNG/JPEG; HTML has a sandboxed origin and no network/form access.

## Permission modes

- **Approval needed**: native `workspace-write` and `untrusted` approval policy.
  Normal trusted reads may proceed; non-trusted commands and permission crossings
  ask the user. Approvals show exact command/cwd/reason or requested permissions.
  The UI supports allow once, decline, and answers to native user questions.
- **Full Access**: native `danger-full-access` and `never` approval policy. This
  removes local sandbox restrictions; it is not a protected-directory sandbox.
  Task instructions and existing prohibitions still apply, including no unspecified
  research writes/GPU/publication or interference with old work. Choosing this mode
  is the user's explicit grant for the subsequent turn, not a global config edit.

The selected mode is recorded with each immutable turn input. It changes the next
turn only, never an in-flight turn or an outstanding approval. Full Access does not
turn a pending approval into an automatic acceptance. Reusing an id with different
input/mode is rejected. Only this application's own recorded native thread id may
be resumed; there is no "latest session" lookup.

Existing Codex skills are discovered through `skills/list` and can be selected.
Selected skills are passed as native skill input items, not just copied markdown.
The host supplies standing rules and a workspace AGENTS template; INFRA remains at
its original absolute path and is read before server work. Credentials are never
copied into the repository. The host disables recursive built-in multi-agent
features and instructs the worker not to call Codex/Claude/other AI recursively.

## Independent service and review

`BGV-Codex-Worker-v1`, owner `BGV.Windows.CodexWorker.v1`, is a separate current-user
Limited/Interactive Windows task with an absolute fixed snapshot and pythonw.
It starts at logon/its one installation due time, stays running, does not wake the
computer and ignores duplicate launches. No account password or SYSTEM account is
used. It has its own OS file lock, process birth records and private kill-on-close
Windows Job created before native execution begins. Only owned process handles are
closed. Job containment is a lifetime/resource limit, not filesystem isolation.

Closing or upgrading the desktop UI does not stop this worker service. UI and worker
have separate activations and may retain different accepted immutable versions.
The core observer/task database/settings remain unchanged except append-only model
call ledger rows. No idle polling invokes a model. Shared Claude reviews remain at
most 50 per UTC day; Codex has no local daily invocation cap. A native user turn is
one charged Codex invocation; internal model/tool iterations are not represented as
separate CLI calls by this local ledger.

After completion, a fresh tool-disabled Claude reviews the exact prompt, visible
final response and local task-workspace manifest/content. **REVIEW_PASS** applies
to that workspace only. It does not certify external scripts, remote jobs, physics,
navigation, image semantics or scientific READY. Missing/oversized/changed evidence
remains unverified. The user removed the arbitrary 24 KiB review-packet gate:
required content is preserved, new-file additions are included once even after
REWORK, and the three fixed review skills direct review to changes and necessary
context instead of a repository scan. Fresh reviewers still receive necessary
unchanged source and all prior findings; REWORK is never an approved baseline.
`NEEDS_CONTEXT` records exact missing context and pauses without consuming a repair.
File/credential checks, shared accounting and process safety still apply.
A review failure requests rework; it does not silently create an
unbounded repair loop. Auth/network/quota failures pause review without API fallback
or automatic retry. The original analysis queue retains its own bounded repair flow.

Native reasoning/analysis items and raw provider diagnostics are not saved. UI
event records contain only visible messages, command metadata, file paths, approvals
and review results, with common credential signatures redacted/rejected. Full native
Codex session history stays in its normal user profile; this host does not copy it.

## Recovery and maintenance

Record explicit task/session/turn ids and PID birth time. Following a service crash,
first verify the old native process is gone. Live or unknown original identities
block a second worker. Running/approval/review turns become
`INTERRUPTED_NEEDS_RECONCILIATION`; they are not automatically replayed. Remote jobs
may continue independently and must be inspected before any manual continuation.
Stale approvals expire; they cannot authorize a new turn. A one-hour running-turn
timeout requests interruption of that exact owned native turn, never an old job.

`tools/worker.ps1` supports Install, Status, Disable, Enable, StopWhenIdle and Uninstall.
Disable pauses new admissions and queued starts and disables future launches;
it retains a running turn and its human approval replies. Enable explicitly resumes
admissions/review and preserves old pause records rather than resetting call charges.
StopWhenIdle requests shutdown only after the current turn; queued inputs remain.
Uninstall refuses a
running/queued service rather than terminating work. The UI's **停止本轮** interrupts
only the currently recorded native turn. Real sleep/reboot/network disruption is
not induced during acceptance; local execution pauses while Windows sleeps/off.

This feature does not wire Factory80's existing jobs into the new worker or authorize
future GitHub publication. Its acceptance must include real native commands, a real
pending approval with both allow/deny controls, full-mode execution, explicit policy
switching, independent Claude review, native UI controls, fixed snapshots and actual
scheduled worker start. Mocks or a dropdown alone do not prove deployment.
