# cost-query

*Part of [Pech](../../README.md) — Cost Ledger for AI-Assisted Development.*

The developer's query surface into Pech's state. Every state file written by `cost-tracker`, `budget-watcher`, and `nook-learning` is readable through these commands — no raw JSON digging required.

## Slash commands

| Command | Function | Agent tier |
|---------|----------|------------|
| `/pech-cost [--session\|--day\|--month]` | Current spend with attribution breakdown | Haiku (formatter) |
| `/pech-forecast [--session\|--day\|--month]` | L1 forecast with ±2σ band | Sonnet (via cost-tracker/forecaster) |
| `/pech-attribute [--last=N] [--tool=<name>] [--plugin=<slug>]` | Break down last N calls by attribution axis | Haiku (filter + format) |
| `/pech-report` | Phase 2 — PDF report (puppeteer pending); Phase 1 emits structured JSONL summary only | Opus (narrator) + Sonnet (rendering) |

## No hooks

cost-query has zero hook bindings. All invocations are developer-initiated via slash command. This is the *only* Pech sub-plugin that's skill-invoked rather than hook-driven — keeping the observation and query paths cleanly separated.

## Outputs

- `/pech-cost` and `/pech-attribute`: plain-text tables for conversation context
- `/pech-forecast`: plain-text table + optional JSON for scripting (`--json` flag)
- `/pech-report`: Phase 2 — dark-themed single-page PDF at `state/reports/report-YYYY-MM-DD-HHMMSS.pdf` (puppeteer pending); Phase 1 emits structured JSONL summary only

## Events

**Publishes:** none (query surface is passive)

**Subscribes:** none (reads state directly, not via bus)

## Brand invariants

- Plain-text output for terminal consumers; PDF only for `/pech-report`
- Never fabricate data to fill an empty table — if the ledger is empty, say so
- Anomaly narrative only runs Opus when explicitly triggered via `/pech-report` — amortize the orchestrator cost
