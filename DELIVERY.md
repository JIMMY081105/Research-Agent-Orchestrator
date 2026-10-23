# Reviewed task results in GitHub

The composer can explicitly request a Draft PR in the private
`JIMMY081105/Building-Generation-Validation` results repository. The software
source remains in `Research-Agent-Orchestrator`; no main update or merge exists.

Only new opted-in tasks are enrolled. Historical tasks, including rejected
publications and running research, are never adopted or retried. Codex prepares
`REPORT.md` in its owned task workspace. Optional `delivery.json` has exactly
`{"files":["figure.png"]}` for additional reviewed reports/images. No raw model
streams, credentials, research source code, checkpoint directories or arbitrary
commands are published. Claude reviews that exact workspace before delivery.

The publisher is deterministic and never invokes AI. It verifies the task,
request, final answer, independently reviewed content hashes and real PASS
receipt, then reuses the independently accepted immutable GitHub bridge. The
bridge allows only a new UUID branch, review artifacts and one Draft PR, with
remote readback. A model PASS alone is insufficient. This is artifact delivery,
not physics acceptance, scientific READY or user approval.

Every external-write intent is persistent. An uncertain crash, stale artifact,
authentication/network failure or conflicting remote state pauses delivery;
there is no blind replay, second model review or alternative publication route.
Existing accepted files and all audit/budget records remain untouched. No-change
checks call neither AI nor GitHub. Disabling this publisher pauses future
admissions and does not stop researchers or the Codex worker.

Publisher code, tests and documentation have a separate content-addressed
snapshot and independent source approval. Its current-user hidden Windows task
is `BGV-Result-Delivery-v1`, with an OS/application single-instance lock, no
password, SYSTEM, wake request or dependency on the current chat/terminal.

Use `tools/delivery.ps1 -Mode Status`, `Disable`, `Enable`, `StopWhenIdle` or
`Uninstall` for this publisher alone. Disable and Enable preserve old pause
records; Uninstall refuses a live owned process and removes only this task.
The pending index contains only uncompleted deliveries; completed intent/state
history stays available for UI readback and cannot starve new submissions.

For a paused individual delivery, `delivery_agent.py reconcile --task <UUID>
--authorize-draft` can requeue only a proven failure before any GitHub intake or
outbox was created, with a current unchanged PASS. It preserves the old pause in
a reconciliation receipt. An uncertain external write remains paused: inspect
the existing bridge with read-only `reconcile` and do not recreate the task or PR.
Global Enable never silently clears an individual delivery failure.
