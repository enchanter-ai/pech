---
description: L1 Exponential Smoothing forecast for session/day/month spend with ±2σ confidence band.
---

# /pech-forecast

Projects end-of-scope spend via L1 Exponential Smoothing over the current ledger. Always reports the ±2σ band — point estimates without bands are banned.

## Usage

```
/pech-forecast              # end-of-session (default)
/pech-forecast --session
/pech-forecast --day
/pech-forecast --month
/pech-forecast --json       # machine-readable
```

## Arguments

| Argument | Type | Default | Purpose |
|----------|------|---------|---------|
| `--session` / `--day` / `--month` | flag | `--session` | Forecast horizon |
| `--json` | flag | off | JSON output |
| `--alpha` | float | 0.3 | Override L1 smoothing coefficient |

## Example output

```
Pech — forecast (session horizon)
─────────────────────────────────────────────────────────────
Point estimate:                                       $1.87
±2σ band:                                   [$1.42, $2.32]
Confidence:                                        95% (2σ)
Observations:                                     47 calls
α:                                                     0.3
Rate card:                        2026-04-19 (0 days old)
─────────────────────────────────────────────────────────────
```

If fewer than 3 observations exist, the command reports `insufficient_data` — forecasts over a 1-or-2 call series are noise, not signal.

## Invokes

Triggers `cost-tracker/forecast-cost` skill (Sonnet tier — the forecasting loop amortizes well). See [../../cost-tracker/skills/forecast-cost/SKILL.md](../../cost-tracker/skills/forecast-cost/SKILL.md).
