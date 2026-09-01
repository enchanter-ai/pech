# nook-learning

*Part of [Pech](../../README.md) — Cost Ledger for AI-Assisted Development.*

L5 Gauss Learning — per-developer cost-pattern accumulation. Solves the cold-start problem for L3 anomaly detection: a fresh session has no history, so the first 30 calls can't fire anomalies. nook-learning persists patterns across sessions and seeds the rolling window with historical means.

## Engine

| ID | Name | Algorithm |
|----|------|-----------|
| **L5** | Gauss Learning (Pech) | Weighted moving averages over per-developer signals. Update rule: `μ_new = 0.95 × μ_old + 0.05 × current_session_mean` (slow accumulator, survives noisy sessions). Per-axis: `(skill, session_type, model)`. Emu-A4 atomic serialization — write-to-tmp + fsync + rename. |

## When it runs

- **`PreCompact` hook** — end-of-session (or compaction trigger), persists accumulated patterns before the session's state is lost
- **On `nook-learning/accumulate-pattern` skill invocation** — explicit recompute after anomaly-triager sessions

## What it persists

`state/learnings.json` shape:

```json
{
  "version": 1,
  "last_updated": "2026-04-19T18:32:00Z",
  "n_sessions_accumulated": 127,
  "patterns": {
    "wixie:/converge:sonnet": {
      "n_observations": 3421,
      "mu_cost_usd": 0.24,
      "sigma_cost_usd": 0.11,
      "p50": 0.22,
      "p95": 0.48,
      "last_session": "2026-04-19T14:02:00Z"
    },
    "crow:/trust-score:sonnet": {
      "n_observations": 891,
      "mu_cost_usd": 0.08,
      "sigma_cost_usd": 0.03,
      "p50": 0.07,
      "p95": 0.15,
      "last_session": "2026-04-19T12:11:00Z"
    }
  }
}
```

## How L3 uses it

When L3 needs a rolling μ and σ but the current session has < 30 calls for the attribution tuple, it falls back to `learnings.json#patterns[<tuple>]` for the historical prior. This is how a brand-new session can flag "this `/converge` run at $0.80 is 3.3× your rolling mean" — because `μ = 0.24` is remembered from prior sessions.

## Export to shared/learnings.json

After each accumulation, `accumulate-pattern` appends a cross-plugin-readable snapshot to `shared/learnings.json` so peer plugins (Wixie, Sylph, Crow) can read Pech's spend-pattern knowledge for their own judgments (e.g. Wixie deciding whether to skip a redundant `/converge` run based on its cost history).

## Events

**Publishes:** `pech.learning.pattern.updated` (once per PreCompact, not per call)

**Subscribes:** none

## Brand invariants

- Emu-A4 atomic serialization — never a partial `learnings.json` on crash
- Slow accumulator (α = 0.05 for μ update) — a single noisy session doesn't skew the pattern
- Per-tuple learning — `(skill, session_type, model)` resolution, not global
- Export to shared/learnings.json on every update — peer plugins learn from Pech
