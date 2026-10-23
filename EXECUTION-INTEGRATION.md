# Bounded execution integration

The approved Flask/Jinja/HTMX chat layout is connected to the accepted separately owned Codex worker. Bounded local Task/Standard execution is deployed as of 2026-10-23; this does not certify autonomous research, GPU dispatch or scientific acceptance.

## Behavior

An explicit task creates a persistent unique request and native session, executes Codex with the selected supported model and native permission policy, snapshots the owned workspace, and starts a fresh tool-disabled Claude review. Concrete REWORK findings return to the same task for at most two repairs. Attempts and charges are retained. Polling reads state; it does not call models. Auth/network/quota failures pause.

Review sends complete differences and necessary context against a verified accepted baseline. The task-review packet is limited to 24,576 bytes. Oversized input pauses before reserving another model call; split large work into explicit stages. Source review is a separately bounded operation. Single-turn JSON judgments are validated locally for exact keys, binding, verdict and issue limits. Usage comes from provider receipts; unavailable usage remains UNKNOWN. No savings percentage is guaranteed.

The UI requires same-origin loopback requests, signed browser ownership, a CSRF nonce and browser-issued request IDs. Status, approval and cancel are bound to the submitting browser and actual task/session. Text analysis always starts a fresh native read-only session. Full Access intentionally removes OS directory confinement; approval mode retains the native workspace policy. Neither selection grants new research or publication authority.

## Limits that remain

- A Claude workspace review is not deterministic scientific acceptance. Check actual artifacts separately; an honest failure report does not fulfill the requested deliverable.
- Sensitive workspace paths are refused before reading. A workspace containing secrets is not supported for review. Never move credentials into an owned review workspace.
- Large responses or workspaces can exceed the review limit and remain paused. No truncation, automatic budget increase or endless retry occurs.
- Generic Goal/Plan/Fast, arbitrary long-running research continuation, GPU dispatch and future automatic GitHub publishing are not accepted features of this integration.
- Real CLI development harnesses bypass only the production admission adapter, use actual native tools/reviews/shared charging, and stop their own retained process jobs. They are not natural Windows schedule receipts or installed UI acceptance.

## Installation and operations

Use a fixed source manifest, complete passing tests and a matching independent PASS before freezing. `tools/deploy_execution.py freeze` refuses a stale/missing PASS. Only then may the frozen `tools/worker.ps1 -Mode Install` register the independently named current-user task. Do not use an edited checkout as the running worker snapshot.

The frozen worker exposes Status, Disable, Enable, StopWhenIdle and Uninstall modes. Disable pauses new admissions and disables only its own task; active work is preserved. Enable retains historical pause records. Resolve `source` from `E:\Github\Building-Generation-Validation\.runtime\worker\activation.json`, then invoke that source's `tools\worker.ps1 -Mode Status`, `Disable` or `Enable`. Uninstall refuses a running worker; use StopWhenIdle and verify ownership/state before uninstalling only this task.

The current immutable worker bundle is `e8ca7a2e16f73c098a4f2d574ec0edfa90df10f524d41f0571600f2edfd8a0be`. Its source manifest passed 288 regressions and independent audit-7 closure PASS against the previous full audit's three findings. Later frontend branding/readiness changes are separately tested and explicitly exempt from Claude frontend review; they do not alter the running worker snapshot. Real desktop submission, installed REWORK/repair/PASS, natural scheduler startup and Disable/Enable receipts are retained privately in `.runtime/ui-connection-20261023`. Earlier failed tests/reviews remain retained.

GitHub software changes belong in Research-Agent-Orchestrator. Selected private research/review reports belong in Building-Generation-Validation. A Draft PR is for user review; nothing merges automatically. Private runtime, raw histories, credentials and complete CLI outputs are excluded.
