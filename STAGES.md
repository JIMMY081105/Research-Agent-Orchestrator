# Four-stage operation

The system has four separately evidenced stages. Infrastructure acceptance does not
establish that a research scene is scientifically valid. Runtime reports are the source
of actual status; examples below do not certify deployment.

## 1. Durable Windows worker

The existing accepted snapshot owns the 15-minute Windows task. Codex executes one
registered action, Claude reviews its fixed input/source/artifact binding, and the
controller forwards bound rejection issues for at most two repairs. The persistent
ledger admits at most 50 reviews per UTC day, including planning and source audits.
No change and no queued task means zero model calls. A different source needs new tests,
independent audit, real acceptance, snapshot installation and an actual timer receipt.

## 2. Projects, goals and existing work

Project profiles are `factory`, `car-warehouse`, `housing`, `office`, `museum`, `stadium`.
They are organizational profiles, not claims of six supported scene generators.
Each project has versioned rules, an exact approved task DAG and private output roots.
Claude coordinates and reviews; Codex executes; the user sets rules and merges results.
Projects without an approved goal remain AWAITING_GOAL. There is no invented production
goal while the user is still choosing assets and algorithms.

`goal-plan` makes one real tool-free Claude call using a literal input catalog. It
can propose only registered actions. The controller supplies task IDs, validates input
types and dependencies, and refuses arbitrary paths, commands and fabricated inputs.
Unsupported goals return NEEDS_INPUT or NEEDS_TOOL without dispatchable tasks. A proposal
does not approve itself. `goal-adopt` verifies the retained CLI result and charged attempt;
`goal-approve` binds trusted local authorization to the exact plan/rules/source hash.
Changing any binding invalidates dispatch and old approval. Dependency completion is
rechecked against real acceptance evidence, not a database state label alone.

```powershell
$c = 'E:\Github\Building-Generation-Validation\tools\control.ps1'
& $c projects
& $c project-register --file 'ABSOLUTE-PROJECT-JSON'
& $c project-rules --project 'PROJECT-UUID' --file 'ABSOLUTE-RULES-JSON'
& $c goal-plan --project 'PROJECT-UUID' --id 'NEW-PROPOSAL-UUID' --file 'ABSOLUTE-GOAL-REQUEST-JSON'
& $c goal-adopt --project 'PROJECT-UUID' --proposal 'PROPOSAL-UUID'
& $c goal-approve --project 'PROJECT-UUID' --goal 'GOAL-UUID' --plan-sha 'EXACT-PLAN-SHA256' --authorization-file 'ABSOLUTE-APPROVAL-TEXT'
& $c goal-submit --project 'PROJECT-UUID' --goal 'GOAL-UUID'
```

`config/project.example.json` and `config/goal-request.example.json` are templates; use
fresh UUIDs and non-sensitive inputs. Registration/approval are trusted local operator
commands. Models have no tools with which to run them. An `ops-smoke` project is marked
as an operational test and cannot be used as research completion evidence.

The optional observer reads `.runtime/research-watch.json`, never a model command.
`config/research-watch.example.json` is disabled and contains generic placeholders.
The real machine configuration is untracked. The fixed SSH probe uses strict existing
host keys, no forwards, no VPN changes, no installations, no remote dispatch and no models.
It reads bounded PID/birth/boot/namespace, cwd, tmux and registered file metadata beneath
one approved private-host root. A network failure is UNKNOWN. PID absence proves exit
only with the same boot/namespace and a complete identity inventory. A live monitor is
not proof that generation is running; a nearby HEAD is not loaded-code evidence.

## 3. Scientific acceptance

Evidence is content-bound to the executed source, literal inputs and actual artifacts.
Registered checker functions must match their actual module file and declared layers.
Trusted controller run receipts are registered separately from model output. Each gate
requires an actual target run, positive control and negative control, exact sample/seed
coverage, process ownership, exit state and matching scientific failure reason.
Missing evidence is UNVERIFIED or BLOCKED. An infrastructure error is not a successful
negative control. Persisted JSON saying READY cannot mint an issued gate assessment.

Full sample readiness requires static geometry, native-runtime collision,
body-radius navigation and robot behavior. Batch completion additionally requires the
entire declared unique sample set. One stair or image cannot certify a building batch.
The current registered stair action establishes limited static asset geometry only;
placement in a building, native physics and humanoid behavior require additional
authorized tools and real runs. No GPU workload or research write is currently enabled.

For an already accepted historical CPU stair task, `science-check --id TASK-UUID`
verifies its complete retained queue/attempt/source/artifact evidence and runs three
new LPAC checker processes. A fourth fixed LPAC helper removes CollisionAPI only on
the negative copy, preserving its geometry. Exit zero with missing collision markers
must be rejected by content. This establishes STATIC_GEOMETRY only. Explicit
`daily-report --verify-science` reconstructs retained assessments from owned receipts
and hashes, never a saved READY label. Routine reporting uses bounded historical
references with UNVERIFIED/SCIENTIFIC_REVALIDATION_DEFERRED instead of rereading entire
dependency trees every tick. Historical acceptance and a fresh scientific check are
shown separately.

## 4. Review packages and final merge

The controller produces immutable local Markdown/JSON/SVG daily packages when meaningful
state changes. They include project/goal status, genuine task state, review budget,
scientific coverage and missing evidence. Overview SVG is a status diagram, not a scene
render. Beauty/Collision pairs require actual content hashes, capture provenance,
matching sample/view metadata and image checks; missing images stay MISSING.
Reports cannot reuse stale or modified READY evidence. No raw prompts, credentials,
machine configuration or entire runtime is packaged. No generated visual substitutes
for research render evidence. Creating the local package does not publish to GitHub.

```powershell
& 'E:\Github\Building-Generation-Validation\tools\control.ps1' research-watch
& 'E:\Github\Building-Generation-Validation\tools\control.ps1' daily-report
& 'E:\Github\Building-Generation-Validation\tools\control.ps1' daily-report --verify-science
& 'E:\Github\Building-Generation-Validation\tools\control.ps1' status
```

GitHub publishing, research-code edits and GPU experiments remain disabled. Once a real
project goal and its tool/resource/publication permissions are approved, those adapters
must be implemented and verified before unattended research execution. Final merge always
belongs to the user. Sleep/network behavior is simulated; this deployment does not disrupt
existing work with a real sleep or network cut.
