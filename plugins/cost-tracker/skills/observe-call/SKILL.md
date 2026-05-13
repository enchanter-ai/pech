---
name: observe-call
description: >
  Writes a single ledger row for the most recent tool-use call: reads the API response's
  usage field (authoritative), looks up the model rate in shared/rate-card.json, applies
  prompt-cache modifiers (1.25× write, 0.1× read), computes billed cost, and appends to
  plugins/cost-tracker/state/ledger-YYYY-MM.jsonl. Use when: a PostToolUse hook fires for
  any tool and attribution metadata is available via ENCHANTED_ATTRIBUTION env. Do not use
  for forecasting (see /pech-forecast → forecast-cost) or for anomaly detection (see
  budget-watcher/detect-anomaly).
model: haiku
tools: [Read, Write, Bash]
---

# observe-call

## Preconditions

- `shared/rate-card.json` exists and is readable
- The caller sets `ENCHANTED_ATTRIBUTION` env var to a JSON object with `{plugin, sub_plugin, skill, agent_tier, model}`
- API response is available via hook input (or Emu's `emu.api.usage.observed` event is the source)

## Inputs

- **Hook payload:** the standard `PostToolUse` shape — tool name, tool input, tool result
- **Environment:** `ENCHANTED_ATTRIBUTION` with the five-tuple above
- **Rate card:** `shared/rate-card.json`

## Steps

1. Parse the hook payload for the API `usage` field (`input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`). If absent, fall back to `emu.api.usage.observed` subscription.
2. Parse `ENCHANTED_ATTRIBUTION`. If missing, tag the row `orphan: true` and continue — do not drop the row.
3. Look up the model in `shared/rate-card.json`. If model absent, tag `rate_card_stale: true` and use the default fallback rate entry.
4. Compute cost:
   - `input_cost = input_tokens × rate.input_rate_per_mtok / 1e6`
   - `cache_write_cost = cache_creation_input_tokens × rate.input_rate_per_mtok × rate.cache_write_modifier / 1e6`
   - `cache_read_cost = cache_read_input_tokens × rate.input_rate_per_mtok × rate.cache_read_modifier / 1e6`
   - `output_cost = output_tokens × rate.output_rate_per_mtok / 1e6`
   - Apply `rate.batch_discount` if this call was batched.
5. Append row to `state/ledger-YYYY-MM.jsonl` with all tags + costs + timestamp.
6. Update `state/session.json` in-place (atomic rename via `@../vis/packages/core/conduct/verification.md` § Dry-run pattern — write to `.tmp`, fsync, rename).

**Success criterion:** ledger row written, session.json updated, zero stdout pollution (`@../vis/packages/core/conduct/hooks.md` § Logging from hooks — log to `state/observe.log`, not stdout).

## Outputs

- Ledger row at `state/ledger-YYYY-MM.jsonl`
- Session snapshot at `state/session.json`

## Handoff

No direct handoff — the skill is fired per-call. The observation feeds downstream consumers (`budget-watcher` reads the ledger for threshold checks; `cost-query` reads it for developer display).

## Failure modes

| Code | Scenario | Counter |
|------|----------|---------|
| F02 | Fabricate attribution because `ENCHANTED_ATTRIBUTION` was missing | Tag `orphan: true` instead; never invent |
| F08 | Reaching for Bash when Python stdlib would do | Use `json` + `pathlib` only |
| F14 | Use stale rate-card without tagging | Always set `rate_card_stale: true` when `effective_from` > 90 days old |
