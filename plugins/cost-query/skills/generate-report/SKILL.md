---
name: generate-report
description: >
  Aggregates state across all 5 Pech sub-plugins and renders a dark-themed single-page
  PDF cost audit. Invokes anomaly-narrator agent (Opus) once per anomaly for
  human-readable diagnoses; invokes forecaster agent (Sonnet) for the forecast block.
  Use when: /pech-report slash command fires. Do not use for live session display (see
  cost-display) — report generation is a heavy operation costing ~$0.04 + $0.005 per
  anomaly.
model: sonnet
tools: [Read, Write, Bash]
phase2_status: "Phase 2 — PDF generation pending (puppeteer + Chrome headless not yet wired). Phase 1 emits structured JSONL summary only."
---

# generate-report

## Preconditions

- At least one session has been observed (ledger has ≥ 1 row)
- `docs/assets/package.json` has been `npm install`'d — puppeteer + mermaid-cli required for PDF rendering

## Inputs

- **Scope:** current session (default), `--session-id=<uuid>`, or `--day=<date>`
- **Output path:** default `state/reports/report-<timestamp>.pdf`

## Steps

1. **Aggregate.** Read and combine:
   - `plugins/cost-tracker/state/ledger-YYYY-MM.jsonl` (all rows in scope)
   - `plugins/cost-tracker/state/session.json#forecast` (or re-run `forecast-cost` skill)
   - `plugins/budget-watcher/state/thresholds.jsonl` (crossings in scope)
   - `plugins/budget-watcher/state/anomalies.jsonl` (anomalies in scope)
   - `plugins/nook-learning/state/learnings.json` (for L5 delta)
2. **Narrate anomalies.** For each anomaly row, delegate to `budget-watcher/agents/anomaly-triager` (Opus) with the row + surrounding ledger context. Collect the returned narratives.
3. **Render HTML.** Fill the report template (at `templates/report.html` — inline in this skill's dir for now) with: header, total, forecast block, attribution table, threshold-crossing timeline, anomaly section (with narratives), cache-waste summary, L5 delta.
4. **Render PDF.** Call `docs/architecture/generate.py --report-html=<html> --out=<pdf-path>` — which internally invokes Chrome headless via `docs/assets/puppeteer.config.json`.
5. Write PDF to output path. Return path + summary JSON.

**Success criterion:** PDF exists at the expected path, file size > 10KB (empty PDFs are a rendering failure), summary JSON returned with all aggregated stats.

## Outputs

- PDF at `state/reports/report-<timestamp>.pdf`
- Summary JSON: `{total_usd, n_anomalies, n_threshold_crossings, forecast, report_path}`

## Handoff

`/pech-report` slash command displays the PDF path; user opens it manually (or via `--open` flag).

## Failure modes

| Code | Scenario | Counter |
|------|----------|---------|
| F10 | PDF generation fails silently with an empty file | Check file size > 10KB; fail loudly with the Chrome headless stderr |
| F11 | Suppress anomaly rows from the report because they "look scary" | All anomalies go in the report; suppression defeats the audit |
| F13 | Inline all 30 anomaly narratives at full Opus tier — cost explodes | Cap narratives at 10 (top anomalies by |z-score|); tabulate the rest without narrative |
| F14 | Use stale rate card for historical session replay without flagging | Report header must show `rate_card_effective_from` for the session being audited |
