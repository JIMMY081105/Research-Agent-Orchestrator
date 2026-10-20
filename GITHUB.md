# GitHub result delivery

This separate bridge delivers a fixed file list to the private repository
`JIMMY081105/Building-Generation-Validation`. It does not adopt research sessions,
run experiments, grant tools to models, change the controller/UI, or merge PRs.
The original `config/policy.json` stays `publish=false`; that controller cannot
call this bridge. The worker or operator invokes the separate, explicit CLI.

The current user's existing GitHub CLI keyring login is reused. No token is
read, copied, printed or stored. Child-only token-variable removal avoids using
an alternate API token; global authentication and environment are unchanged.
All publication is scoped to a new `bgv/review/<UUID>` branch and
`reviews/<UUID>/` directory. The default branch is only read as the commit parent.
There is no branch-update, force-push, delete, settings, review-approval or merge API.

## Worker handoff

Research work already running stays where it is. On completion, copy only the
intended final summary and explicitly selected, permitted images into:

`E:\Github\Building-Generation-Validation\.runtime\github\intake\<UUID>\`

Use a new canonical UUID per delivery. Write `ready.json` last, following
`config/github-review.example.json`, with each file's actual SHA256. Paths are
relative to that UUID directory, not paths into an active research checkout.
The bridge reads no other research directories and executes no embedded commands.
Keep full model output, raw logs, task databases, checkpoints, machine configuration,
credentials and local acceptance evidence outside the delivery. Only concise
shareable reports and selected PNG/JPEG/WebP previews belong here. Text is checked
for common credential signatures; that check cannot prove absence of every secret
or remove private metadata from images. Review the exact fixed file list before publishing.

## Prepare, publish and inspect

After independently reviewed source is frozen and activated:

```powershell
$g = 'E:\Github\Building-Generation-Validation\.runtime\github\activation.json'
$a = Get-Content -LiteralPath $g -Raw | ConvertFrom-Json
$c = Join-Path $a.source 'tools\github.ps1'
& $c status
& $c prepare --id 'DELIVERY-UUID'
```

Preparation performs remote GETs only. It saves the copied, hashed file list and
`PREVIEW.md` under `.runtime/github/outbox/<UUID>`. It never publishes automatically.
Its receipt supplies the exact package SHA256. Authorize only that concrete package:

```powershell
& $c publish --id 'DELIVERY-UUID' --expected-hash 'EXACT-PACKAGE-SHA256' --authorize-draft-pr
& $c reconcile --id 'DELIVERY-UUID' --expected-hash 'EXACT-PACKAGE-SHA256'
```

Publication requires current independent source review and its bound passing tests,
unchanged source, unchanged input/request and unchanged copied files. It rechecks
the exact local repository/origin and private remote before writes. It creates blobs,
a tree based on the recorded default-branch commit, one commit, a new branch and
one draft PR. It never checks out, stages, commits or pushes an active working tree.
GitHub tree changes are limited to the fixed `reviews/<UUID>/` prefix.

Every remote write has a durable local intent first. On an uncertain API result or
crash, further publication is blocked. `reconcile` is remote read-only, checks the
exact head/base/repository/commit, and records a found PR. It does not automatically
replay an unknown write. Repeating a completed delivery returns the same PR, not a
new branch or PR. An existing branch with a different commit is rejected.

Open the returned PR URL. Read its report and inspect images; source-reported
PASS does not mean this delivery bridge validated physics, navigation or science.
The same GitHub account cannot formally approve its own PR; the owner can inspect
the result, mark the draft ready and merge manually, or obtain another reviewer's
approval. No automatic merge or approval is implemented.

This feature has no recurring task or model calls. Closing the app does not alter
research work. Invocations are bounded to 45 seconds per GitHub API call and pause
on authentication, network, permission or rate-limit errors without retry loops.
Remove only this bridge's local activation to disable new invocations; preserve
outbox history. No existing Windows tasks, VPN or archive processes are changed.
