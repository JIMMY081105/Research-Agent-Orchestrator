# A research desk before a production goal

The same controller can do a single analysis, compare supplied options, or draft a
master prompt before a generation pipeline is approved. These are offline advisory
tasks: supplied excerpts go to Codex, Claude reviews the fixed result, and acceptance
checks the source/input hashes, literal citations and review. An accepted advisory
answer does not certify a scene, confirm a literature search, or approve its suggested
production work. No extra shell, browser, AI delegation or GPU permissions are granted.

`bgv-research-claims` and its case reference are explicitly loaded from pinned repository
copies for the writer, reviewer and Claude planner. The loader refuses changed hashes or
unregistered paths. Original skill paths are provenance labels; execution does not read
the user's global skill directory. Other native skills remain inventory entries unless
the registered action explicitly loads them. Adding a SKILL file alone adds no tools.

## Prepare a bounded brief

Use a separate analysis-only project with `allowed_actions: ["analyze_text"]`. This keeps
approval of a small advisory task from replacing another project's active production
goal. Choose the relevant organizational profile; it does not select an algorithm.
Project registration and fixed-plan approval use the existing trusted local commands.

Copy `config/brief.example.json` to an untracked `.runtime` request file. Replace both
example UUIDs with distinct new UUIDs, and supply real literal excerpts. The three
purposes are `analyze`, `compare`, and `prepare-master-prompt`. References record what the
user supplied; they are not independently verified document reads. Supply one to eight
sources, at most 14,000 source-text characters and 32 KiB UTF-8 request/input bytes. The
question is at most 1,000 characters, subject also to the compiled question limit.
Never include credentials. Paths and URLs inside the text are never followed.

```powershell
$c = 'E:\Github\Building-Generation-Validation\tools\control.ps1'
& $c brief-prepare --project 'ANALYSIS-PROJECT-UUID' --file 'ABSOLUTE-BRIEF-REQUEST-JSON'
```

Preparation makes zero model calls. It saves a fixed single-task draft goal and an
immutable preview/package in `.runtime/projects/PROJECT/briefs/GOAL/`. The package records
each source body's character offsets and hash, the exact input, rules/source/skill
bindings, and the plan hash. It does not change the active goal, approve anything, or
enqueue a task. An identical retry is idempotent; changed material needs new IDs.
The preview contains the exact input, not an AI-written answer.
The compiled input includes fixed source-body spans. Acceptance rejects a header-only
quote or a quote crossing source boundaries even when its characters match the input.
Semantic grounding still requires Claude's independent review and researcher judgment.
The preview's `approved: false` describes preparation; use live project/task status for
subsequent approval and execution state.

After checking the preview, approve that exact plan with an authorization text file
describing the limited analysis, then submit it:

```powershell
& $c goal-approve --project 'ANALYSIS-PROJECT-UUID' --goal 'GOAL-UUID' --plan-sha 'RETURNED-PLAN-SHA256' --authorization-file 'ABSOLUTE-AUTHORIZATION-TEXT'
& $c goal-submit --project 'ANALYSIS-PROJECT-UUID' --goal 'GOAL-UUID'
& $c show --id 'TASK-UUID'
```

The existing 15-minute worker dispatches it; no open chat or terminal is needed. The
current Windows user must remain logged in, the machine must be awake, and the CLI
service must be available. Status shows budget/login/network pauses. All reviews still
share the 50-per-UTC-day limit and a task has at most two repairs.

The answer is `artifact.json` in the shown task evidence directory, with its separate
review and acceptance receipts. Summary length is 10..5,000 characters and citations
are 1..8 exact quotes using Python character offsets. Use smaller briefs for larger
documents; the controller does not claim to read pages that were not supplied.

## From a draft to a production plan

`prepare-master-prompt` asks for a clearly unapproved draft: problem, provided inputs,
proposed outputs, acceptance checks, resource limits and missing decisions. Unknown
assets, algorithms and permissions stay UNKNOWN. Commands in that draft are plain
text. Neither parsing the draft nor advisory acceptance dispatches its proposals.
After the user settles the real goal, use the separate `goal-plan` and fixed-plan
approval flow in `STAGES.md`. Unsupported tools remain NEEDS_TOOL; the system cannot
turn arbitrary prose into authorized research-code edits or GPU runs.

No new UI, online asset search or GitHub publishing is implemented by this entry.
Local reporting and final user merge remain separate from analysis acceptance.
