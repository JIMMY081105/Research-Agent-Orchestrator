# Bounded source reviews and usage

Review preparation is local Python, not another model call. The three original
skills in `skills/diff-review.md`, `skills/risk-aware-review.md` and
`skills/token-budget.md` supply one review's criteria. They take ideas from
evidence-first review, behavioral testing and progressive disclosure, without
vendoring third-party prompts, installers or a graph/MCP service.

## Prepare without calling a model

From the software repository, use an absolute Python/script path:

```powershell
& 'C:\Python312\python.exe' -B 'E:\Github\Research-Agent-Orchestrator\tools\prepare_review.py' --tests '<current-tests.json>' --output '<new-private-runtime-directory>' --baseline-snapshot '<accepted-snapshot>' --baseline-review '<its-PASS-result.json>'
```

`auto` uses delta plus fixed cross-language context only for the defined UI
paths. Initial reviews, permissions, process management, queues, deployment,
review rules, new files and unknown changes require full source. `--scope delta`
refuses those changes rather than hiding them. `--include <manifest-relative-path>`
adds required context; `--scope full` explicitly expands the review.

All allowlisted current source hashes, the approved baseline source/review
hashes, complete changed paths, selected/omitted paths and test-evidence hash
are bound. Uncommitted content is read from disk, not inferred from HEAD.
Baselines must be real independently approved snapshots; preparation does not
make a PASS or authorize installation. Old PASS records never approve new code.

Full test transcripts stay local. Summaries retain complete-run counts,
failures, source binding and explicit fixture/installed limits. The default
delta bound is 256 KiB; full source is bounded to 2 MiB. Exceeding a limit
defers before charging a model call. There is no silent diff truncation.

`tools/review_desktop.py` uses the same packet builder, explicitly injects the
three criteria, and validates a fresh source/package-bound result. A reviewer
can return `NEEDS_CONTEXT`; that is deferred, never PASS. Existing call caps,
authorization chains and no-refund/no-reset rules are unchanged. CLI tools,
MCP, customizations and recursive agent invocation remain disabled. The
current-source adapter is included in the source manifest; the live core's
immutable policy, authentication and queue are not rewritten.

## Install and verify skills

```powershell
& 'C:\Python312\python.exe' -B 'E:\Github\Research-Agent-Orchestrator\tools\install_review_skills.py'
& 'C:\Python312\python.exe' -B 'E:\Github\Research-Agent-Orchestrator\tools\install_review_skills.py' --check
```

Installs `diff-review`, `risk-aware-review`, `token-budget` into the existing
user's Codex and Claude skills homes. Unknown or manually edited destinations
are retained and rejected. No global auth, model or tool configuration is
changed. New interactive sessions can discover them. Existing sessions are
not restarted. The tool-disabled background reviewer receives criteria from
the fixed source package explicitly; it does not discover user-home files.

## Actual token evidence

```powershell
& 'C:\Python312\python.exe' -B 'E:\Github\Research-Agent-Orchestrator\tools\token_usage.py' --runtime 'E:\Github\Building-Generation-Validation\.runtime'
```

The CLI adapter retains allowlisted provider-reported input/output/cache counts
and per-model counters in `evidence.token_usage`, including failures whose native
response contains usage. Missing is `UNAVAILABLE`, explicit zero is zero. No
historical count is invented. A byte budget or tokenizer estimate is not actual
Claude usage. Per-model and aggregate values are kept separate, not added twice.
Codex cached input is part of its input count; Claude cache-read/write counters
have different semantics. Native App Server cumulative thread samples are
reported separately, not summed across notifications or turns. No reasoning
text, credentials, raw streams or hidden model output is stored.

This change prepares development code and local skills. It does not auto-start
an audit, reset the exhausted historical cycle, unpause workers, publish research,
or replace any running fixed snapshot. A source/test change invalidates earlier
candidate acceptance. Current live jobs continue on their existing versions.
