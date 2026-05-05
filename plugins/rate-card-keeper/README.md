# rate-card-keeper

*Part of [Pech](../../README.md) — Cost Ledger for AI-Assisted Development.*

Holds the rate card that every cost computation depends on. Rate card is committed JSON, refreshed via CI PR — never fetched at runtime (brand invariant: zero external runtime deps).

## Rate-card location

`shared/rate-card.json` — sibling-level shared state, not plugin-local, because cost-tracker and budget-watcher both read it and keeping three copies guarantees drift.

## Rate-card schema

```json
{
  "effective_from": "2026-04-19",
  "effective_until": null,
  "currency": "USD",
  "models": {
    "claude-opus-4-7":     { "input_rate_per_mtok": 15.00, "output_rate_per_mtok": 75.00 },
    "claude-sonnet-4-6":   { "input_rate_per_mtok":  3.00, "output_rate_per_mtok": 15.00 },
    "claude-haiku-4-5":    { "input_rate_per_mtok":  0.80, "output_rate_per_mtok":  4.00 }
  },
  "modifiers": {
    "cache_write_modifier": 1.25,
    "cache_read_modifier":  0.10,
    "batch_discount":       0.50
  },
  "fallback_model_rate": {
    "input_rate_per_mtok":  3.00,
    "output_rate_per_mtok": 15.00,
    "note": "Used when a model ID is not in the rates table. Rows using this fall-back are tagged rate_card_stale:true."
  },
  "_meta": {
    "source": "https://www.anthropic.com/pricing",
    "verified_by": "CI nightly refresh job",
    "last_verified": "2026-04-19"
  }
}
```

## Staleness policy

- **0–60 days old:** normal operation.
- **60–90 days old:** `load-rate-card` emits `pech.rate_card.stale.warning` at SessionStart.
- **> 90 days old:** all ledger rows computed against this card are tagged `rate_card_stale: true` — forecasts flag themselves as potentially off.
- **> 180 days old:** `load-rate-card` fails hard at SessionStart — refuse to observe until refreshed. Cost data under a half-year-stale card is dangerously wrong.

## Refresh mechanism

Nightly GitHub Actions workflow at `.github/workflows/refresh-rate-card.yml` (ships separately — this plugin describes the contract, not the CI). The job:

1. Scrapes Anthropic's published pricing.
2. Diffs against `shared/rate-card.json`.
3. On diff, opens a PR with the update, CC'ing `@enchanter-ai/maintainers`.
4. On no diff, updates `_meta.last_verified` and commits directly.

Never fetches at runtime. Never caches. The JSON is authoritative.

## Inputs

- **Hook event:** `SessionStart`
- **Rate card:** `shared/rate-card.json`

## Outputs

- **Event bus:** `pech.rate_card.refreshed` (on first load of a newer-than-prior-session card), `pech.rate_card.stale.warning` (60-90 days), `pech.rate_card.stale.blocking` (>180 days)

## Events

**Publishes:** `pech.rate_card.refreshed`, `pech.rate_card.stale.warning`, `pech.rate_card.stale.blocking`

**Subscribes:** none

## Brand invariants

- Zero runtime deps — the card is a committed file, not an HTTP fetch.
- Staleness is a first-class signal, not a silent drift.
- Schema validation at SessionStart (Haiku) catches breaking changes early.
