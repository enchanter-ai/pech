# budget-watcher

*Part of [Pech](../../README.md) — Cost Ledger for AI-Assisted Development.*

Owns Pech's two threshold-alerting engines. L2 fires on budget crossings; L3 fires on statistical anomalies. Both publish through the enchanted-mcp event bus so peer plugins degrade gracefully.

## Engines

| ID | Name | Algorithm |
|----|------|-----------|
| **L2** | Budget Boundary Detection | Per-scope counters (session / hour / day / month × agent tier × model). Thresholds at 50 / 80 / 100%. Debounced: one event per (threshold, scope, window) — not one per call. |
| **L3** | Z-Score Cost Anomaly | Rolling mean μ + σ over last 30 calls matching the same attribution tuple (plugin, sub-plugin, skill, agent_tier, model). Anomaly when `|y - μ| > 3σ`. Alerts on spikes *and* drops (drops signal cache-hit regressions). |

## Inputs

- **Hook event:** `PostToolUse` on any tool (after cost-tracker writes the ledger row)
- **Budget ceilings:** `state/budgets.json` (developer config)
- **Ledger:** reads `plugins/cost-tracker/state/ledger-YYYY-MM.jsonl`

## Outputs

- **Event bus:** `pech.budget.threshold.crossed`, `pech.anomaly.detected`, `pech.attribution.orphan_rate.crossed`
- **State log:** `state/thresholds.jsonl` (debounce state + audit trail of every crossing)

## Budget configuration

`state/budgets.json` — per-developer, versioned, checked into git (it's a config, not runtime state). Default shape:

```json
{
  "session": { "total_usd": 5.00, "opus_usd": 2.00 },
  "hour":    { "total_usd": 15.00 },
  "day":     { "total_usd": 50.00, "opus_usd": 20.00 },
  "month":   { "total_usd": 500.00 },
  "orphan_rate_threshold": 0.01
}
```

Missing scopes disable threshold checking for that scope — no budget means no event.

## Debounce rule

One threshold event per `(threshold ∈ {50, 80, 100}, scope ∈ {session, hour, day, month}, scope_key)` tuple per window. Example: after `50% session total` fires once, it does not fire again until either (a) a new session starts, or (b) the session drops below 50% and re-crosses (rare but possible if a batch correction arrives late).

Debounce state lives in `state/thresholds.jsonl` — append-only so we can audit why an event did or didn't fire.

## Events

**Publishes:**

| Event | Trigger | Payload |
|-------|---------|---------|
| `pech.budget.threshold.crossed` | L2 crossing (50/80/100%) | `{scope, scope_key, threshold, ceiling_usd, current_usd, ratio}` |
| `pech.anomaly.detected` | L3 3σ outlier | `{attribution_tuple, current_cost_usd, rolling_mean, rolling_sigma, z_score, direction ∈ {spike, drop}}` |
| `pech.attribution.orphan_rate.crossed` | orphan rate > threshold over rolling 100 calls | `{orphan_count, total_count, orphan_rate}` |

**Subscribes:** (reads ledger rows written by cost-tracker; no bus subscription needed)

## Brand invariants

- Events fire on crossings + rollups only — never per call (see `@../enchanter-foundations/packages/core/conduct/hooks.md`).
- Debounce is mandatory: N calls past threshold produce one event, not N.
- Orphan rate is a first-class health signal, not a hidden bucket.
