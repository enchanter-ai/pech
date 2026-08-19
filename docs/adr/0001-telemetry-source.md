# ADR 0001: Telemetry source for per-call token usage

## Status

Accepted (2026-08-19).

## Context

Pech's ledger (`plugins/cost-tracker/state/ledger-*.jsonl`) is supposed to record
real token usage and cost per tool call. It never did: `shared/scripts/observe.py`
is wired as a `PostToolUse` hook, and `extract_usage()` read
`hook_payload["tool_response"]["usage"]` — a field that does not exist on that
event. `tool_response` carries the tool's *result* (file contents, command output,
etc.), not the model's token accounting. Every call fell through the
`if not usage: return 0` fail-open guard, so the ledger silently stayed empty. This
is the defect VF-12 exists to fix.

Two candidate sources were considered for the real number:

1. **CLI-reported `total_cost_usd`** (surfaced at session end / in `Stop` hook
   payloads). Rejected: it is a *session-level* aggregate, not per-call. Pech's
   ledger schema and every downstream consumer (`detect_anomaly.py`,
   `check_budget.py`, `finalize_session.py`) are built around per-call rows —
   attributing a session total to individual tool calls would require guessing a
   split, which is exactly the kind of silent capability substitution
   `capability-fidelity.md` (F22) forbids. It also can't tell a Haiku sub-agent's
   spend from an Opus orchestrator's inside the same session.
2. **The transcript JSONL** (`~/.claude/projects/<project>/<session>.jsonl`, whose
   path is handed to every hook as `transcript_path`). Each assistant turn is one
   line: `message.id`, `message.usage` (`input_tokens`, `output_tokens`,
   `cache_creation_input_tokens`, `cache_read_input_tokens`), and a `content[]`
   array containing the `tool_use` block(s) issued in that turn, each with its own
   `id`. This is the same data the CLI itself derives `total_cost_usd` from —
   sourcing it directly gives Pech per-turn granularity instead of a session-wide
   number.

**Decision: transcript JSONL.**

## The split problem

Anthropic's API bills token usage per *turn*, not per tool call. When a model
emits three tool calls in one turn (parallel tool use), all three share one
`message.id` and one `message.usage` — there is no per-tool-call cost to recover,
because none exists at the API level. `PostToolUse` fires once per tool call, so a
three-tool turn fires the hook three times against the same underlying usage.

Splitting the turn's cost three ways (e.g. dividing by call count) was considered
and rejected: it invents a number the API never gave us, which is a heavier
honest-numbers violation than picking a policy and stating it plainly.

**Decision: first-call-gets-full-turn-cost.** The first `PostToolUse` whose
`message.id` hasn't been seen yet records the full turn usage/cost. Every
subsequent `PostToolUse` for the same `message.id` still writes a ledger row (so
`n_calls` / call-count stays accurate) but with zero usage — the turn's cost has
already been recorded once. Session-level totals (`check_budget.py`,
`finalize_session.py`) are therefore correct; only the *attribution of cost to a
specific tool call within a multi-tool turn* is approximate (it lands on whichever
call happened to run first).

## Dedup store

Each `PostToolUse` hook is a fresh process — there is no in-memory way to remember
"we already billed `message.id` X" across calls. The dedup decision is persisted to
`plugins/cost-tracker/state/seen-message-ids.json`, a capped/rotated list (last
2000 ids, oldest dropped first) written via the same atomic tmp-file-then-rename
pattern already used for `session.json`. A short-lived exclusive-create lockfile
(`seen-message-ids.lock`, 0.5s timeout, fails open) guards the read-modify-write
against the one realistic race: two tool calls from the same parallel-tool-use turn
firing their hooks concurrently.

## Bounded tail scan

Transcripts grow unboundedly over a long session. Scanning the whole file on every
tool call would risk blowing the hook's 2-3s timeout budget on a long-running
session. `extract_usage()` reads only the last ~200 lines (`TRANSCRIPT_TAIL_LINES`,
via a bounded `collections.deque`) and scans backward from the end — the turn that
just fired a tool call is always near the tail. If the tool_use id isn't found in
that window (should not happen in practice, since `PostToolUse` fires immediately
after the corresponding transcript line is written, but transcript-write races or
an unusually chatty turn with heavy tool interleaving are possible), the row is
recorded as zero-usage/uncosted rather than the hook hanging, crashing, or growing
the scan window unboundedly.

## Consequences

- Ledger rows now reliably carry real per-turn token usage instead of always being
  empty.
- `n_calls` in `session.json` now reflects true tool-call volume, including the
  zero-cost dedup rows and any not-found rows — a more honest count than "only
  calls where we happened to find usage."
- Cost attribution within a multi-tool-call turn is approximate (all-or-nothing on
  the first call), which is disclosed here rather than hidden behind a
  finer-grained number the API doesn't actually provide.
- A missed dedup lock is a rare double-bill, not a crash — consistent with the
  hook's fail-open contract (`shared/vis/conduct/hooks.md`).
- `compute_cost()`, the ledger row schema, and all downstream consumers
  (`detect_anomaly.py`, `check_budget.py`, `finalize_session.py`) are unchanged;
  this ADR is scoped to `extract_usage()` and the new dedup layer in
  `shared/scripts/observe.py`.
