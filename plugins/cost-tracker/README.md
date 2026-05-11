# cost-tracker

*Part of [Pech](../../README.md) — Cost Ledger for AI-Assisted Development.*

Pech's primary hook consumer. Observes every tool call, attributes spend to the firing plugin / sub-plugin / skill / agent tier / model, writes to an append-only JSONL ledger, and runs L1 forecasting + L4 cache-waste measurement.

## Engines

| ID | Name | Algorithm |
|----|------|-----------|
| **L1** | Exponential Smoothing Forecast | `ŷ_{t+1} = α · y_t + (1−α) · ŷ_t`, α = 0.3. Horizons: end-of-session, end-of-day, end-of-month. Confidence: ±2σ over residual series. |
| **L4** | Cache-Waste Measurement | Hit ratio = `reads / (reads + writes + misses)`. Waste = writes with no downstream reads within session — surfaces dollars wasted on unused prompt-cache writes. |

## Inputs

- **Hook event:** `PostToolUse` on any tool (the matcher is `.*` — everything gets observed)
- **Attribution source:** `ENCHANTED_ATTRIBUTION` environment variable set by the firing plugin
- **Rate card:** read from `shared/rate-card.json`
- **Token counts:** authoritative from API response `usage` field; falls back to Emu's A2 estimate if API response unavailable

## Outputs

- **Ledger row** written to `state/ledger-YYYY-MM.jsonl` (monthly rotation)
- **Session snapshot** updated at `state/session.json` (for status-line consumers)
- **Daily rollup** regenerated at `state/rollups/daily-YYYY-MM-DD.json` on `Stop`
- **Event bus:** `pech.session.cost.finalized` on `Stop` only

## State

| File | Purpose | Retention |
|------|---------|-----------|
| `state/ledger-YYYY-MM.jsonl` | Append-only per-call rows | 90 days |
| `state/rollups/daily-YYYY-MM-DD.json` | Daily pre-aggregated rollups | Forever |
| `state/session.json` | In-memory snapshot of current session | Per-session |

## Events

**Publishes:** `pech.session.cost.finalized`

**Subscribes:** `emu.api.usage.observed` (authoritative token source)

## Brand invariants

- Bus emission on `Stop` only, never per-call (see `@../enchanter-foundations/packages/core/conduct/hooks.md` + Pech CLAUDE.md § Behavioral contract 3).
- Never re-tokenize client-side — API `usage` field is authoritative; Emu's A2 is the fallback estimate.
- Per-agent-tier attribution is load-bearing; orphan rate surfaced as health metric.
