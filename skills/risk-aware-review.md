---
name: risk-aware-review
description: Determine the necessary context for a bounded code review and identify behavior or test regressions. Use with diff-review; does not grant tools or decide deployment authorization.
---

Expand review across permission checks, authentication, subprocess ownership, persistent queues, locking, recovery, billing configuration, serialization and deployment when those contracts change. Inspect the affected end-to-end path and failure behavior.

For UI work check container clipping, display scaling, event handlers and backend contracts. Embedded JavaScript/CSS in Python or C# and WebView2 calls need explicit cross-language context; a static dependency graph is advisory.

Tests must observe behavior and be capable of failing for the defect. Preserve real incident regressions and positive/negative controls. Mock external boundaries deliberately; mock-only results do not prove real scheduling, process recovery or research acceptance. Never weaken a test to obtain PASS.

Missing coverage or a stale baseline requires NEEDS_CONTEXT or a larger bounded review. Do not demand unrelated refactoring, arbitrary function-length limits or extra model panels.
