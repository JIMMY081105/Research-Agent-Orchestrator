# Software and research boundary

This repository is the desktop/orchestrator development source. It contains no
server checkout, building assets, generated scenes, voxel caches, experiments or
scientific PASS/FAIL reports.

- `native/`: native Windows/WebView2 shell.
- `researchops/worker_*`: native Codex transport, user permission requests, owned
  process lifecycle, queue records and independent bounded workspace review.
- `researchops/dashboard_*`: presentation, read-only telemetry and HTTP admission.
- `researchops/core.py`, planning/projects/operations modules: bounded task and
  evidence contracts. Science/scene modules are connectors to external research
  tools, not vendored building-generation or simulation implementations.
- `researchops/github_review.py`: separately versioned delivery adapter. Its
  allowlisted private delivery repository is distinct from this software repository.
  Publishing software here does not change a research delivery target.
- `config/`, `prompts/`, `skills/`: general templates, adapters and reusable rules.
- `tests/`: isolated failure controls; `tools/`: local build/review/control helpers.

`config/tools.json` is a disabled example registry: no scenes are registered and
external source hashes are placeholders. Actual machine/input bindings remain
private in the existing deployment. Populate and validate local bindings before
requesting an external-tool action. Most Windows helpers retain that installation's
existing absolute runtime root; this source is not a portable turnkey installer.

The README image was rendered separately using synthetic documentation data with
zero models, SSH or live database reads. It is not a copied private acceptance
record or evidence that a research experiment passed. David/Lucy are UI portraits;
character imagery is not claimed as original project research or a new asset license.

Never commit `.runtime/`, `.venv/`, machine configuration, credentials, model output,
review packages, logs, databases, checkpoints or local deployment acceptance records.

## Tests for this software layer

On Windows run `python -B tools/test_desktop.py --output .runtime/desktop-tests.json`
for the complete UI/native-worker regression, and
`python -B -m unittest discover -s tests -p test_github_review.py` for the delivery
adapter. These isolated tests do not call models, SSH or real GPU jobs. Native
process-lifetime tests start only their own short Python children.

The historical controller-only `tools/run_tests.py` packager assumes a controller
candidate tree. A combined checkout also contains C# and documentation media that
its older allowlist refuses. Do not interpret that refusal as a completed full
monorepo test run or bypass it when activating a controller snapshot. The current
work verified the full UI/worker suite and the delivery adapter; research/GPU
acceptance remains separate.
