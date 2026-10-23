---
name: token-budget
description: Keep review context focused and interpret actual CLI token evidence correctly. Use when preparing or assessing model calls and usage reports; does not raise limits or authorize retries.
---

Use the complete bounded review packet. Keep test transcripts and full manifests as local evidence; send bound summaries, failure evidence and necessary source. Never silently truncate a diff or omit required context to fit a budget. Report a context limit as DEFERRED/NEEDS_CONTEXT.

The runner, not this instruction, enforces byte/call/time limits and preserves all charges. These three review skills are one call's criteria, not three separate model calls. No recursive agent calls, automatic paid fallback or retry after quota/auth/network failure.

Record only provider-reported input, output and cache token counters. Missing metrics are UNKNOWN, explicit zero is zero. Input/cache semantics differ by provider; do not sum per-model and aggregate counters or repeated cumulative snapshots. Tokenizer estimates and bytes are not actual Claude usage. Never log credentials, raw model streams or hidden reasoning.
