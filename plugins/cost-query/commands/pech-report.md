---
description: Generate a dark-themed single-page PDF cost audit with Opus-narrated anomaly diagnosis.
---

# /pech-report

Full cost audit for the current session (or a prior session by `--session-id`). Produces a dark-themed single-page PDF combining:

- Total spend + L1 forecast with ±2σ band
- Attribution breakdown (plugin → tier → model)
- L2 threshold crossings (50/80/100% with timestamps)
- L3 anomaly list, each with Opus-narrated diagnosis
- L4 cache-waste report ($ wasted on unread prompt-cache writes)
- L5 delta from rolling mean — "this session vs. your historical pattern"

## Usage

```
/pech-report                                    # current session
/pech-report --session-id=<uuid>                # prior session
/pech-report --day=2026-04-19                   # full day
/pech-report --output=path/to/report.pdf        # custom output path
```

## Arguments

| Argument | Type | Default | Purpose |
|----------|------|---------|---------|
| `--session-id` | string | current | Audit a specific prior session |
| `--day` | date | null | Audit a full day (roll-up across all sessions on that date) |
| `--output` | path | `state/reports/report-YYYY-MM-DD-HHMMSS.pdf` | Where to write the PDF |
| `--open` | flag | off | Open the PDF after generation (platform-dependent) |

## Pipeline

1. `generate-report` skill (Sonnet) aggregates data from every sub-plugin's state.
2. For each anomaly in `budget-watcher/state/anomalies.jsonl`, the `anomaly-narrator` agent (Opus) generates a 2-4 sentence diagnosis.
3. HTML template filled with the aggregated data + narratives.
4. Rendered to PDF via `docs/architecture/generate.py` + Chrome headless (`docs/assets/puppeteer.config.json`).

## Cost

Generating a report with N anomalies costs approximately `$0.04 + N × $0.005` (Sonnet for aggregation + Opus per narrative). Amortized over the developer's insight gained — the report is typically generated a few times per week, not per session.

## Invokes

Triggers `generate-report` skill. See [../skills/generate-report/SKILL.md](../skills/generate-report/SKILL.md).
