# Scene Control interface

The full desktop keeps four sections: Mission, SQZ GPU, Codex/David and
Claude/Lucy. Documentation shows the complete interface, without separate portrait
cards. Demonstration images are labelled and contain synthetic data.

## Mission

The conversation fills the upper part of Mission. The prompt stays at the bottom;
reference text and skills sit directly above it. **Codex 工作** and **文本分析** keep
their existing, separate admission rules. System budgets and old task records are
inside **系统与历史记录**. Research stop alerts remain visible outside that drawer.

Codex references become a clearly delimited part of the same bounded prompt. The
question and references together are limited to 20,000 characters. A failed send
keeps both fields and retries the same request ID. Refreshing status preserves a
draft and does not dispatch work. Changing a permission selector affects the next
turn; it does not rewrite the settings shown for an already running turn.

## Agent panels

David's larger square video sits on the outside left. Lucy's matching video sits
on the outside right. Each panel shows its reported model, effort and permission
mode, current public phase and a locally scrolling event history.

- Codex model comes from the owned session record; effort and permission mode come
  from the exact admitted turn.
- Claude effort and permission mode come from its review record. The current
  bounded reviewer requests `high` with tools disabled and `dontAsk`; the UI labels
  that **自动审核 · 工具禁用**. This is not unrestricted shell access.
- The existing Claude adapter does not report an actual resolved model name.
  That field stays **CLI 默认 · 未上报**. Old reviews lacking settings keep unknown
  fields. The interface never guesses Opus or a model version.
- Work without a verified active service is labelled offline/history or stale.
  The interface does not adopt other terminal/chat sessions.

## Public workflow and handoffs

Each registered native-worker turn follows its existing cycle:
**登记 → Codex 执行 → Claude 审核 → 结果**. The phase bar advances from persisted
states. The two panels describe their different responsibilities: Codex submits
work for review; Claude returns a pass or repair request. An unknown state is not
shown as a completed phase.

This cycle is not an automatically invented research master plan. No arbitrary
five-stage goal is inferred from prose. A separate authorised research plan and its
actual acceptance gates are still required for scientific work. A workspace review
PASS allows continuing that workspace workflow; it does not certify a building,
robot simulation or permission to publish.

A slow light pulse appears only with fresh observation of the relevant registered
running process. Waiting for approval, blocked, paused and stale states do not
receive that executing pulse. STALLED is displayed only if explicitly reported;
silence or elapsed time alone does not prove a stall.

An observed transition of the same turn into review triggers the forward handoff.
A new supported review result triggers the return handoff. Initial snapshots and
unchanged polling do not replay transfers. Pausing motion, OS reduced-motion and
hidden-window handling stop decorative motion through the existing controls.

Stage history contains public command/status records and bounded review issues,
not hidden reasoning. It follows new records while you are at the bottom. Scrolling
up preserves your reading position; **回到最新** resumes following. At most the most
recent 20 turns and 60 visible events are projected; totals are retained separately.

## Verification and deployment

`python -B tools/test_desktop.py --output .runtime/desktop-tests.json` includes the
workflow-projection regressions. On the configured Windows development machine,
`python -B tools/verify_mission_ui.py --output .runtime/ui-checks.json` exercises the
actual interface scripts in a separate headless Edge profile with synthetic data.
That optional QA tool uses the existing `websocket-client` installation; production
services do not import it. It makes no model calls, SSH connections or live database
reads, and closes only its own browser/server.

Synthetic interaction checks and documentation GIFs are not installed acceptance.
New activation still requires the fixed-source independent review, complete current
tests, installed native checks and the owned Windows scheduler receipt. A UI update
does not activate the paused native worker or restart research jobs.
