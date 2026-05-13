---
name: check-budget
description: >
  Runs L2 Budget Boundary Detection after each ledger write: increments per-scope counters,
  compares against ceilings in state/budgets.json, emits pech.budget.threshold.crossed on
  first crossing of each threshold within each scope-window. Use when: a PostToolUse hook
  fires and cost-tracker has already written the ledger row. Do not use for forecasting
  (see forecast-cost) or anomaly detection (see detect-anomaly).
model: haiku
tools: [Read, Write]
---

# check-budget

## Preconditions

- A ledger row has been written for the current call (cost-tracker runs before this skill)
- `state/budgets.json` exists (absent = no threshold checking, silently skip)

## Inputs

- **Ledger tail:** most recent row from `plugins/cost-tracker/state/ledger-YYYY-MM.jsonl`
- **Budget config:** `state/budgets.json`
- **Debounce state:** `state/thresholds.jsonl` (append-only log of prior crossings)

## Steps

1. Parse the latest ledger row. Extract `cost_usd`, `timestamp`, `attribution.agent_tier`, `attribution.model`.
2. For each scope ∈ {session, hour, day, month}, compute or read the current scope total. Use rolling sums stored in `state/counters.json` (atomic updates).
3. For each ceiling in `budgets.json`:
   - `ratio = current_total / ceiling`
   - For each threshold ∈ {0.50, 0.80, 1.00}: if `ratio` crossed from below to above AND `(threshold, scope, scope_key)` not in recent debounce log → emit `pech.budget.threshold.crossed`.
4. Append the crossing decision (fire / debounce-skip) to `state/thresholds.jsonl` with reason.

**Success criterion:** counters updated atomically (temp-write + rename); at most one event per threshold-scope-window; no stdout pollution.

## Outputs

- Updated `state/counters.json`
- Appended `state/thresholds.jsonl`
- Event published via `shared/scripts/pech_publish.py` (which rate-limits to honor the per-window contract)

## Handoff

Downstream subscribers: Wixie (switches to cheaper model on 80%+ crossings), Sylph (defers PR polish on 100% crossings), Emu (trims context aggressively on any crossing).

## Failure modes

| Code | Scenario | Counter |
|------|----------|---------|
| F09 | Two hooks writing `counters.json` concurrently | Use `@../vis/packages/core/conduct/tool-use.md` § atomic write pattern (write-to-tmp + fsync + rename) |
| F05 | Emit threshold event repeatedly on every call past the ceiling | Debounce in `thresholds.jsonl` is mandatory — read it first |
| F13 | Counter inflation from stale session.json on multi-developer/shared state | `session_id` from `ENCHANTED_ATTRIBUTION` scopes the counter; never share |
