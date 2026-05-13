---
name: refresh-rate-card
description: >
  Updates shared/rate-card.json with a new per-model rate table. Validates the proposed
  update against the existing schema, diffs prices against the current card, and produces
  a commit-ready diff for human review. Use when: CI nightly job detects a pricing change
  on Anthropic's published rate page, or when the developer runs /refresh-rate-card after
  verifying a price change. Do not use at runtime during a Claude Code session — this
  skill runs in CI or at developer invocation, never inside the observation hot path.
model: sonnet
tools: [Read, Write]
---

# refresh-rate-card

## Preconditions

- Fresh rate data is available as structured JSON (provided as argument, not fetched here)
- The proposed JSON validates against the schema (see `load-rate-card` step 2-4)
- Not running inside a hook context (refresh is a deliberate developer/CI action)

## Inputs

- **Proposed rate-card JSON:** the new values to write
- **Current card:** `shared/rate-card.json`

## Steps

1. Validate the proposed card's schema (same checks as `load-rate-card`).
2. Diff against the current card:
   - For each model: compare input_rate and output_rate.
   - For each modifier: compare value.
   - Summarize changes: `{model, field, old_value, new_value, pct_change}`.
3. If any price changes by > 20% in either direction, flag as `suspicious_change` — require explicit confirmation before writing. Anthropic pricing historically moves by ≤ 10% per change.
4. Append the current card to `state/rate-card-history.jsonl` (audit trail of all prior cards).
5. Write the new card to `shared/rate-card.json` via atomic temp-rename (@../vis/packages/core/conduct/verification.md § dry-run pattern).
6. Set `_meta.last_verified` to today.
7. Emit `pech.rate_card.refreshed` with the diff summary.

**Success criterion:** new card is valid, history is preserved, diff summary emitted. Never overwrite the card without appending history — audit trail is load-bearing for forecasting backtests.

## Outputs

- Updated `shared/rate-card.json`
- Appended `state/rate-card-history.jsonl`
- Event: `pech.rate_card.refreshed` with diff

## Handoff

CI workflow commits the updated card in a PR. Developer review decides whether `suspicious_change` flags require reverting.

## Failure modes

| Code | Scenario | Counter |
|------|----------|---------|
| F10 | Overwrite the card without appending history | Hard-fail — atomic rename requires history append in the same operation |
| F11 | Silently pass a > 20% change because the diff looks clean | `suspicious_change` flag is mandatory regardless of visual appearance |
| F14 | Apply a rate change retroactively to old ledger rows | Forbidden — old rows stay at their computed-at-write-time cost; audit trail compares against rate-card-history.jsonl |
